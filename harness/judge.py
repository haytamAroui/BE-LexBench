# Copyright 2026 Haytam Aroui
# SPDX-License-Identifier: GPL-3.0-only
"""
be-lexbench LLM-as-judge.

The judge scores open-ended legal reasoning on a documented, versioned rubric.
Design rules (see docs/methodology.md §5.2):
  - The rubric is explicit and anchored (0-4 with per-level descriptions).
  - The judge runs BLIND: it never learns which model produced the answer.
  - Use an ENSEMBLE of ≥2 judges of different lineage; report agreement.
  - Validate against a human-scored calibration set; report Cohen's / weighted κ.

This module provides the rubric text and a judge runner. The judge itself is just
another ModelClient (models.py), so you can point it at a strong model via the
OpenAI-compatible client. Keep the judge model FIXED across a leaderboard refresh
and record which model + version was the judge.
"""

from __future__ import annotations
import json
import re
import sys
import time
from typing import Optional


# Anchored 0-4 scale reused by most rubrics; rescaled to 0-1 at aggregation.
SCALE_ANCHORS = """Score on a 0-4 scale:
4 = Fully correct. Doctrinally accurate, complete on the required points, correct
    terminology for the applicable legal tradition, no fabricated authorities.
3 = Substantially correct with a minor omission or imprecision that would not
    mislead a competent reader.
2 = Partially correct. Captures some required points but has a material gap, a
    wrong-tradition error, or imprecise terminology.
1 = Mostly incorrect. Major doctrinal error, wrong legal tradition applied, or
    misleading framing, with only incidental correct content.
0 = Incorrect, non-responsive, or contains a fabricated/misattributed authority.
A fabricated or misattributed case/statute citation caps the score at 0
regardless of other quality."""

