# End-to-End Workflow Test — `GwH nr. 22/2025` (Council of State urban-planning competence)

> Worked real-case walkthrough through the be-lexbench harness. One Constitutional Court ruling, two mirror items (NL + FR), full CLI trace from `--items` to `summary.json`.

This document demonstrates a complete end-to-end run of a single evaluation item through the be-lexbench harness. The case is **GwH nr. 22/2025 of 13 February 2025**, a real, public-domain decision of the Belgian Constitutional Court already anchored in our `be-administrative-v1` rubric. Every citation and statutory cross-reference below is verifiable against Moniteur Belge and the official Court site.

**Reproducible on a fresh checkout** — see §7.

---

## §1. The case

| Field | Value |
|---|---|
| Court | Grondwettelijk Hof / Cour constitutionnelle |
| Decision number | nr. 22/2025 |
| Date | 13 February 2025 |
| ECLI | `ECLI:BE:GHCC:2025:ARR.22` |
| Subject | Exclusive competence of the Raad van State / Conseil d'État over appeals against urban-planning permits, against a Flemish Region decree claim of regional competence |
| Constitutional hooks | Art. 160 GW (Council of State) and Art. 10/11 GW (equality / non-discrimination) |
| Holding (paraphrased) | The Council of State remains the supreme administrative court for permit-appeal jurisdiction in all three Regions. Regional decrees can shape the procedure but cannot displace the Council of State's exclusive appellate competence. |

**Why this case is a good end-to-end test:** It exercises four scoring dimensions at once:

- **Track 10 — `administrative_law`**: structural separation between Council of State and Court of Cassation.
- **Track 11 — `constitutional_federalism`**: federal-regional competence allocation under the *werkelijke aard* (true character) doctrine.
- **Bilingual parity**: items rendered in NL and FR must score identically when content matches.
- **Citation integrity**: any correct answer must include `ECLI:BE:GHCC:2025:ARR.22` and an `art. 160 GW` reference.

A model that fails any one of these dimensions is caught by a different scorer.

---

## §2. Item construction

Two mirror items in `data/real_cases/gwh_022_2025.jsonl`, both `format: open` so the rubric path executes end-to-end. They share a `parity_group` so the aggregation in `summary.json -> bilingual_parity` pairs them automatically.

### §2.1 — Dutch (`nl`) item

```json
{
  "id": "real-case-gwh-022-2025-nl-001",
  "track": "constitutional_federalism",
  "language": "nl",
  "parity_group": "real-case-gwh-022-2025",
  "difficulty": "core",
  "jurisdiction": "FED",
  "format": "open",
  "prompt": "Welke rechtbank is bevoegd voor een beroep tegen een stedenbouwkundige vergunning in het Vlaams Gewest, en waarom? Verwijs naar GwH nr. 22/2025.",
  "system": null,
  "context": null,
  "tools": null,
  "choices": null,
  "scoring": {
    "method": "rubric",
    "rubric_id": "be-constitutional-v1",
    "answer": null,
    "reference": "De Raad van State is exclusief bevoegd voor het annulatieberoep tegen stedenbouwkundige vergunningen (GwH nr. 22/2025, ECLI:BE:GHCC:2025:ARR.22). Regionale decreten mogen de procedurele regels vastleggen, maar kunnen de exclusieve bevoegdheid van de Raad van State op grond van artikel 160 GW niet verdringen.",
    "must_include": ["Raad van State", "artikel 160"],
    "must_not_include": ["Hof van Cassatie", "1382 BW"],
    "valid_citations": [
      "ECLI:BE:GHCC:2025:ARR.22",
      "GwH nr. 22/2025",
      "art. 160 GW"
    ],
    "expected_refusal": null,
    "expected_tool": null,
    "expected_args": null
  },
  "provenance": {
    "author": "Haytam Aroui",
    "validated_by": null,
    "review_date": null,
    "source": "public-domain Constitutional Court ruling",
    "canary": "DEMO-REAL-CASE-gwh-022-2025-NOT-IN-SCORING-SET"
  }
}
```

### §2.2 — French (`fr`) mirror

