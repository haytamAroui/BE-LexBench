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

## Architecture Overview

The `be-lexbench` harness is organized as a modular, split-design pipeline. It loads evaluation items, validates them against the schema, invokes model clients, scores responses using programmatic or judge-based rules, and aggregates the results with bootstrap confidence intervals.

```mermaid
graph TD
    A["CLI Entry<br>run_eval.py → main()"] --> B["Load Items<br>JSONL + Schema Validation"]
    B --> C["Model Client<br>models.py → build_client()"]
    C --> D["Generate Response<br>with retry + backoff"]
    D --> E["score_one()<br>Routing Engine"]
    E --> F{"Scoring Method?"}
    F -->|rubric| G["Keyword Gate → Language Gate → LLM Judge"]
    F -->|mcq_exact| H["Final-Committed-Answer Extraction"]
    F -->|citation_validity| I["Citation Pattern Matching + Gold Match"]
    F -->|refusal| J["Refusal Marker Detection"]
    F -->|tool_call| K["Tool-Call Parsing (4 formats)"]
    F -->|keyword_coverage| L["Must-Include / Must-Not Gate"]
    F -->|language_adherence| M["NL/FR/EN Detection"]
    G --> N["Aggregate → summary.json"]
    H --> N
    I --> N
    J --> N
    K --> N
    L --> N
    M --> N
    N --> O["Bootstrap CIs + Bilingual Parity"]
```

### Module Architecture

The codebase is organized into five core modules under `harness/`:

*   **[`run_eval.py`](harness/run_eval.py)**: CLI entry point, concurrent async pipeline orchestration, rate limiting, and evaluation aggregation.
*   **[`models.py`](harness/models.py)**: Client adapters for various model backends (`hf_local`, `openai_compat`, native `anthropic`, and GCP `vertex_anthropic`).
*   **[`scorers.py`](harness/scorers.py)**: Programmatic verification scoring rules (MCQ extraction cascades, Belgian citation regex patterns, keyword gates, and language checks using `langdetect`).
*   **[`judge.py`](harness/judge.py)**: Domain-specific legal reasoning rubrics and judge voting/ensemble routines.
*   **[`stats.py`](harness/stats.py)**: Statistical calculations (95% bootstrap confidence intervals, two-sample significance tests, and bilingual parity ratios).

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

## Scoring methods

| Method | Used by | Programmatic? |
|---|---|---|
| `mcq_exact` | Multiple-choice items | Yes — final-committed-answer extraction |
| `language_adherence` | Bilingual parity track | Yes — heuristic, fastText recommended for release |
| `citation_validity` | Citation integrity track | Yes — optional Juportal/Justel verifier |
| `keyword_coverage` | Compliance tracks (gate) | Yes — gate only; judge sets quality score |
| `rubric` | Open legal reasoning | No — requires an LLM judge |
| `refusal` | Safety calibration | Yes — binary correctness |
| `tool_call` | Function calling | Partial — judge scores argument quality |

`mcq_exact` implements a **final-committed-answer** strategy: for reasoning models that produce chain-of-thought before committing, it scans for the LAST commitment pattern rather than the first letter.

---

## Quickstart

New here? See [docs/quickstart.md](docs/quickstart.md) for a step-by-step guide — install, run the harness on the synthetic sample items, and read the results in under 5 minutes.

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
  --out-dir ./results
```

**With the canonical judge (Claude Sonnet 4.6 — recommended):**

```bash
export ANTHROPIC_API_KEY=sk-ant-...

be-lexbench \
  --items your_items.jsonl \
  --model '{"kind":"openai_compat","model_name":"your-model-name","base_url":"http://localhost:8000/v1"}' \
  --judge '{"kind":"anthropic","model_name":"claude-sonnet-4-6","api_key_env":"ANTHROPIC_API_KEY"}' \
  --run-id your-model-v1 \
  --out-dir ./results
```

---

## Output format

Results are written to `--out-dir/<run-id>/`:

- `items.jsonl` — one row per item: response, latency, programmatic score, judge score, final score
- `summary.json` — per-track means with 95% bootstrap CIs, bilingual parity ratios, difficulty breakdowns

---

## License

**Code**: GNU GPL v3.0. See [LICENSE](LICENSE).