RUBRICS = {
    # ── Track 2: Belgian Civil Law ──────────────────────────────────────
    "be-civil-law-v1": (
        "You are grading an answer about BELGIAN CIVIL LAW. "
        "As of 1 January 2025, extra-contractual liability is governed by "
        "BOOK 6 of the Civil Code (Wet 7 februari 2024). The THREE elements "
        "are: fout/faute (objective 'normally prudent person' standard, "
        "Art. 6.5), schade/dommage (actual, certain, personal damage), and "
        "causaal verband/lien causal (conditio sine qua non with correction "
        "for concurrent causes). "
        "KEY REFORM CHECKS: (1) the quasi-immunity of auxiliaries is "
        "ABOLISHED — citing it as still valid caps at 1; (2) concurrence of "
        "contractual and extra-contractual liability is now ALLOWED; "
        "(3) citing old arts. 1382–1386 as current law without acknowledging "
        "the Book 6 reform caps at 2. "
        "Reward correct Code article references (art. 6.5 BW, not '1382 BW').\n"
        + SCALE_ANCHORS),

    # ── Track 3: Corporate Law WVV/CSA ──────────────────────────────────
    "be-corporate-wvv-v1": (
        "You are grading an answer about BELGIAN CORPORATE LAW under the "
        "Code of Companies and Associations (WVV/CSA, Law of 23 March 2019, "
        "fully applicable since 1 January 2024 for all existing companies). "
        "KEY POINTS: (1) the BV/SRL has NO minimum capital — replaced by "
        "'adequate initial assets' + a mandatory financial plan; "
        "(2) distributions require a DOUBLE TEST: net asset test (solvency) "
        "AND liquidity test (ability to pay debts for 12 months); "
        "(3) directors' liability is capped at statutory thresholds (art. 2:57 WVV) "
        "except for gross negligence, fraud, or unpaid social contributions; "
        "(4) the NV/SA now allows a sole director; "
        "(5) the statutory seat theory governs applicable law. "
        "Citing the old Wetboek van Vennootschappen (W.Venn.) provisions as "
        "current law is a wrong-law error (cap at 2).\n" + SCALE_ANCHORS),

    # ── Track 4: Market Practices WER/CDE ───────────────────────────────
    "be-market-practices-v1": (
        "You are grading an answer about BELGIAN MARKET PRACTICES AND "
        "CONSUMER PROTECTION under the Code of Economic Law (WER/CDE). "
        "Book VI covers unfair commercial practices (misleading/aggressive), "
        "pre-contractual information duties, consumer contract rules, "
        "price indication, and sales promotions. Book XII covers electronic "
        "commerce. Book XVI covers ADR for consumer disputes. "
        "Reward correct Book/Article references. Confusing Belgian WER/CDE "
        "provisions with French Code de la consommation or generic 'EU "
        "consumer law' without citing the Belgian transposition is imprecise "
        "(cap at 3).\n" + SCALE_ANCHORS),

    # ── Track 5: Competition Law ────────────────────────────────────────
    "be-competition-v1": (
        "You are grading an answer about BELGIAN COMPETITION LAW. "
        "Book IV WER/CDE prohibits cartels (Art. IV.1, mirroring EU Art. 101 "
        "TFEU) and abuse of dominant position (Art. IV.2, mirroring Art. 102 "
        "TFEU). The Belgian Competition Authority (BMA/ABC) enforces these. "
        "Merger control thresholds are Belgian-specific. "
        "The 'effect on Belgian market' nexus is key for purely national "
        "cases. Reward awareness of parallel EU/national enforcement.\n"
        + SCALE_ANCHORS),

    # ── Track 6: Financial Compliance ───────────────────────────────────
    "be-financial-compliance-v1": (
        "You are grading an answer about BELGIAN FINANCIAL REGULATION. "
        "Belgium uses a TWIN PEAKS model: NBB (prudential supervision of "
        "banks, insurers, payment institutions) and FSMA (conduct-of-business, "
        "market supervision, consumer protection). "
        "AML/CFT: Law of 18 September 2017 (KYC, risk-based approach, "
        "suspicious transaction reporting to CTIF-CFI). "
        "Whistleblower: Act of 28 November 2022 (private sector, ≥50 "
        "employees must have internal channels; effective 15 February 2023). "
        "ESG/CSRD: Transposed by Act of 2 December 2024; 'Stop-the-Clock' "
        "delayed waves 2-3 by two years (large companies FY2027, listed SMEs "
        "FY2028). "
        "Pillar Two: Law of 19 December 2023, QDMTT/IIR returns due "
        "30 September 2026. "
        "Confusing NBB and FSMA roles is a factual error (cap at 2).\n"
        + SCALE_ANCHORS),

    # ── Track 7: GDPR & Digital Compliance ──────────────────────────────
    "be-gdpr-digital-v1": (
        "You are grading an answer about BELGIAN PRIVACY AND DIGITAL "
        "COMPLIANCE. GDPR (Regulation EU 2016/679) applies directly. "
        "National implementation: Privacy Act of 30 July 2018. "
        "Data Protection Authority: APD/GBA (established by Act of "
        "3 December 2017, amended 2023). "
        "AI ACT: Regulation EU 2024/1689, directly applicable; BIPT/IBPT "
        "designated as Market Surveillance Authority; high-risk AI system "
        "obligations apply from 2 August 2026; 21 supervisory bodies for "
        "fundamental rights. SmartAI.Nation is the federal policy roadmap "
        "(not a law). "
        "NIS2: Law of 26 April 2024, effective 18 October 2024; CCB is the "
        "national authority; CyberFundamentals (CyFun) is the compliance "
        "framework; incident reporting: 24h warning / 72h follow-up / "
        "30-day final report. "
        "ePrivacy/Cookies: Law of 13 June 2005. "
        "Reward distinguishing direct EU regulation from national "
        "implementation gaps (e.g. Art. 23 GDPR derogations).\n"
        + SCALE_ANCHORS),

    # ── Track 8: Employment / Social Law ────────────────────────────────
    # NOTE on the 2026 reforms: the substantive reform package (52-week notice
    # cap for new contracts, abolition of the night-work prohibition, reduction
    # of the part-time minimum to 1/10 of full-time) was enacted in spring 2026
    # and took effect on 1 June 2026. The exact statute number and Moniteur
    # Belge publication date were NOT independently verified for this rubric;
    # the rubric uses neutral descriptors so it does not bake in a specific
    # act identifier. Authors of items for this track should:
    #   (i)  confirm the act number against Moniteur Belge before publishing, and
    #   (ii) surface it in `scoring.valid_citations` so the citation_validity
    #        scorer can verify it authoritatively rather than relying on the judge.
    "be-employment-v1": (
        "You are grading an answer about BELGIAN EMPLOYMENT LAW. "
        "JUNE 2026 REFORMS (reform package effective 1 June 2026; treat act "
        "number as item-specific — verify against the item's reference): "
        "(1) notice period capped at 52 WEEKS for contracts "
        "starting on or after 1 June 2026 (NOT retroactive); (2) night work "
        "prohibition ABOLISHED for all industries; (3) part-time minimum reduced "
        "from 1/3 to 1/10 of full-time; (4) flexible working-time frameworks "
        "replace fixed schedules in work regulations. "
        "ONGOING RULES: (1) serious cause dismissal requires action within "
        "3 WORKING DAYS of knowledge; (2) protected employees (works council, "
        "CPPT, pregnant, parental leave) cannot be dismissed for "
        "status-related reasons; (3) blue/white collar notice periods "
        "harmonised since 2014 but legacy transitional rules apply to "
        "pre-2014 contracts. "
        "SCORING TIERS: (a) Citing pre-June 2026 rules (e.g. no cap on "
        "notice, night work banned) as current law for new contracts is a "
        "reform-awareness failure (cap at 2). (b) Answer is doctrinally "
        "correct on statutory rules but omits the CAO/CCT (collective "
        "bargaining agreement) layer that modifies rules in specific joint "
        "committees (Comités paritaires / Paritaire comités) → cap at 3. "
        "(c) Act-number precision is the item author's responsibility: the "
        "judge scores substance and reform-awareness, not act-number lookup.\n"
        + SCALE_ANCHORS),

    # ── Track 9: Insolvency / Restructuring ─────────────────────────────
    "be-insolvency-v1": (
        "You are grading an answer about BELGIAN INSOLVENCY AND "
        "RESTRUCTURING LAW (Book XX WER/CDE). "
        "CURRENT LAW: Book XX as amended 1 September 2023 (transposition of "
        "EU Restructuring Directive 2019/1023). Key tools: judicial "
        "reorganisation (amicable settlement, collective agreement, transfer "
        "under judicial authority), confidential procedures, and pre-pack "
        "(closed preparation for bankruptcy). "
        "Directors' filing duty under CURRENT Book XX WER/CDE: a director "
        "must file for bankruptcy within a short, statutory deadline after "
        "cessation of payments (the precise window is item-specific — see "
        "the item's `reference` for the applicable article); failure exposes "
        "the director to personal liability for company debts. Do NOT "
        "conflate the current Book XX deadline with the longer window the "
        "Insolvency III Directive (EU 2026/799) proposes — that is "
        "forward-looking, not currently in force. "
        "UPCOMING: Insolvency III Directive (2026/799, adopted 1 April 2026) "
        "must be transposed by 22 January 2029 — harmonises avoidance "
        "actions, asset tracing, pre-packs, and directors' filing duty. "
        "Reward awareness that Insolvency III is adopted but NOT YET "
        "transposed into Belgian law.\n" + SCALE_ANCHORS),

    # ── Track 10: Administrative Law ────────────────────────────────────
    "be-administrative-v1": (
        "You are grading an answer about BELGIAN ADMINISTRATIVE LAW. "
        "The Raad van State / Conseil d'État is the HIGHEST ADMINISTRATIVE "
        "COURT, operating OUTSIDE the ordinary judiciary (Constitution "
        "Art. 160). It has two sections: "
        "(1) Administrative Litigation Section: annuls/suspends illegal "
        "administrative acts and regulations; acts as cassation court over "
        "specialised administrative tribunals (e.g. Council for Alien Law "
        "Litigation); (2) Legislation Section: gives mandatory advisory "
        "opinions on bills and decrees. "
        "IMPORTANT: The Raad van State is NOT part of the Court of Cassation "
        "hierarchy. Conflating the two is a structural error (cap at 1). "
        "GwH ruling nr. 22/2025 (13 February 2025) reaffirmed the Council "
        "of State's exclusive competence over urban planning appeals.\n"
        + SCALE_ANCHORS),

    # ── Track 11: Constitutional / Federalism ───────────────────────────
    "be-constitutional-v1": (
        "You are grading a BELGIAN CONSTITUTIONAL LAW answer. "
        "EQUALITY: Articles 10 and 11 of the Constitution. The "
        "Grondwettelijk Hof / Cour constitutionnelle applies a "
        "VARIABLE-INTENSITY proportionality test: deferential 'manifestly "
        "unreasonable' scrutiny for socioeconomic measures; strict scrutiny "
        "for fundamental rights. Do NOT expect rigid four-prong proportionality "
        "analysis here. "
        "FEDERALISM: Belgium uses EXCLUSIVE competence allocation across "
        "Federal / Regions (Flanders, Wallonia, Brussels-Capital) / "
        "Communities (Flemish, French, German-speaking). Conflict resolution "
        "uses 'true character' (werkelijke aard) test + duty of loyal "
        "cooperation (loyauté fédérale / federale loyauteit). "
        "Reward correct identification of which level of government has "
        "competence for the subject matter.\n" + SCALE_ANCHORS),

    # ── Track 14: Grounded RAG ──────────────────────────────────────────
    "be-rag-faithfulness-v1": (
        "You are grading FAITHFULNESS to a supplied context. The answer must "
        "be grounded ONLY in the provided context. If the context does not "
        "contain the answer, the correct response says so. Inventing facts "
        "not in the context is an unfaithfulness failure (cap at 1).\n"
        + SCALE_ANCHORS),

    # ── Track 14 alt: Instruction Following ─────────────────────────────
    "be-instruction-following-v1": (
        "You are grading FORMAT COMPLIANCE with the instruction. Check that "
        "every explicit constraint (count, list style, 'no other text', "
        "language — NL or FR per item) is satisfied exactly.\n"
        + SCALE_ANCHORS),
}

