# Copyright 2026 Haytam Aroui
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for harness/stats.py.

All functions are pure math with no external deps:
bootstrap_ci, bootstrap_diff_test, parity_ratio, bilingual_accuracy_ratio.
"""
from __future__ import annotations

import pytest
from harness.stats import bootstrap_ci, bootstrap_diff_test, parity_ratio, bilingual_accuracy_ratio


class TestBootstrapCI:
    def test_empty_returns_none_sentinel(self):
        r = bootstrap_ci([])
        assert r == {"n": 0, "mean_pct": None, "ci_low_pct": None, "ci_high_pct": None}

    def test_single_item_all_correct(self):
        r = bootstrap_ci([1.0])
        assert r["n"] == 1
        assert r["mean_pct"] == 100.0


class TestBootstrapDiffTest:
    def test_empty_a_insufficient_data(self):
        r = bootstrap_diff_test([], [1.0, 0.0])
        assert r["verdict"] == "insufficient_data"


class TestParityRatio:
    def test_normal_ratio(self):
        assert parity_ratio(0.8, 1.0) == {"parity_ratio": 0.8}

    def test_bilingual_accuracy_ratio(self):
        assert bilingual_accuracy_ratio(0.8, 1.0, "fr", "nl") == {"parity_ratio": 0.8}
        assert bilingual_accuracy_ratio(0.8, 0.0, "fr", "nl") == {"parity_ratio": None}
