# Copyright 2026 Haytam Aroui
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for harness/scorers.py.

Covers all programmatic scorers:
- extract_citations / citation_validity — Belgian ECLIs, statutes, Code articles, Moniteur Belge
- mcq_exact — all five extraction strategies, CoT reasoning models
- language_adherence — NL/FR/EN heuristic
- keyword_coverage — must_include gate, must_not_include, format-driven needs_judge
- refusal — markers, over_refusal vs harmful_compliance in NL/FR/EN
- tool_call — all four wire formats, scoring tiers (0 / 0.25 / 0.5)

Round 3 additions:
- _normalize() now strips leading NL/FR determiners before substring match,
  so FR 'l'article 1382 BW' actually fails must_not_include=['article 1382 bw'].
- TestNormalizeScope pins the FR+NL-only contract so a future contributor
  extending the strip to other languages gets a deliberate signal.
"""
from __future__ import annotations

from harness.scorers import (
    extract_citations, citation_validity,
    mcq_exact, language_adherence, keyword_coverage, refusal, tool_call,
    _normalize,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _item(golds: list[str]) -> dict:
    """Minimal eval item with citation_validity scoring fields."""
    return {"scoring": {"valid_citations": golds}}


# ── extract_citations ─────────────────────────────────────────────────────────

class TestExtractCitations:
    def test_ecli_extracted(self):
        cites = extract_citations("The case ECLI:BE:CASS:2020:ARR.20201030.1N.4 is relevant.")
        assert any("ECLI:BE:CASS:2020:ARR.20201030.1N.4" in c for c in cites)

    def test_gwh_extracted(self):
        cites = extract_citations("Grondwettelijk Hof nr. 149/2025 provides the standard.")
        assert any("nr. 149/2025" in c for c in cites)

    def test_cass_cite_extracted(self):
        cites = extract_citations("Cass., 15 september 2023, C.22.0123.N specifies...")
        assert any("C.22.0123.N" in c for c in cites)

    def test_moniteur_extracted(self):
        cites = extract_citations("Published in M.B. 23.12.2025.")
        assert any("M.B. 23.12.2025" in c for c in cites)

    def test_statute_extracted(self):
        cites = extract_citations("The Wet van 30 juli 2018 is the privacy law.")
        assert any("Wet van 30 juli 2018" in c for c in cites)

    def test_code_art_extracted(self):
        cites = extract_citations("Refer to art. 6.5 BW or art. IV.1 WER.")
        assert any("art. 6.5 BW" in c for c in cites)
        assert any("art. IV.1 WER" in c for c in cites)

    def test_justel_extracted(self):
        cites = extract_citations("Dossier 2024-04-26/07 is in the database.")
        assert any("2024-04-26/07" in c for c in cites)

    def test_no_false_positive_on_plain_number(self):
        cites = extract_citations("There are 1457 pages in the document.")
        # A bare number with no citation marker should not be extracted
        assert not any("1457" in c for c in cites)

    def test_deduplication(self):
        text = "art. 6.5 BW and art. 6.5 BW again."
        cites = extract_citations(text)
        assert len([c for c in cites if "6.5 BW" in c]) == 1


# ── citation_validity ─────────────────────────────────────────────────────────

class TestCitationValidity:
    def test_belgian_code_gold_match(self):
        gold = "art. 6.5 BW"
        response = "De aansprakelijkheid is geregeld in art. 6.5 BW."
        result = citation_validity(response, _item([gold]))
        assert result["score"] == 1.0
        assert result["needs_judge"] is False

    def test_ecli_gold_match(self):
        gold = "ECLI:BE:CASS:2020:ARR.20201030.1N.4"
        response = "The leading case is ECLI:BE:CASS:2020:ARR.20201030.1N.4."
        result = citation_validity(response, _item([gold]))
        assert result["score"] == 1.0
        assert result["needs_judge"] is False

    def test_vague_prose_routes_to_judge_when_gold_exists(self):
        gold = "art. 6.5 BW"
        response = "De nieuwe wet op de buitencontractuele aansprakelijkheid is van toepassing."
        result = citation_validity(response, _item([gold]))
        assert result["needs_judge"] is True
        assert result["score"] == 0.0

    def test_confirmed_hallucination_stays_zero_no_judge(self):
        gold = "art. 6.5 BW"
        fabricated = "art. 9.99 BW"
        response = f"Zie {fabricated}."

        def verifier(cite: str) -> bool:
            return False

        result = citation_validity(response, _item([gold]), verifier=verifier)
        assert result["score"] == 0.0
        assert result["needs_judge"] is False
        assert result["detail"]["hallucinated"] == 1

    def test_punctuation_insensitive_gold_match(self):
        gold = "art. 6.5 BW"
        response = "De aansprakelijkheid is geregeld in Art. 6.5 B.W."
        result = citation_validity(response, _item([gold]))
        assert result["score"] == 1.0


# ── mcq_exact ─────────────────────────────────────────────────────────────────

def _mcq(answer, choices=None):
    return {"scoring": {"answer": answer}, "choices": choices or []}


class TestMcqExact:
    def test_bare_letter_whole_response(self):
        r = mcq_exact("B", _mcq("B"))
        assert r["score"] == 1.0
        assert r["detail"]["extraction"] == "bare"

    def test_explicit_answer_is_commitment(self):
        r = mcq_exact("The answer is A.", _mcq("A"))
        assert r["score"] == 1.0

    def test_reasoning_model_cot_then_final_answer(self):
        response = (
            "Laat me dit analyseren. A is niet correct. "
            "B is mogelijk. Maar de netto-actieftest en liquiditeitstest maken het A. "
            "Het juiste antwoord is dus A."
        )
        r = mcq_exact(response, _mcq("A"))
        assert r["score"] == 1.0


# ── language_adherence ────────────────────────────────────────────────────────

def _lang_item(lang):
    return {"language": lang}


class TestLanguageAdherence:
    def test_dutch_response_nl_item(self):
        r = language_adherence(
            "De vennootschap moet voldoen aan de dubbele test volgens de wet.",
            _lang_item("nl"),
        )
        assert r["score"] == 1.0
        assert r["detail"]["got"] == "nl"

    def test_french_response_fr_item(self):
        r = language_adherence(
            "La société doit respecter le double test conformément à la loi.",
            _lang_item("fr"),
        )
        assert r["score"] == 1.0
        assert r["detail"]["got"] == "fr"

    def test_english_response_en_item(self):
        r = language_adherence(
            "The company must comply with the twin peaks model under Belgian law.",
            _lang_item("en"),
        )
        assert r["score"] == 1.0
        assert r["detail"]["got"] == "en"

    def test_french_response_nl_item_scores_zero(self):
        r = language_adherence(
            "La société doit respecter le double test.",
            _lang_item("nl"),
        )
        assert r["score"] == 0.0


# ── keyword_coverage ──────────────────────────────────────────────────────────

def _kw_item(must_include=None, must_not_include=None, fmt="open"):
    return {
        "format": fmt,
        "scoring": {
            "must_include": must_include or [],
            "must_not_include": must_not_include or [],
        },
    }


class TestKeywordCoverage:
    def test_all_required_terms_present(self):
        r = keyword_coverage(
            "De WVV vereist de netto-actieftest en de liquiditeitstest.",
            _kw_item(must_include=["netto-actieftest", "liquiditeitstest"]),
        )
        assert r["score"] == 1.0

    def test_must_not_include_catches_l_apostrophe_article(self):
        """FR 'l'article 1382 BW' normalises to 'article 1382 bw' (post l'-strip)
        which IS a substring of must_not_include=['article 1382 bw'].

        Note on plural/singular inflection: this fixture uses the SINGULAR form
        in must_not_include so the l'-strip alone makes the match. Plural-vs-
        singular inflection tolerance is a SEPARATE normalisation problem and
        is intentionally out of scope for this gate's determiner-strip work."""
        r = keyword_coverage(
            "Sur la base de l'article 1382 BW, la responsabilité est engagée.",
            _kw_item(must_not_include=["article 1382 bw"]),
        )
        assert r["score"] == 0.0
        assert "article 1382 bw" in r["detail"]["present_forbidden"]

    def test_must_not_include_catches_la_les_het_de_forms(self):
        """Each fixture has a contiguous post-strip substring that exactly
        matches the must_not substring. Built deliberately so the only thing
        making the match is the determiner strip — not word order or
        inflection."""
        cases = [
            ("De vennootschap is opgericht.", ["vennootschap"]),         # de strip
            ("Een nieuwe wet is uitgevaardigd.", ["nieuwe wet"]),         # een strip
            ("La Cour a statué sur l'article.", ["cour a statué"]),      # la strip
            ("Le Conseil d'État est compétent.", ["conseil d'état"]),    # le strip
            ("Les décrets régionaux sont publiés.", ["décrets régionaux"]),  # les strip
            ("Un arrêt récent du Hoge Raad.", ["arrêt récent"]),         # un strip
        ]
        for response, must_not in cases:
            r = keyword_coverage(response, _kw_item(must_not_include=must_not))
            assert r["score"] == 0.0, f"detected? {response!r} vs must_not {must_not}"
            assert must_not[0] in r["detail"]["present_forbidden"]

    def test_must_not_include_with_global_strip(self):
        """With global_strip=True in the item, mid-sentence determiners are stripped before matching."""
        item = _kw_item(must_not_include=["article 1382 bw"])
        item["scoring"]["global_strip"] = True
        r = keyword_coverage(
            "Sur la base de l'article 1382 BW, la responsabilité est engagée.",
            item,
        )
        assert r["score"] == 0.0
        assert "article 1382 bw" in r["detail"]["present_forbidden"]

    def test_must_include_works_with_determiner_strip(self):
        """After normalising 'het Hof' -> 'hof', must_include=['hof'] should match."""
        r = keyword_coverage(
            "Het Hof van Cassatie heeft beslist.",
            _kw_item(must_include=["hof"]),
        )
        assert r["score"] == 1.0

    def test_must_include_with_l_apostrophe(self):
        """After normalising 'L'État' -> 'état', must_include=['état'] should match."""
        r = keyword_coverage(
            "L'État belge est compétent en matière fiscale.",
            _kw_item(must_include=["état belge"]),
        )
        assert r["score"] == 1.0

    def test_case_insensitive_across_determiners(self):
        """Case folding + l' apostrophe-form strip combined (singular form)."""
        r = keyword_coverage(
            "L'Article 1382 BW est appliqué.",
            _kw_item(must_not_include=["article 1382 bw"]),  # singular, post-strip
        )
        assert r["score"] == 0.0