```json
{
  "id": "real-case-gwh-022-2025-fr-001",
  "track": "constitutional_federalism",
  "language": "fr",
  "parity_group": "real-case-gwh-022-2025",
  "difficulty": "core",
  "jurisdiction": "FED",
  "format": "open",
  "prompt": "Quelle juridiction est compétente pour connaître d'un recours contre un permis d'urbanisme en Région flamande, et pourquoi ? Faites référence à l'arrêt C.C. n° 22/2025.",
  "system": null,
  "context": null,
  "tools": null,
  "choices": null,
  "scoring": {
    "method": "rubric",
    "rubric_id": "be-constitutional-v1",
    "answer": null,
    "reference": "Le Conseil d'État est exclusivement compétent pour le recours en annulation contre les permis d'urbanisme (C.C. n° 22/2025, ECLI:BE:GHCC:2025:ARR.22). Les décrets régionaux peuvent fixer les règles de procédure, mais ne peuvent pas écarter la compétence exclusive du Conseil d'État sur la base de l'article 160 de la Constitution.",
    "must_include": ["Conseil d'État", "article 160"],
    "must_not_include": ["Cour de cassation", "articles 1382"],
    "valid_citations": [
      "ECLI:BE:GHCC:2025:ARR.22",
      "C.C. n° 22/2025",
      "art. 160 Const."
    ],
    "expected_refusal": null,
    "expected_tool": null,
    "expected_args": null
  },
  "provenance": {
    "author": "Haytam Aroui",
    "validated_by": null,
    "review_date": null,
    "source": "public-domain Constitutional Court ruling",
    "canary": "DEMO-REAL-CASE-gwh-022-2025-NOT-IN-SCORING-SET"
  }
}
```

---

## §3. Workflow execution

### §3.1 — File layout

```
data/real_cases/
  └── gwh_022_2025.jsonl          # both NL and FR items, two lines
results/gwh-022-2025-run-v1/
  ├── items.jsonl                 # per-item rows (resumable — appended, fetched)
  └── summary.json                # per-track means + bootstrap CIs + bilingual parity
```

### §3.2 — CLI invocation

```bash
export ANTHROPIC_API_KEY=sk-ant-...          # canonical Claude-Sonnet-4.6 judge

be-lexbench \
  --items data/real_cases/gwh_022_2025.jsonl \
  --model '{
    "kind": "openai_compat",
    "model_name": "your-llm",
    "base_url": "http://localhost:8000/v1"
  }' \
  --judge '{
    "kind": "anthropic",
    "model_name": "claude-sonnet-4-6",
    "api_key_env": "ANTHROPIC_API_KEY"
  }' \
  --judge '{
    "kind": "vertex_anthropic",
    "model_name": "claude-sonnet-4-6",
    "project": "your-gcp-project",
    "region": "us-east5"
  }' \
  --run-id gwh-022-2025-run-v1 \
  --out-dir ./results
```

Two `--judge` flags = an ensemble. The Anthropic / Vertex AI split is technically the same model on two paths; that's a *starting* lineage-diversity pattern. For publication-grade ensemble, swap one judge for a different model family (e.g. a GPT-4 judge alongside the Claude judge).

### §3.3 — Per-item pipeline (what `harness.run_eval.main()` does)

For each item in the JSONL:

1. **Skip-if-done** — `load_done(results_path)` reads the already-written JSONL rows. Re-running the same `--run-id` resumes from the last completed item.
2. **Format the prompt** — `format == "open"` → pass `item.prompt` unchanged. MCQ items get the choices appended, tool_call items get the schema; irrelevant for this case.
3. **Call the model** — `client.generate(prompt, system=item.system, context=item.context, tools=item.tools, max_tokens=args.max_tokens, temperature=args.temperature)`. Default `temperature=0.0` for fair comparison across runs.
4. **Score (`score_one`)** — `method == "rubric"` routes directly to `J.judge_item(item, response, judge_clients)`. Programmatic scorers (`citation_validity`, `keyword_coverage`) are bypassed for `method="rubric"` items.
5. **Judge ensemble** — each `judge_client.generate(prompt, max_tokens=300, temperature=0.0)` returns free-form text. `_parse_judge_json` extracts `{score: 0–4, rationale, fabricated_citation}`. The recorded `judge_model` on each vote is the resolved model ID the API returned — methodology §5.2 says the judge version must be pinned across a leaderboard refresh.
6. **Aggregate votes** — any `fabricated_citation=true` clamps the item to 0 (`agreement="fabrication_cap"`); otherwise mean / 4.0, with `agreement="tight"` for spread ≤ 1.
7. **Append + flush** — one JSONL row written per item, `flush()` after each. SIGTERM-safe: re-run resumes from where the kill happened.

