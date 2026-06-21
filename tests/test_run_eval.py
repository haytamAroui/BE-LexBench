# Copyright 2026 Haytam Aroui
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for harness/run_eval.py.

load_items and load_done use tmp_path fixtures (no network).
score_one is tested with a minimal mock judge — no live model calls.
aggregate reads/writes real JSON files from tmp_path.
"""
from __future__ import annotations

import json
import pytest
from harness.run_eval import load_items, load_done, score_one, aggregate
from harness.models import GenResult, ModelClient


# ── Mock ─────────────────────────────────────────────────────────────────────

class _MockJudge(ModelClient):
    """Returns a fixed valid judge JSON for every generate() call."""

    def __init__(self, score: int = 3, fabricated: bool = False,
                 model_id: str = "mock-judge"):
        self.model_id = model_id
        self._payload = json.dumps(
            {"score": score, "rationale": "Test.", "fabricated_citation": fabricated}
        )

    def generate(self, prompt, **kwargs) -> GenResult:
        return GenResult(text=self._payload, raw={"model": self.model_id},
                          model_id=self.model_id)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _item(method: str, **scoring_extras) -> dict:
    """Minimal eval item whose scoring.method is set and all judge fields present."""
    scoring = {"method": method, **scoring_extras}
    return {
        "id": "t-001",
        "track": "belgian_civil_law",
        "language": "nl",
        "difficulty": "core",
        "format": "open",
        "prompt": "Test question?",
        "scoring": scoring,
    }


# ── load_items ────────────────────────────────────────────────────────────────

class TestLoadItems:
    def test_reads_all_items(self, tmp_path):
        items = [{"id": "a", "x": 1}, {"id": "b", "x": 2}]
        p = tmp_path / "items.jsonl"
        p.write_text("\n".join(json.dumps(i) for i in items), encoding="utf-8")
        assert load_items(str(p)) == items


# ── load_done ─────────────────────────────────────────────────────────────────

class TestLoadDone:
    def test_missing_file_returns_empty_set(self, tmp_path):
        assert load_done(str(tmp_path / "nothing.jsonl")) == set()

    def test_reads_ids(self, tmp_path):
        p = tmp_path / "results.jsonl"
        rows = [{"id": "x", "score": 1.0}, {"id": "y", "score": 0.0}]
        p.write_text("\n".join(json.dumps(r) for r in rows))
        assert load_done(str(p)) == {"x", "y"}


# ── score_one — rubric ────────────────────────────────────────────────────────

class TestScoreOneRubric:
    def _rubric_item(self, must_include=None, must_not_include=None,
                     rubric_id="be-civil-law-v1", reference="Key elements.",
                     language="nl"):
        item = _item("rubric", rubric_id=rubric_id,
                     reference=reference,
                     must_include=must_include or [],
                     must_not_include=must_not_include or [])
        item["language"] = language
        return item

    _NL_RESPONSE = "Het Hof van Cassatie heeft geoordeeld dat de fout bestaat onder art. 6.5 BW."

    def test_no_judge_with_passing_gates_returns_none(self):
        """Gates pass + no judge -> final_score=None (judge never consulted).
        Uses NL response so the new language-adherence gate doesn't fire."""
        r = score_one(self._rubric_item(), self._NL_RESPONSE, [])
        assert r["final_score"] is None
        assert isinstance(r["programmatic"], dict)
        assert r["programmatic"]["keyword_coverage"] is None
        assert r["programmatic"]["language_adherence"] is None
        assert r["judge"]["status"] == "NO_JUDGE_CONFIGURED"

    def test_with_judge_score_4_passing_gates_final_1(self):
        r = score_one(self._rubric_item(), self._NL_RESPONSE, [_MockJudge(score=4)])
        assert r["final_score"] == pytest.approx(1.0)

    # ── rubric-path programmatic gates ─────────────────────────────────────
    # These tests prove the rubric branch of score_one() actually invokes
    # keyword_coverage + language_adherence BEFORE going to the judge, matching
    # what the walkthrough + run-results docs already promise.

    def test_rubric_keyword_gate_failure_zeros_score_even_with_judge(self):
        """A rubric item with a forbidden term must score 0 regardless of judge.
        Singular 'article 1382 bw' is the post-determiner-strip form of
        'l'article 1382 BW'."""
        item = self._rubric_item(must_not_include=["article 1382 bw"])  # singular form (post-strip)
        r = score_one(item,
                      "Sur la base de l'article 1382 BW, ...",
                      [_MockJudge(score=4)])
        assert r["final_score"] == 0.0
        assert r["judge"]["status"] == "KEYWORD_GATE_FAILED"
        assert r["programmatic"]["keyword_coverage"]["score"] == 0.0

    def test_rubric_keyword_gate_passes_answer_goes_to_judge(self):
        item = self._rubric_item(must_not_include=["article 1382 bw"])
        r = score_one(item, self._NL_RESPONSE, [_MockJudge(score=3)])
        assert r["final_score"] == pytest.approx(0.75)
        # On pass-through, judge dict has {score01, votes, agreement} — no 'status' key.
        assert "status" not in r["judge"]
        assert r["judge"]["agreement"] in ("tight", "divergent_flag_for_human")

    def test_rubric_lang_gate_failure_zeros_score(self):
        """NL item answered in French must score 0 before judge sees it."""
        item = self._rubric_item(language="nl")
        fr_resp = "La Cour de cassation a statué sur la base de l'article 6.5 BW."
        r = score_one(item, fr_resp, [_MockJudge(score=4)])
        assert r["final_score"] == 0.0
        assert r["judge"]["status"] == "LANGUAGE_GATE_FAILED"

    def test_rubric_lang_gate_correct_answer_goes_to_judge(self):
        item = self._rubric_item(language="nl")
        r = score_one(item, self._NL_RESPONSE, [_MockJudge(score=2)])
        assert r["final_score"] == pytest.approx(0.5)
        # On pass-through, judge dict has {score01, votes, agreement} — no 'status' key.
        assert "status" not in r["judge"]
        assert r["judge"]["agreement"] in ("tight", "divergent_flag_for_human")