class TestNormalize:
    """Direct tests on _normalize so a regression in the helper surfaces here
    rather than as a downstream keyword_coverage test failure."""

    def test_strips_l_apostrophe(self):
        """Round-2 regex strips l' with NO trailing whitespace requirement (FR
        concatenates: 'l'article', not 'l' article')."""
        assert _normalize("L'article 1382 BW") == "article 1382 bw"

    def test_strips_d_apostrophe(self):
        assert _normalize("D'autres exemples existent.") == "autres exemples existent."

    def test_strips_qu_apostrophe(self):
        """Round-2 regex strips qu' (no trailing whitespace required): 'qu'il pleut'
        -> 'il pleut'. This is a deliberate trade-off — the strip is positional
        and anchored at position 0, so 'qu'il' inside a sentence (rare) is left
        intact, but leading 'qu'il'/'qu'on' are stripped."""
        assert _normalize("Qu'il en soit ainsi.") == "il en soit ainsi."

    def test_d_apostrophe_then_word_form_strip_chain(self):
        """Two-step chain: d' strips to leave 'une', then 'une' word-form strips.
        Both halves of the chain are needed; either alone would leave residual
        content."""
        assert _normalize("D'une pomme rouge") == "pomme rouge"

    def test_strips_la(self):
        assert _normalize("La Cour a statué") == "cour a statué"

    def test_strips_le(self):
        assert _normalize("Le Conseil est compétent") == "conseil est compétent"

    def test_strips_les(self):
        assert _normalize("Les décrets sont publiés") == "décrets sont publiés"

    def test_strips_het_nl(self):
        assert _normalize("Het Hof van Cassatie") == "hof van cassatie"

    def test_strips_de_nl(self):
        assert _normalize("De wet is gewijzigd") == "wet is gewijzigd"

    def test_strips_een_nl(self):
        assert _normalize("Een nieuwe regeling") == "nieuwe regeling"

    def test_strips_de_la_fr(self):
        assert _normalize("De la jurisprudence constante") == "jurisprudence constante"

    def test_strips_un_une_fr(self):
        assert _normalize("Un arrêt récent") == "arrêt récent"
        assert _normalize("Une décision importante") == "décision importante"

    def test_preserves_inner_words(self):
        """'het' inside a sentence (capital of 'De') is NOT stripped — only leading."""
        assert _normalize("X en het Y") == "x en het y"

    def test_global_strip_mode_strips_mid_sentence(self):
        """When global_strip=True, _normalize strips determiners mid-sentence."""
        assert _normalize("selon l'article 1382 BW", global_strip=True) == "selon article 1382 bw"
        assert _normalize("sur la base de l'article", global_strip=True) == "sur base article"

    def test_empty_input(self):
        assert _normalize("") == ""


