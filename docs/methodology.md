# be-lexbench Scoring Methodology

> **Scoring protocol status: stable.** The harness-level scoring rules described here — scorers, rubrics, aggregation, and judge protocol — are fixed and will not change without a versioned update. 

---

## §0. Pre-publication gate

The current validation set is undergoing expert review. Runs against the private item bank produce a `summary.json` that carries the following note until SME validation is complete:

```
"note": "Seed run. Items require SME validation before these numbers are publishable (see docs/methodology.md §0)."
```

Do not publish or cite numbers from seed runs as finalized benchmark results.

---

## §1. Per-track scoring overview

| Track | Primary scorer | Judge required? |
|---|---|---|
| `bilingual_parity` | `language_adherence` + track-specific scorer | No |
| `belgian_civil_law` | `rubric` (`be-civil-law-v1`) | Yes |
| `corporate_law_wvv` | `rubric` (`be-corporate-wvv-v1`) or `mcq_exact` | Yes (for open) / No (for MCQ) |
| `market_practices_wer` | `rubric` (`be-market-practices-v1`) | Yes |
| `competition_law_bma` | `rubric` (`be-competition-v1`) | Yes |
| `financial_compliance` | `rubric` (`be-financial-compliance-v1`) | Yes |
| `gdpr_digital_compliance` | `rubric` (`be-gdpr-digital-v1`) | Yes |
| `employment_social_law` | `rubric` (`be-employment-v1`) | Yes |
| `insolvency_restructuring` | `rubric` (`be-insolvency-v1`) | Yes |
| `administrative_law` | `rubric` (`be-administrative-v1`) | Yes |
| `constitutional_federalism` | `rubric` (`be-constitutional-v1`) | Yes |
| `citation_integrity` | `citation_validity` | Optional (Juportal verifier) |
| `safety_calibration` | `refusal` | Optional (quality annotation only) |
| `grounded_rag` | `rubric` (`be-rag-faithfulness-v1`) | Yes |

All scoring code is in `harness/scorers.py` (programmatic) and `harness/judge.py` (LLM judge). No gold answers are embedded in these files.

---

## §2. Final-committed-answer extraction (MCQ)

Reasoning models frequently produce long chain-of-thought before committing to a final answer, then continue with caveats or restatements. Taking the first letter-match would mis-score many correct responses.

`scorers.mcq_exact` applies a four-stage cascade, taking the LAST commitment found:

1. **Bare response** — the entire response is a single letter, optionally wrapped in parens/period
2. **Last explicit commitment** — scan the full response for patterns like `"The answer is B"`, `"**C**"`, `"So, D"`, `"Choose E"`. The LAST match position wins.
3. **Final-line letter** — the last non-empty line of the response contains only a letter
4. **Content match** — match response text against option bodies; requires ≥3 content-word hits and a 2-word margin over the runner-up to avoid degenerate matches on short options
5. **Last letter fallback** — the last standalone A–E anywhere in the response

---

## §3. Citation validity

`scorers.citation_validity` detects hallucinated Belgian legal citations using several patterns:

- **ECLI**: standard European Case Law Identifier format for Belgium (e.g. `ECLI:BE:CASS:2020:ARR.20201030.1N.4`)
- **Grondwettelijk Hof (GwH)**: e.g. `GwH nr. 149/2025`
- **Court of Cassation**: e.g. `Cass., 15 september 2023, C.22.0123.N`
- **Moniteur Belge / Belgisch Staatsblad**: e.g. `B.S. 01.06.2026`
- **Code articles**: e.g. `art. 6.5 BW`, `art. IV.1 WER`, `art. 2:57 WVV`
- **Justel dossier number**: e.g. `2024-04-26/07`

Known-good citations from `item.scoring.valid_citations` are matched punctuation-insensitively (alphanumeric collapse). An optional `verifier` callable can check real existence via Juportal or Justel. Without a verifier, citation-shaped strings that do not match gold are flagged as `unverified_format_ok` and escalated to the judge.

---

## §4. Bilingual parity

The Track 1 headline metric is the **parity ratio**: FR accuracy ÷ NL accuracy. A ratio of 1.0 indicates no accuracy drop between languages. Ratios below ~0.90 indicate material bilingual performance degradation.

---

## §5. LLM judge

Open-ended legal reasoning items (method `rubric`) and some programmatic tracks with quality escalation (tool-call argument quality, citation ambiguity) require an LLM judge.

### §5.1 Available rubrics

| Rubric ID | Used for |
|---|---|
| `be-civil-law-v1` | Belgian Civil Law reasoning |
| `be-corporate-wvv-v1` | Belgian Corporate Law (WVV/CSA) |
| `be-market-practices-v1` | Belgian Market Practices (WER/CDE) |
| `be-competition-v1` | Belgian Competition Law (BMA) |
| `be-financial-compliance-v1` | Belgian Financial Regulation / Twin Peaks |
| `be-gdpr-digital-v1` | GDPR & Digital Compliance (AI Act / NIS2) |
| `be-employment-v1` | Belgian Employment Law / June 2026 labor reforms |
| `be-insolvency-v1` | Belgian Insolvency / Book XX WER/CDE |
| `be-administrative-v1` | Belgian Administrative Law / Council of State |
| `be-constitutional-v1` | Belgian Constitutional Law / Federalism |
| `be-rag-faithfulness-v1` | Grounded RAG faithfulness |
| `be-instruction-following-v1` | Format compliance / instruction following |

### §5.2 Judge design rules

- **Canonical judge**: the official primary judge is **Claude Sonnet 4.6** (`claude-sonnet-4-6`), accessed through the native Anthropic API (client kind `anthropic`) or equivalently through Google Vertex AI (client kind `vertex_anthropic`) — the model is identical on both paths, so scores are comparable regardless of access route.
- **Blind grading**: the judge prompt never identifies which model produced the answer
- **Ensemble**: ≥2 judge clients of different lineage, anchored on the canonical judge
- **Fabrication cap**: a fabricated or misattributed citation flagged by any judge caps the item at 0 regardless of other quality
- **Fixed judge version**: the judge model + version must be recorded and held constant across a leaderboard refresh; changing the judge invalidates comparisons

---

## §6. Scoring combination rules

| Method | Programmatic score | Judge role | Final score |
|---|---|---|---|
| `mcq_exact` | Exact match → 0 or 1 | Not used | Programmatic |
| `language_adherence` | Heuristic match → 0 or 1 | Not used | Programmatic |
| `citation_validity` | Gold match / hallucination | Escalated if ambiguous | Judge (if escalated) |
| `keyword_coverage` | Gate pass/fail | Sets quality score for open items | 0 if gate fails; otherwise judge |
| `rubric` | Not scored | Sets full score on 0–4 scale | Judge / 4 |
| `refusal` | Binary correct/incorrect | Quality annotation only | Programmatic |
| `tool_call` | 0.5 if correct tool name | Scores argument quality (other 0.5) | prog + 0.5 × judge |

---

## §7. Statistics

All reported numbers include:
- Item count (n) per track
- Mean accuracy (%)
- 95% bootstrap CI (10,000 resamples, percentile method, seed=0)
- Difficulty breakdown: `core` / `applied` / `expert`