JUDGE_TEMPLATE = """You are a careful, impartial grader of answers to Belgian legal questions.
You are grading BLIND — you do not know which system produced the answer, and the
identity is irrelevant. Grade only against the rubric and the reference.
Belgium has three official languages (Dutch, French, German) and a complex federal
structure (Federal State, Regions, Communities). Apply Belgian legal doctrine only;
do not import foreign legal frameworks unless the question
explicitly asks for comparative analysis.

RUBRIC:
{rubric}

QUESTION (asked in language='{language}', jurisdiction='{jurisdiction}'):
{prompt}

REFERENCE / KEY POINTS (authoritative; the answer need not match wording, but must
be consistent with this):
{reference}

ANSWER TO GRADE:
\"\"\"
{answer}
\"\"\"
Return ONLY a JSON object, no other text:
{{"score": <integer 0-4>, "rationale": "<one or two sentences>", "fabricated_citation": <true|false>}}"""


def build_judge_prompt(item: dict, answer: str) -> str:
    rubric_id = item["scoring"].get("rubric_id")
    rubric = RUBRICS.get(rubric_id, SCALE_ANCHORS)
    return JUDGE_TEMPLATE.format(
        rubric=rubric,
        language=item.get("language", "en"),
        jurisdiction=item.get("jurisdiction", ""),
        prompt=item["prompt"],
        reference=item["scoring"].get("reference", "(no reference provided)"),
        answer=answer,
    )