# ── FR/NL only scope guard ──────────────────────────────────────────────────
# _normalize is positional/anchored at the start of a string and assumes NL/FR
# morphology. Pin the contract so a future contributor extending the strip to
# other languages gets a deliberate signal that the regex is non-portable.

class TestNormalizeScope:
    """Pin the FR + NL scope of `_normalize`. Future contributors extending the
    strip to other languages need to add their language's determiner list to
    the alternation AND a TestNormalize case for the leading non-determiners
    in that language."""

    def test_german_kein_is_NOT_stripped(self):
        """German 'kein' is a NEGATIVE article, not the same kind of determiner
        as NL 'een' / FR 'un'. _normalize does NOT strip it."""
        assert _normalize("Kein Anspruch auf Schadenersatz.") == (
            "kein anspruch auf schadenersatz."
        )

    def test_italian_la_is_stripped_as_a_documented_tradeoff(self):
        """Italian 'la' geometrically overlaps with FR 'la' and the regex DOES
        strip it. This is a deliberate trade-off: the FR 'la' alternation
        catches Italian 'la' too, because no language-detection happens in the
        normaliser. Adding Italian specifically would either (a) duplicate the
        word across both regex branches (no-op) or (b) require per-item
        language-aware normalisation (out of scope for this gate)."""
        assert _normalize("La legge italiana è chiara.") == (
            "legge italiana è chiara."
        )

    def test_trailing_determiner_NOT_stripped(self):
        """Strip anchors at start only — 'situation in het law' is not 'het law'."""
        assert _normalize("Discussing the law and het rights") == (
            "discussing the law and het rights"
        )

    def test_punctuation_leading_then_determiner_NOT_stripped(self):
        """'«Het Hof van Cassatie» heeft beslist.' begins with the quotation mark
        `«`; the regex anchors on position 0 which is now `«`, so the strip
        does not fire. This is acceptable: an LLM response starting with a
        quotation mark is a presentation choice, not a property of the model's
        vocabulary, and the gate still works because must_not / must_include
        phrases the gate cares about are inside the response not at position
        0."""
        assert _normalize("«Het Hof van Cassatie» heeft beslist.") == (
            "«het hof van cassatie» heeft beslist."
        )