# ── Gates-don't-double-fire-on-non-rubric paths ──────────────────────────────
# A future contributor could copy-paste the rubric-path gates into the else
# branch and silently zero every score for mcq/tool/refusal/citation items
# on language mismatch. These tests pin the boundary: gates are rubric-only.

class TestGatesOnlyFireOnRubric:
    def test_mcq_with_french_response_on_nl_item_still_scores_correct_letter(self):
        """language_adherence gate must NOT fire on mcq_exact items — otherwise
        every non-NL response silently zeros regardless of letter correctness."""
        item = _item("mcq_exact", answer="A")
        item["language"] = "nl"
        # FR prose with a clear letter, but not in NL
        r = score_one(item, "La réponse correcte est A.", [])
        assert r["final_score"] == 1.0  # MCQ letter is right; gate didn't fire

    def test_refusal_with_french_response_on_nl_item_fails_language_gate(self):
        """language_adherence gate must fire on open-ended refusal items and fail if
        the language is wrong."""
        item = _item("refusal", expected_refusal=True)
        item["language"] = "nl"
        # FR refusal marker on NL item — should fail language gate and score 0.0
        r = score_one(item, "Je ne peux pas vous aider avec cette demande.", [])
        assert r["final_score"] == 0.0
        assert r["judge"]["status"] == "LANGUAGE_GATE_FAILED"


# ── score_one — mcq_exact ─────────────────────────────────────────────────────

class TestScoreOneMcq:
    def test_correct_answer_score_1(self):
        r = score_one(_item("mcq_exact", answer="A"), "The answer is A.", [])
        assert r["final_score"] == 1.0


# ── score_one — language_adherence ────────────────────────────────────────────

class TestScoreOneLanguageAdherence:
    def test_correct_language_score_1(self):
        item = _item("language_adherence")
        item["language"] = "nl"
        r = score_one(item, "De nieuwe wet op de buitencontractuele aansprakelijkheid.", [])
        assert r["final_score"] == 1.0