After every item is scored, `aggregate(results_path, summary_path, ...)` reads the full JSONL and writes `summary.json`.

---

## §4. Score traces (worked examples)

### §4.1 — Correct answer, judge returns high

```
response: "De Raad van State is bevoegd krachtens art. 160 GW
           (GwH nr. 22/2025, ECLI:BE:GHCC:2025:ARR.22)."

Judge #1 (Anthropic):
  score: 4
  rationale: "Correct court, correct constitutional basis, citations accurate."
  fabricated_citation: false

Judge #2 (Vertex Anthropic):
  score: 4
  rationale: "Matches reference; mirrors the FR item."

spread = 0  → agreement = "tight"
mean   = 4  → score01    = 1.0
```

### §4.2 — Hallucinated ECLI

```
response: "De Raad van State is bevoegd (GwH nr. 99/2099,
           ECLI:BE:GHCC:2099:ARR.999)."

Judge vote:
  fabricated_citation: true   (any one judge flips the cap)

final_score: 0.0
agreement:  "fabrication_cap"
```

The fabrication cap is enforced in `judge.py:judge_item` *before* mean calculation — confident hallucination scores zero, never averaged.

### §4.3 — Wrong court (Council of State vs. Court of Cassation conflation)

```
response: "Het Hof van Cassatie is bevoegd (GwH nr. 22/2025)."

`must_not_include` matched "Hof van Cassatie" → already a content red flag.
Judge vote:
  score: 1   (rubric anchor: structural error caps at 1)
  rationale: "Confuses supreme administrative court with supreme ordinary court."
  fabricated_citation: false

final_score: 0.25    (judge_mean 1 / 4 = 0.25)
```

### §4.4 — Bilingual divergence

```
NL item, judge score mean = 3
FR item, same model, judge score mean = 1
→ summary.json -> bilingual_parity["constitutional_federalism"] = {
    "nl_acc_pct": 75.0, "fr_acc_pct": 25.0, "parity_ratio": 0.333
  }
→ a 67 % accuracy drop is a signal for NL-only tuning, not for substance
```

---

## §5. Reading `summary.json`

After the run, `./results/gwh-022-2025-run-v1/summary.json` looks like:

```json
{
  "run_id": "gwh-022-2025-run-v1",
  "timestamp_utc": "2026-...",
  "model_spec": { "kind": "openai_compat", "model_name": "your-llm", "base_url": "..." },
  "judge_specs": [
    { "kind": "anthropic", "model_name": "claude-sonnet-4-6" },
    { "kind": "vertex_anthropic", "model_name": "claude-sonnet-4-6" }
  ],
  "n_items": 2,
  "n_unscored_no_judge": 0,
  "tracks": {
    "constitutional_federalism": {
      "n": 2,
      "mean_pct": 100.0,
      "ci_low_pct": 100.0,
      "ci_high_pct": 100.0,
      "by_difficulty": {
        "core": { "n": 2, "mean_pct": 100.0, "ci_low_pct": 100.0, "ci_high_pct": 100.0 }
      }
    }
  },
  "bilingual_parity": {
    "constitutional_federalism": {
      "nl_acc_pct": 100.0,
      "fr_acc_pct": 100.0,
      "parity_ratio": 1.0,
      "n_nl": 1,
      "n_fr": 1
    }
  },
  "note": "Seed run. Items require SME validation before these numbers are publishable (see docs/methodology.md §0)."
}
```

Reading top to bottom:

- **`n_items=2`, `n_unscored_no_judge=0`** → complete run, nothing lost to missing judge.
- **`tracks["constitutional_federalism"]`** is the single track this case exercises. With `n=2`, the bootstrap CI degenerates (`ci_low == ci_high == mean`); real leaderboard numbers need ≥ 20 cells per language-difficulty pair.
- **`bilingual_parity["constitutional_federalism"]`** shows NL and FR both present. `parity_ratio=1.0` means no NL↔FR accuracy drop on this case — a strong positive signal.
- **`note:`** flags that real publication still requires SME validation gate (per `docs/methodology.md §0`).

