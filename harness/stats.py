# Copyright 2026 Haytam Aroui
# SPDX-License-Identifier: GPL-3.0-only
"""
be-lexbench statistics.

Every reported number gets an n and a 95% bootstrap CI. Every "A beats B"
claim gets a significance test. Differences inside overlapping CIs are reported
as "not distinguishable", never as a ranking.
"""

from __future__ import annotations
import random
from statistics import mean


def bootstrap_ci(scores: list[float], n_boot: int = 10000,
                 alpha: float = 0.05, seed: int = 0) -> dict:
    """95% bootstrap CI (percentile method) over a list of per-item scores in
    [0,1]. Returns mean and CI in percent."""
    if not scores:
        return {"n": 0, "mean_pct": None, "ci_low_pct": None, "ci_high_pct": None}
    rng = random.Random(seed)
    n = len(scores)
    boots = []
    for _ in range(n_boot):
        sample = [scores[rng.randrange(n)] for _ in range(n)]
        boots.append(mean(sample))
    boots.sort()
    lo = boots[int((alpha / 2) * n_boot)]
    hi = boots[int((1 - alpha / 2) * n_boot)]
    return {"n": n,
            "mean_pct": round(100 * mean(scores), 2),
            "ci_low_pct": round(100 * lo, 2),
            "ci_high_pct": round(100 * hi, 2)}


def bootstrap_diff_test(scores_a: list[float], scores_b: list[float],
                        n_boot: int = 10000, seed: int = 0) -> dict:
    """
    Two-sample bootstrap test of mean(A) - mean(B). Returns the observed
    difference (percentage points) and a two-sided p-value for H0: diff = 0.
    Use for any leaderboard claim that one model beats another on a track.
    """
    if not scores_a or not scores_b:
        return {"diff_pct": None, "p_value": None, "verdict": "insufficient_data"}
    rng = random.Random(seed)
    obs = mean(scores_a) - mean(scores_b)
    na, nb = len(scores_a), len(scores_b)
    # Center both samples on the pooled mean to simulate H0, then resample.
    pooled = mean(scores_a + scores_b)
    a_c = [x - mean(scores_a) + pooled for x in scores_a]
    b_c = [x - mean(scores_b) + pooled for x in scores_b]
    count_extreme = 0
    for _ in range(n_boot):
        da = mean([a_c[rng.randrange(na)] for _ in range(na)])
        db = mean([b_c[rng.randrange(nb)] for _ in range(nb)])
        if abs(da - db) >= abs(obs):
            count_extreme += 1
    p = count_extreme / n_boot
    verdict = ("A_better" if obs > 0 else "B_better") if p < 0.05 else "not_distinguishable"
    return {"diff_pct": round(100 * obs, 2), "p_value": round(p, 4), "verdict": verdict}


def bilingual_accuracy_ratio(acc_a: float, acc_b: float, lang_a: str = "fr", lang_b: str = "nl") -> dict:
    """Bilingual accuracy ratio (e.g. FR / NL)."""
    if not acc_b:
        return {"parity_ratio": None}
    return {"parity_ratio": round(acc_a / acc_b, 3)}


def parity_ratio(acc_fr: float, acc_en: float) -> dict:
    """Track-1 headline metric. Ratio of FR accuracy to EN accuracy (retained for backward compatibility)."""
    return bilingual_accuracy_ratio(acc_fr, acc_en, "fr", "en")