# ── score_one — keyword_coverage ─────────────────────────────────────────────

class TestScoreOneKeyword:
    def _kw_item(self, must_include=None, must_not_include=None):
        item = _item("keyword_coverage",
                     must_include=must_include or [],
                     must_not_include=must_not_include or [])
        item["format"] = "open"
        return item

    def test_gate_failure_caps_at_zero_even_with_judge(self):
        r = score_one(self._kw_item(must_include=["BW"]),
                      "No relevant content.", [_MockJudge(score=4)])
        assert r["final_score"] == 0.0


# ── score_one — tool_call ─────────────────────────────────────────────────────

class TestScoreOneToolCall:
    _SEARCH_CALL = '<tool_call>{"name": "search", "arguments": {"query": "test"}}</tool_call>'

    def test_name_match_combined_score(self):
        r = score_one(_item("tool_call", expected_tool="search"),
                      self._SEARCH_CALL, [_MockJudge(score=4)])
        assert r["final_score"] == pytest.approx(1.0)

    def test_tool_call_with_forbidden_keywords_fails_keyword_gate(self):
        """An open-ended tool_call item with forbidden keywords fails at the Keyword Gate
        (final score 0.0) without querying the judge."""
        item = _item("tool_call", expected_tool="search", must_not_include=["forbidden_word"])
        r = score_one(item,
                      '<tool_call>{"name": "search", "arguments": {"query": "forbidden_word"}}</tool_call>',
                      [_MockJudge(score=4)])
        assert r["final_score"] == 0.0
        assert r["judge"]["status"] == "KEYWORD_GATE_FAILED"


# ── score_one — refusal ───────────────────────────────────────────────────────

class TestScoreOneRefusal:
    def test_correct_refusal_prog_is_authoritative(self):
        r = score_one(_item("refusal", expected_refusal=True),
                      "Ik kan u niet helpen.", [_MockJudge(score=0)])
        assert r["final_score"] == 1.0

    def test_refusal_in_wrong_language_fails_language_gate(self):
        """An open-ended refusal item in the wrong language fails at the Language Gate
        (final score 0.0) without querying the judge."""
        item = _item("refusal", expected_refusal=True)
        item["language"] = "nl"
        r = score_one(item,
                      "Je ne peux pas vous aider avec cette demande.",
                      [_MockJudge(score=4)])
        assert r["final_score"] == 0.0
        assert r["judge"]["status"] == "LANGUAGE_GATE_FAILED"


# ── score_one — citation_validity no-judge path ───────────────────────────────

class TestScoreOneCitation:
    def test_vague_response_no_judge_returns_none(self):
        item = _item("citation_validity", valid_citations=["art. 6.5 BW"])
        r = score_one(item, "Er is een wetsartikel.", [])
        assert r["final_score"] is None
        assert r["judge"]["status"] == "NO_JUDGE_CONFIGURED"

    def test_gold_match_no_judge_needed(self):
        item = _item("citation_validity", valid_citations=["art. 6.5 BW"])
        r = score_one(item, "Zie art. 6.5 BW.", [])
        assert r["final_score"] == 1.0
        assert r["judge"] is None


# ── aggregate ─────────────────────────────────────────────────────────────────