---

## §6. Failure modes — what trips LLMs up

Common ways models miss GwH nr. 22/2025:

| Failure | Where caught | Cap / signal |
|---|---|---|
| **Confuses Council of State with Court of Cassation** | judge on `be-administrative-v1` (cap-1 structural-error rule) | score ≤ 1 |
| **Wrong article number** (e.g. `art. 159 GW`, `art. 161 GW`) | judge on `be-constitutional-v1` (mixed-up semantics) | score ≤ 2 |
| **Cross-track contamination** (cites `art. 6.5 BW` / civil-law framing) | `must_not_include: ["1382 BW"]` keyword gate (free 0) | score = 0 |
| **Bilingual divergence** (NL correct, FR wrong) | aggregated in `summary.json -> bilingual_parity` | `parity_ratio != 1.0` |
| **Fabricated ECLI** | `citation_validity` + judge `fabricated_citation` | score = 0 (fabrication_cap) |
| **Confident-but-wrong article** (e.g. `art. 159 GW` instead of art. 160) | judge on `be-constitutional-v1` rubric | score ≤ 2 |

Each failure mode isolates a different layer of model capability, which is what makes a single real case useful for diagnostic profiling.

---

## §7. Reproducibility checklist

On a fresh checkout:

```bash
# 1. Install
git clone https://github.com/<your-org>/be-lexbench.git
cd be-lexbench
pip install -e .

# 2. Place the JSONL
mkdir -p data/real_cases
# (write gwh_022_2025.jsonl — see §2)

# 3. Smoke-test the install
python -c "from harness import scorers, judge, run_eval, models, stats"
be-lexbench --help

# 4. Run with the canonical judge ensemble
export ANTHROPIC_API_KEY=sk-ant-...
be-lexbench \
  --items data/real_cases/gwh_022_2025.jsonl \
  --model '{"kind":"openai_compat","model_name":"your-llm","base_url":"http://localhost:8000/v1"}' \
  --judge '{"kind":"anthropic","model_name":"claude-sonnet-4-6","api_key_env":"ANTHROPIC_API_KEY"}' \
  --run-id gwh-022-2025-anthropic-v1 \
  --out-dir ./results

# 5. Inspect
cat results/gwh-022-2025-anthropic-v1/summary.json | python -m json.tool
```

**Expected**, depending on model quality:

| Scenario | `summary.json -> tracks["constitutional_federalism"]` | `agreement` | `bilingual_parity` |
|---|---|---|---|
| Strong model, correct citations | `mean_pct: 100.0`, `n: 2` | `"tight"` | `parity_ratio: 1.0` |
| Strong model, fabricated ECLI | `mean_pct: 0.0`, `n: 2` | `"fabrication_cap"` | `parity_ratio: null` (no NL/FR split, both 0) |
| NL-tuned model, FR drifts | NL=100, FR=50 → `mean_pct: 75.0` | `"tight"` (single judge) | `parity_ratio: 0.5` |
| Hallucinates court | `mean_pct: 25.0`, n=2 | `"tight"` | varies |

If `n_unscored_no_judge > 0`, you ran without `--judge` on `rubric` items — rerun with a judge spec.

---

## §8. Where to go next

- One case is one data point. For stable per-track CIs you need ≥ 20 cells per language-difficulty pair (methodology §0); plan for ~1,680 items across all 14 tracks.
- Add the canonical judge to a *different-lineage* model (GPT-4 family or Gemini) for publication-grade ensemble diversity.
- Once 5+ cases like this exist, aggregate them across `parity_group` keys and report the per-track `bilingual_parity` headline metric.
- Track 12 (`citation_integrity`) and Track 13 (`safety_calibration`) need their own dedicated cases — this walkthrough only stresses 10/11/1.
- The gated scoring bank follows the contamination-resistance design from `docs/data_access.md`; this walkthrough is suitable for development, not leaderboard publication.

---

*Use:* Walk a new contributor through this file before they touch the harness. It is also the reference for "is my model doing the right thing on a real Belgian case" sanity checks.