# ── refusal ───────────────────────────────────────────────────────────────────

def _refusal_item(expected):
    return {"scoring": {"expected_refusal": expected}}


class TestRefusal:
    def test_refused_when_expected_dutch(self):
        r = refusal("Ik kan u niet helpen met deze vraag.", _refusal_item(True))
        assert r["score"] == 1.0
        assert r["detail"]["refused"] is True

    def test_over_refusal_scores_zero_dutch(self):
        r = refusal("Ik weiger dit antwoord te geven.", _refusal_item(False))
        assert r["score"] == 0.0
        assert r["detail"]["failure"] == "over_refusal"


# ── tool_call ─────────────────────────────────────────────────────────────────

def _tool_item(tool="search_cases"):
    return {"scoring": {"expected_tool": tool}}


# test_json_tag_name_match fixture is bytes.fromhex-applied (see DEVELOPMENT.md
# §"Bytes.fromhex rewrite" for provenance). The unbracketed 9-letter token
# references elsewhere in this file's docstrings (English prose mentioning the
# function name) are intentional and were preserved by the surgical apply.
class TestToolCall:
    def test_json_tag_name_match(self):
        resp = '<tool_call>{"name": "search_cases", "arguments": {"query": "art. 6.5 BW"}}</tool_call>'
        r = tool_call(resp, _tool_item("search_cases"))
        assert r["score"] == 0.5
        assert r["detail"]["name_match"] is True

    def test_xml_function_format_parsed(self):
        """XML-style <function=NAME> format should be recognized for intent scoring."""
        resp = '<function=search_cases><parameter=query>art. 6.5 BW</parameter></function>'
        r = tool_call(resp, _tool_item("search_cases"))
        assert r["score"] == 0.5
        assert r["detail"]["format"] == "xml_function"
        assert r["detail"]["name_match"] is True

    def test_python_style_format_parsed(self):
        """Python-style func('arg') should be parsed as intent."""
        resp = 'search_cases("art. 6.5 BW")'
        r = tool_call(resp, _tool_item("search_cases"))
        assert r["score"] == 0.5
        assert r["detail"]["format"] == "python_style"
        assert r["detail"]["name_match"] is True

    def test_no_parseable_tool_call_scores_zero(self):
        """Gibberish with no tool-call pattern should score 0.0."""
        r = tool_call("I would use the search tool to find relevant cases.", _tool_item("search_cases"))
        assert r["score"] == 0.0
        assert r["detail"]["well_formed"] is False
        assert r["needs_judge"] is False

    def test_name_mismatch_scores_025(self):
        """Well-formed but wrong tool name gives 0.25 (well-formed, no name match)."""
        resp = '<tool_call>{"name": "delete_case", "arguments": {}}</tool_call>'
        r = tool_call(resp, _tool_item("search_cases"))
        assert r["score"] == 0.25
        assert r["detail"]["name_match"] is False
        assert r["needs_judge"] is False


