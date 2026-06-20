# be-lexbench — Belgian Legal Evaluation Suite

[![License](https://img.shields.io/badge/License-GPL_v3-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

**Not BIG-Bench. A jurisdiction-scoped benchmark on 14 Belgian legal tracks.**

**Status: In active development.** The scoring harness and item schema are published here.

`be-lexbench` is a benchmark for evaluating large language models on Belgian legal and regulatory tasks, in both official languages (Dutch and French).

---

## Why public harness, gated items?

The item bank, gold answers, and held-out scoring split are not published here. Evaluators can inspect the full scoring logic, run the harness against their own items, and understand the methodology — while the private split prevents models from being trained on test content before evaluation. This is the standard contamination-resistance design used by credible benchmarks.

---

## How It Works: The Scoring & Gating Pipeline

The `be-lexbench` evaluation runner processes items through a multi-stage execution pipeline designed to guarantee high-performance, cost efficiency, and evaluation integrity:

```
[Load JSONL Items] ➔ [Async Concurrency / Rate Limiter] ➔ [Model Inference]
                                                                  │
┌───────────────────────── [Score Routing Engine] ────────────────┘
│
├─► Rubric Path ➔ [Keyword Gate] ➔ [Language Gate] ➔ [LLM Judge Ensemble]
│
└─► Programmatic Path ➔ [Scorer Cascade (MCQ, Refusal, Tool, Citations)]
                                                                  │
                                                                  ▼
                                                   [Bootstrap CIs & Parity Ratios]
```

### 1. Execution Orchestration (Async & Rate-Limited)
To evaluate large benchmarks quickly without overwhelming target APIs, the harness runs an asynchronous orchestration loop.
*   **Concurrency Limiting**: Uses `asyncio.Semaphore` (via `--concurrency N`) to run multiple target model calls and judges concurrently.
*   **Request Throttling**: Uses a token-bucket rate limiter (via `--rpm N`) to regulate API request frequency, preventing rate limit errors on hosted providers (OpenAI, Anthropic, Together).

### 2. Guarded Evaluation Flow (Gates & Judges)
For open-ended legal reasoning tasks (`method: rubric`), the harness routes answers through successive verification gates before querying an LLM Judge:
1.  **Keyword Gate**: Programmatically checks for forbidden terms (e.g., cross-track contamination such as citing a civil law article in a corporate tax task). If any forbidden term is present or required terms are missing, the score is capped at `0.0` immediately.
2.  **Language Gate**: Leverages `langdetect` with a fallback heuristic to verify response language. Mismatched languages are zeroed out automatically.
3.  **LLM Judge Ensemble**: Only if both gates pass, the response is sent to an ensemble of judges. The judges grade the response based on detailed, jurisdiction-specific rubrics.
4.  **Fabrication Cap**: If the judge identifies a fabricated citation/authority, the score is clamped to `0.0` regardless of prose quality.

### 3. Programmatic Scorer Cascades
For structured tasks, specific scorers evaluate output correctness:
*   **MCQ Answer Extraction**: Uses a 5-stage cascade (exact match ➔ last commitment ➔ final-line letter ➔ content word matching ➔ fallback) to accurately locate the final committed answer in reasoning/CoT models.
*   **Citation Integrity**: Extracts and validates Belgian citations (ECLI, Code articles, Moniteur Belge) using a punctuation-insensitive normalizer.
*   **Safety Calibration**: Uses language-specific markers to verify if the model correctly refuses harmful prompts (e.g., requests to draft fake deeds).

### 4. Aggregation and Bootstrap Statistics
After processing all items, the harness aggregates scores per track:
*   **95% Bootstrap CIs**: Computes percentile-based bootstrap confidence intervals to check if differences between models are statistically significant. Warns if the sample size is too small (`n < 20`) for meaningful intervals.
*   **Bilingual Parity**: Compares performance parity ratios between NL and FR tracks to evaluate bilingual equity.

---

## Tracks

| # | Track | What it measures |
|---|---|---|
| 1 | `bilingual_parity` | Accuracy drop between matched NL and FR items |
| 2 | `belgian_civil_law` | Book 6 extra-contractual liability (Art. 6.5), contract law (Book 5), property law |
| 3 | `corporate_law_wvv` | WVV/CSA BV capital-free structure, double distribution test, directors' liability |
| 4 | `market_practices_wer` | Book VI economic law (unfair practices, consumer contract rules), e-commerce |
| 5 | `competition_law_bma` | Book IV economic law (cartels, abuse of dominance, merger control/BMA) |
| 6 | `financial_compliance` | Twin Peaks model (NBB/FSMA), AML Act, whistleblower protection, ESG/CSRD, Pillar Two tax |
| 7 | `gdpr_digital_compliance` | GDPR national transposition, AI Act (BIPT/IBPT), NIS2 Law (CCB/CyFun framework) |
| 8 | `employment_social_law` | June 2026 labor reforms (notice cap, night work), dismissal protection, CAO/CCT layer |
| 9 | `insolvency_restructuring` | Book XX Economic Law (judicial reorganisation, pre-pack), bankruptcy filing deadlines |
| 10 | `administrative_law` | Raad van State / Conseil d'État jurisdiction, public procurement, urban planning |
| 11 | `constitutional_federalism` | Equality (Grondwettelijk Hof variable-intensity), division of competences |
| 12 | `citation_integrity` | Legal citation validation (ECLI, Moniteur Belge, BW/WVV articles, Justel dossier IDs) |
| 13 | `safety_calibration` | Appropriate refusal vs. compliance (with NL and FR markers) |
| 14 | `grounded_rag` | Answer faithfulness to supplied Belgian legal context |

---

## Running the harness on your own items

You supply a JSONL file where each line is an item conforming to [`schema/eval_item.schema.json`](schema/eval_item.schema.json). The harness calls your model, scores each item, and writes a per-item JSONL and a `summary.json`.

**Install:**

```bash
# Local development checkout:
git clone https://github.com/BE-LexBench/be-lexbench.git && cd be-lexbench
pip install -e .
```

If you are using the **Vertex AI judge path** (GCP ADC auth), add the `vertex` extra:
```bash
pip install -e ".[vertex]"
```

If you are using a **local HuggingFace checkpoint** as the model (`kind: hf_local`), add the `local` extra:
```bash
pip install -e ".[local]"
```

**Programmatic tracks only (no judge required):**

```bash
be-lexbench \
  --items your_items.jsonl \
  --model '{"kind":"openai_compat","model_name":"your-model-name","base_url":"http://localhost:8000/v1"}' \
  --run-id your-model-v1 \
  --out-dir ./results \
  --concurrency 4
```

**With the canonical judge (Claude Sonnet 4.6 — recommended):**

```bash
export ANTHROPIC_API_KEY=sk-ant-...

be-lexbench \
  --items your_items.jsonl \
  --model '{"kind":"openai_compat","model_name":"your-model-name","base_url":"http://localhost:8000/v1"}' \
  --judge '{"kind":"anthropic","model_name":"claude-sonnet-4-6","api_key_env":"ANTHROPIC_API_KEY"}' \
  --run-id your-model-v1 \
  --out-dir ./results \
  --concurrency 4 \
  --rpm 120
```

---

## Output format

Results are written to `--out-dir/<run-id>/`:

- `items.jsonl` — one row per item: response, latency, programmatic score, judge score, final score
- `summary.json` — per-track means with 95% bootstrap CIs, bilingual parity ratios, difficulty breakdowns

---

## License

**Code**: GNU GPL v3.0. See [LICENSE](LICENSE).