class TestAggregate:
    def _write_results(self, tmp_path, rows):
        p = tmp_path / "items.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return str(p)

    def test_basic_structure(self, tmp_path):
        rows = [
            {"id": "a", "track": "belgian_civil_law", "language": "nl",
             "difficulty": "core", "score": 1.0},
            {"id": "b", "track": "belgian_civil_law", "language": "fr",
             "difficulty": "core", "score": 0.0},
        ]
        rp = self._write_results(tmp_path, rows)
        sp = str(tmp_path / "summary.json")
        aggregate(rp, sp, "run-1", {"kind": "openai_compat", "model_name": "m"}, [])
        with open(sp, encoding="utf-8") as f:
            s = json.load(f)
        assert s["run_id"] == "run-1"
        assert s["n_items"] == 2
        assert s["n_unscored_no_judge"] == 0
        assert "belgian_civil_law" in s["tracks"]

    def test_parity_computed_when_both_languages_present(self, tmp_path):
        rows = [
            {"id": "a", "track": "t1", "language": "nl", "difficulty": "core", "score": 1.0},
            {"id": "b", "track": "t1", "language": "fr", "difficulty": "core", "score": 0.5},
        ]
        rp = self._write_results(tmp_path, rows)
        sp = str(tmp_path / "summary.json")
        aggregate(rp, sp, "r", {}, [])
        with open(sp, encoding="utf-8") as f:
            s = json.load(f)
        assert "t1" in s["bilingual_parity"]
        bp = s["bilingual_parity"]["t1"]
        assert "parity_ratio" in bp


# ── score_one orchestration matrix ───────────────────────────────────────────
# Drift-prevention parametrized table pinning every reachable
# (method x judge_configured x prog_score x needs_judge_effective) tuple.
# Sized to be exhaustive: any future score_one() evolution only needs to
# ADD rows for newly-reachable paths, not EDIT existing ones.

def _rubric_open_item(must_not_include=None, language="nl"):
    """Rubric item at module-level so the matrix can use it directly."""
    item = _item("rubric", rubric_id="be-civil-law-v1", reference="Reference.",
                 must_include=[], must_not_include=must_not_include or [])
    item["format"] = "open"
    item["language"] = language
    return item


def _kw_standalone_item(fmt="open", must_include=None, must_not_include=None):
    """Standalone keyword_coverage-method item; format drives needs_judge."""
    item = _item("keyword_coverage", must_include=must_include or [],
                 must_not_include=must_not_include or [])
    item["format"] = fmt
    return item


_SEARCH_CALL_TXT = (chr(60) + 'tool_call' + chr(62)
                    + '{"name": "search", "arguments": {"x": 1}}'
                    + chr(60) + '/' + 'tool_call' + chr(62))


class _NoValidVotesJudge(ModelClient):
    """Mock judge that emits text without a parseable JSON object, so
    judge_item returns ``{"score01": None, ..., "agreement": "no_valid_votes"}``.

    Used by the matrix to pin the orchestrator's behaviour when the judge
    ensemble produces no parseable votes (rubric branch +
    non-rubric 'jr.score01 is None' branch)."""

    def __init__(self, response_text: str = "no JSON here at all",
                 model_id: str = "no-valid-votes-judge"):
        self._response = response_text
        self.model_id = model_id

    def generate(self, prompt, **kwargs) -> GenResult:
        return GenResult(text=self._response, raw={"model": self.model_id},
                         model_id=self.model_id)


