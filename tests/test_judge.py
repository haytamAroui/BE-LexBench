# Copyright 2026 Haytam Aroui
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for harness/judge.py.

build_judge_prompt and _parse_judge_json are pure functions.
judge_item is tested with a minimal mock ModelClient — no network calls.
"""
from __future__ import annotations

import json
import pytest
from harness.judge import (
    build_judge_prompt, _parse_judge_json, judge_item,
    RUBRICS,
)
from harness.models import GenResult, ModelClient


# ── Mock ─────────────────────────────────────────────────────────────────────

class _MockJudgeClient(ModelClient):
    def __init__(self, response_text: str, model_id: str = "mock-judge"):
        self.model_id = model_id
        self._response = response_text

    def generate(self, prompt, **kwargs) -> GenResult:
        return GenResult(
            text=self._response,
            raw={"model": self.model_id},
            model_id=self.model_id,
        )


def _item(rubric_id=None, language="nl", prompt="Leg uit wat de fout is in Book 6.",
          reference="Fout vereist schending specifieke norm of algemene zorgvuldigheidsnorm (art. 6.5 BW)."):
    return {
        "prompt": prompt,
        "language": language,
        "scoring": {"rubric_id": rubric_id, "reference": reference},
    }


def _valid_json(score=3, rationale="ok.", fabricated=False) -> str:
    return json.dumps({"score": score, "rationale": rationale,
                       "fabricated_citation": fabricated})


# ── build_judge_prompt ────────────────────────────────────────────────────────

class TestBuildJudgePrompt:
    def test_all_rubric_ids_produce_prompt(self):
        assert len(RUBRICS) == 12
        for rid in RUBRICS:
            p = build_judge_prompt(_item(rubric_id=rid), "Answer.")
            assert "RUBRIC:" in p
            assert "ANSWER TO GRADE:" in p

    def test_known_rubric_text_appears_in_prompt(self):
        for rid, rubric_text in RUBRICS.items():
            p = build_judge_prompt(_item(rubric_id=rid), "Answer.")
            assert rubric_text[:40] in p

    def test_unknown_rubric_id_falls_back_to_scale_anchors(self):
        p = build_judge_prompt(_item(rubric_id="no-such-rubric-v99"), "Answer.")
        assert "0-4" in p  # SCALE_ANCHORS always contains "0-4 scale"

    def test_no_rubric_id_uses_scale_anchors(self):
        p = build_judge_prompt(_item(rubric_id=None), "Answer.")
        assert "0-4" in p

    def test_answer_embedded(self):
        p = build_judge_prompt(_item(), "This is the answer to evaluate.")
        assert "This is the answer to evaluate." in p

    def test_question_embedded(self):
        item = _item(prompt="Wat is de verjaringstermijn?")
        p = build_judge_prompt(item, "Answer.")
        assert "Wat is de verjaringstermijn?" in p

    def test_language_embedded(self):
        p = build_judge_prompt(_item(language="fr"), "Réponse.")
        assert "fr" in p

    def test_reference_embedded(self):
        item = _item(reference="Must cite art. 6.5 BW.")
        p = build_judge_prompt(item, "Answer.")
        assert "Must cite art. 6.5 BW." in p


# ── _parse_judge_json ─────────────────────────────────────────────────────────

class TestParseJudgeJson:
    def test_score_zero_valid(self):
        r = _parse_judge_json(_valid_json(score=0))
        assert r is not None
        assert r["score"] == 0

    def test_score_four_valid(self):
        r = _parse_judge_json(_valid_json(score=4))
        assert r["score"] == 4

    def test_all_valid_scores(self):
        for s in range(5):
            r = _parse_judge_json(_valid_json(score=s))
            assert r is not None
            assert r["score"] == s

    def test_score_minus_one_returns_none(self):
        assert _parse_judge_json(_valid_json(score=-1)) is None

    def test_score_five_returns_none(self):
        assert _parse_judge_json(_valid_json(score=5)) is None


# ── judge_item ────────────────────────────────────────────────────────────────

class TestJudgeItem:
    def _legal_item(self):
        return {
            "prompt": "Leg uit wat de fout is in Book 6.",
            "language": "nl",
            "scoring": {
                "rubric_id": "be-civil-law-v1",
                "reference": "Art. 6.5 BW: fout.",
            },
        }

    def test_single_judge_score_rescaled_from_4(self):
        client = _MockJudgeClient(_valid_json(score=4))
        r = judge_item(self._legal_item(), "Excellent.", [client])
        assert r["score01"] == pytest.approx(1.0)
        assert r["agreement"] == "tight"

    def test_fabrication_caps_score_at_zero(self):
        client = _MockJudgeClient(_valid_json(score=3, fabricated=True))
        r = judge_item(self._legal_item(), "Answer.", [client])
        assert r["score01"] == 0.0
        assert r["agreement"] == "fabrication_cap"