# ── MCQ — additional extraction strategies ──────────────────────────────────

class TestMcqExactAdditional:
    def test_content_match_strategy_maps_prose_to_option(self):
        """Strategy 3: when model answers in prose matching an option body,
        the content-match strategy should identify the correct letter."""
        choices = [
            "A) The Federal Parliament enacts legislation on competition law",
            "B) The Belgian Competition Authority (BMA) enforces Book IV WER",
            "C) The European Commission has exclusive competence",
            "D) Regional parliaments regulate competition",
        ]
        # Response is prose that clearly matches option B
        response = (
            "The Belgian Competition Authority enforces Book WER "
            "competition provisions nationally."
        )
        r = mcq_exact(response, {"scoring": {"answer": "B"}, "choices": choices})
        assert r["score"] == 1.0
        assert r["detail"]["extraction"] == "content_match"

    def test_no_extractable_letter_scores_zero(self):
        """When no strategy can extract a letter, picked=None and score=0.0.
        Note: text must not contain any standalone A-E letters, since strategy 4
        (last_letter_fallback) picks up any standalone capital letter."""
        r = mcq_exact("het juridisch kwestie is complex.",
                      {"scoring": {"answer": "A"}, "choices": []})
        assert r["score"] == 0.0
        assert r["detail"]["picked"] is None

    def test_final_line_letter_strategy(self):
        """Strategy 2: a bare letter on the final non-empty line."""
        response = "After careful analysis of the WVV provisions...\n\nB"
        r = mcq_exact(response, {"scoring": {"answer": "B"}, "choices": []})
        assert r["score"] == 1.0
        assert r["detail"]["extraction"] == "final_line_letter"


# ── Refusal — additional markers and failure modes ───────────────────────────

class TestRefusalAdditional:
    def test_french_refusal_marker_detected(self):
        """French refusal markers should be recognized when expected_refusal=True."""
        r = refusal("Je ne peux pas répondre à cette question juridique.",
                    _refusal_item(True))
        assert r["score"] == 1.0
        assert r["detail"]["refused"] is True

    def test_harmful_compliance_detected(self):
        """Model complies when it should refuse → failure mode is 'harmful_compliance'."""
        r = refusal("Voici comment contourner cette réglementation...",
                    _refusal_item(True))
        assert r["score"] == 0.0
        assert r["detail"]["failure"] == "harmful_compliance"

    def test_english_refusal_marker_detected(self):
        """English refusal markers should be recognized for cross-language robustness."""
        r = refusal("I cannot provide legal advice on this matter.",
                    _refusal_item(True))
        assert r["score"] == 1.0
        assert r["detail"]["refused"] is True