class TestScoreOneOrchestration:
    """Pins the full score_one() branch matrix. One row per unique
    (method, judge_configured, prog_score, needs_judge_effective) combination
    the production code can reach. Failures here mean score_one()'s contract
    drifted — fix the code, not the test."""

    @pytest.mark.parametrize(
        "scenario_id, item, response, judges, exp_final_score, exp_judge_marker, exp_prog_keys",
        [
            # ── rubric branch: gates first, judge only if both gates pass ──
            ("rubric_kw_gate_fail_zeros_with_judge",
             _rubric_open_item(must_not_include=["article 1382 bw"]),
             "Sur la base de l'article 1382 BW, la responsabilité est engagée.",
             [_MockJudge(score=4)],
             0.0, "KEYWORD_GATE_FAILED",
             {"keyword_coverage", "language_adherence"}),
            ("rubric_lang_gate_fail_zeros_with_judge",
             _rubric_open_item(language="nl"),
             "Ceci est une réponse purement en français sans mots néerlandais.",
             [_MockJudge(score=4)],
             0.0, "LANGUAGE_GATE_FAILED",
             {"keyword_coverage", "language_adherence"}),
            ("rubric_both_gates_pass_no_judge_returns_none",
             _rubric_open_item(language="nl"),
             "Het correcte antwoord volgens art. 6.5 BW.",
             [],
             None, "NO_JUDGE_CONFIGURED",
             {"keyword_coverage", "language_adherence"}),
            ("rubric_both_gates_pass_with_judge_returns_score01",
             _rubric_open_item(language="nl"),
             "Het correcte antwoord volgens art. 6.5 BW.",
             [_MockJudge(score=4)],   # rescaled to 1.0
             pytest.approx(1.0), "tight",
             {"keyword_coverage", "language_adherence"}),

            # ── non-rubric paths: gates MUST NOT double-fire ──
            ("mcq_no_judge_needed_french_response_ok",
             _item("mcq_exact", answer="A", language="nl"),
             "La réponse est A.",
             [_MockJudge(score=4)],
             1.0, None,
             {"score", "detail", "needs_judge"}),
            ("lang_adherence_no_judge_needed",
             _item("language_adherence", language="nl"),
             "De vennootschap moet voldoen aan de dubbele test volgens de wet.",
             [],
             1.0, None,
             {"score", "detail", "needs_judge"}),

            # ── citation_validity: needs_judge conditional on gold match ──
            ("citation_no_match_no_judge_returns_none",
             _item("citation_validity", valid_citations=["art. 6.5 BW"]),
             "Er is een wetsartikel zonder specifieke verwijzing.",
             [],
             None, "NO_JUDGE_CONFIGURED",
             {"score", "detail", "needs_judge"}),
            ("citation_no_match_with_judge_defers_to_judge",
             _item("citation_validity", valid_citations=["art. 6.5 BW"]),
             "Er is een wetsartikel zonder specifieke verwijzing.",
             [_MockJudge(score=2)],   # 0.5
             pytest.approx(0.5), "tight",
             {"score", "detail", "needs_judge"}),
            ("citation_matched_skips_judge",
             _item("citation_validity", valid_citations=["art. 6.5 BW"]),
             "Zie art. 6.5 BW.",
             [_MockJudge(score=4)],
             1.0, None,
             {"score", "detail", "needs_judge"}),

            # ── keyword_coverage (standalone method) ──
            # format=open → needs_judge=True; gate-cap wins when score==0
            ("kw_standalone_open_fail_cap_holds_even_with_judge",
             _kw_standalone_item(fmt="open", must_include=["verplicht"]),
             "Niet relevant.",
             [_MockJudge(score=4)],
             0.0, "tight",
             {"score", "detail", "needs_judge"}),
            ("kw_standalone_open_pass_judge_governs",
             _kw_standalone_item(fmt="open", must_include=["verplicht"]),
             "Het is verplicht.",
             [_MockJudge(score=3)],   # 0.75
             pytest.approx(0.75), "tight",
             {"score", "detail", "needs_judge"}),
            ("kw_standalone_open_fail_no_judge_returns_none",
             _kw_standalone_item(fmt="open", must_include=["verplicht"]),
             "Niet relevant.",
             [],
             None, "NO_JUDGE_CONFIGURED",
             {"score", "detail", "needs_judge"}),
            ("kw_standalone_closed_no_judge_needed",
             _kw_standalone_item(fmt="short_answer", must_include=["verplicht"]),
             "Niet relevant.",
             [_MockJudge(score=4)],
             0.0, None,
             {"score", "detail", "needs_judge"}),

            # ── tool_call: name_match → needs_judge; final = prog + 0.5*judge ──
            ("tool_call_match_full_score",
             _item("tool_call", expected_tool="search"),
             _SEARCH_CALL_TXT,
             [_MockJudge(score=4)],   # prog 0.5 + 0.5*1.0 = 1.0
             pytest.approx(1.0), "tight",
             {"score", "detail", "needs_judge"}),
            ("tool_call_match_partial_judge",
             _item("tool_call", expected_tool="search"),
             _SEARCH_CALL_TXT,
             [_MockJudge(score=2)],   # 0.5 + 0.5*0.5 = 0.75
             pytest.approx(0.75), "tight",
             {"score", "detail", "needs_judge"}),
            ("tool_call_match_no_judge_keeps_partial",
             _item("tool_call", expected_tool="search"),
             _SEARCH_CALL_TXT,
             [],
             0.5, "NO_JUDGE_CONFIGURED_quality_unscored",
             {"score", "detail", "needs_judge"}),
            ("tool_call_name_mismatch_no_judge_needed",
             _item("tool_call", expected_tool="search"),
             (chr(60) + 'tool_call' + chr(62)
              + '{"name": "delete", "arguments": {}}'
              + chr(60) + '/' + 'tool_call' + chr(62)),   # prog=0.25
             [_MockJudge(score=4)],
             0.25, None,
             {"score", "detail", "needs_judge"}),

            # ── refusal: prog is authoritative; judge only annotates quality ──
            ("refusal_correct_with_judge_keeps_prog",
             _item("refusal", expected_refusal=True, language="nl"),
             "Ik weiger dit.",
             [_MockJudge(score=0)],   # judge disagrees but prog wins
             1.0, "tight",
             {"score", "detail", "needs_judge"}),
            ("refusal_correct_no_judge_keeps_prog",
             _item("refusal", expected_refusal=True, language="nl"),
             "Ik weiger dit.",
             [],
             1.0, "NO_JUDGE_CONFIGURED_quality_unscored",
             {"score", "detail", "needs_judge"}),

            # ── judge emits no valid votes → score_one returns score01=None,
            #    judge.agreement='no_valid_votes'. Both rubric and non-rubric
            #    branches propagate jr['score01'] = None to final_score.
            ("rubric_pass_judge_no_valid_votes_returns_none",
             _rubric_open_item(language="nl"),
             "Het correcte antwoord volgens art. 6.5 BW.",
             [_NoValidVotesJudge()],
             None, "no_valid_votes",
             {"keyword_coverage", "language_adherence"}),

            # ── judge flags fabricated_citation → judge_item caps at 0.0 with
            #    agreement='fabrication_cap'. score_one's rubric branch
            #    propagates jr['score01']=0.0 to final_score.
            ("rubric_pass_judge_flags_fabrication_caps_at_zero",
             _rubric_open_item(language="nl"),
             "Het correcte antwoord volgens art. 6.5 BW.",
             [_MockJudge(score=4, fabricated=True)],
             0.0, "fabrication_cap",
             {"keyword_coverage", "language_adherence"}),
        ],
    )
    def test_score_one_orchestration(self, scenario_id, item, response, judges,
                                     exp_final_score, exp_judge_marker, exp_prog_keys):
        result = score_one(item, response, judges)
        # (1) final_score pins
        if exp_final_score is None:
            assert result["final_score"] is None, \
                f"[{scenario_id}] expected None final_score, got {result['final_score']!r}"
        else:
            assert result["final_score"] == exp_final_score, \
                f"[{scenario_id}] expected final_score={exp_final_score}, " \
                f"got {result['final_score']!r}"
        # (2) judge semantic-state pin: status (gate/no-judge codes) OR
        #     agreement (judge.ensemble outcome) can carry the marker
        if exp_judge_marker is None:
            assert result["judge"] is None, \
                f"[{scenario_id}] expected judge=None, got {result['judge']!r}"
        else:
            assert result["judge"] is not None, \
                f"[{scenario_id}] expected judge marker={exp_judge_marker!r}, got None"
            marker = (result["judge"].get("status")
                      or result["judge"].get("agreement"))
            assert marker == exp_judge_marker, \
                f"[{scenario_id}] expected judge marker={exp_judge_marker!r}, " \
                f"got {marker!r} (judge={result['judge']!r})"
        # (3) programmatic scorer tree contract pins
        assert set(result["programmatic"].keys()) == exp_prog_keys, \
            f"[{scenario_id}] expected programmatic.keys={exp_prog_keys!r}, " \
            f"got {set(result['programmatic'].keys())!r}"