def _parse_judge_json(text: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        o = json.loads(m.group(0))
        score = int(o.get("score"))
        if 0 <= score <= 4:
            return {"score": score,
                    "rationale": o.get("rationale", ""),
                    "fabricated_citation": bool(o.get("fabricated_citation", False))}
    except Exception:
        return None
    return None


def judge_item(item: dict, answer: str, judge_clients: list) -> dict:
    """
    Run an ensemble of judge clients (models.ModelClient) over one answer.
    Returns {"score01": float, "votes": [...], "agreement": "..."}.
    Score is the mean of judge scores, rescaled 0-4 -> 0-1. A fabricated-citation
    flag from any judge caps the item at 0 (matches the rubric anchor).
    """
    prompt = build_judge_prompt(item, answer)
    votes = []
    for jc in judge_clients:
        # Retry judge calls with backoff — judge failures on transient errors
        # should not crash the run or silently produce no_valid_votes.
        out = None
        for attempt in range(1, 4):
            try:
                out = jc.generate(prompt, max_tokens=300, temperature=0.0)
                break
            except Exception as e:
                if attempt == 3:
                    print(
                        f"[judge] WARNING: judge {getattr(jc, 'model_id', '?')} "
                        f"failed after 3 attempts: {e}", file=sys.stderr,
                    )
                    break
                wait = 2.0 ** (attempt - 1)
                print(
                    f"[judge-retry] attempt {attempt}/3 for "
                    f"{getattr(jc, 'model_id', '?')} failed: {e}. "
                    f"Retrying in {wait:.0f}s...", file=sys.stderr,
                )
                time.sleep(wait)
        if out is None:
            continue
        parsed = _parse_judge_json(out.text)
        if parsed:
            # Record the judge identity per vote — prefer the model ID the API
            # resolved and returned over the requested one, so results pin the
            # exact judge version (methodology §5.2, fixed-judge-version rule).
            parsed["judge_model"] = out.raw.get("model") or out.model_id
            votes.append(parsed)
    if not votes:
        return {"score01": None, "votes": [], "agreement": "no_valid_votes"}
    if any(v["fabricated_citation"] for v in votes):
        return {"score01": 0.0, "votes": votes, "agreement": "fabrication_cap"}
    scores = [v["score"] for v in votes]
    mean = sum(scores) / len(scores)
    spread = max(scores) - min(scores)
    return {"score01": mean / 4.0, "votes": votes,
            "agreement": "tight" if spread <= 1 else "divergent_flag_for_human"}
