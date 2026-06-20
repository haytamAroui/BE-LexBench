# Run Analysis — `GwH nr. 22/2025` mock end-to-end

> Companion to [`gwh_022_2025_e2e_walkthrough.md`](gwh_022_2025_e2e_walkthrough.md). That doc says **how** to run. This one says **what happened**, including a Windows-specific UTF-8 corruption bug discovered during the first run and fixed in `harness/run_eval.py` + `tools/dev_mock_openai.py`.

Two runs exist in this repo's `results/` directory:

| Run id | Status | Reason |
|---|---|---|
| `gwh-022-2025-mock-v1` | **DELETED** | Contained cp1252 single-byte corruption of FR characters; pre-fix artifact |
| `gwh-022-2025-mock-v2` | **current, valid** | Re-run after the encoding fix; FR bytes are properly UTF-8 on disk |

This document interprets **`gwh-022-2025-mock-v2`** (the valid run). §9 documents the bug found in `mock-v1` and the fix.

---

## §1. What ran

| Field | Value |
|---|---|
| Run id | `gwh-022-2025-mock-v2` |
| Items file | `data/real_cases/gwh_022_2025.jsonl` (2 items) |
| Model | `openai_compat` against `http://127.0.0.1:8765/v1` (`mock`) |
| Judge | `openai_compat` against the same mock (`mock-judge`) |
| Mock Content-Type | `application/json; charset=utf-8` (RFC 8259 — explicit charset) |
| Items scored | 2 of 2 (`n_unscored_no_judge == 0`) |
| Tracks exercised | 1 — `constitutional_federalism` (only track represented by these items) |

---

## §2. Item-by-item results

Each item scored through the rubric path (`method: "rubric"` → `J.judge_item(...)` → judge ensemble). The programmatic `citation_validity` and `keyword_coverage` scorers are bypassed for rubric-method items in the current `score_one` flow; the judge's `fabricated_citation` flag is the sole hallucination gate.

### §2.1 — `real-case-gwh-022-2025-nl-001` (Dutch)

```
prompt      : "Welke rechtbank is bevoegd voor een beroep tegen een
               stedenbouwkundige vergunning in het Vlaams Gewest...?"
response    : "De Raad van State is exclusief bevoegd voor het beroep
               tegen de stedenbouwkundige vergunning. Zie GwH nr.
               22/2025, ECLI:BE:GHCC:2025:ARR.22, op grond van artikel
               160 GW."
judge vote  : {score: 4, rationale: "Correct court, correct constitutional
               basis, citations accurate.", fabricated_citation: false,
               judge_model: "mock-judge"}
agreement   : "tight"
final_score : 1.0   (judge_mean 4 / 4)
```

### §2.2 — `real-case-gwh-022-2025-fr-001` (French mirror)

```
prompt      : "Quelle juridiction est compétente pour connaître d'un
               recours contre un permis d'urbanisme en Région flamande...?"
response    : "Le Conseil d'État est exclusivement compétent pour le
               recours en annulation contre les permis d'urbanisme. Voir
               C.C. n° 22/2025, ECLI:BE:GHCC:2025:ARR.22, sur la base
               de l'article 160 de la Constitution."
judge vote  : {score: 4, rationale: "Correct court, correct constitutional
               basis, citations accurate.", fabricated_citation: false,
               judge_model: "mock-judge"}
agreement   : "tight"
final_score : 1.0
```

**Byte-level verification of the response on disk (mock-v2, post-fix):**

```
hex around "d'État":    64 27 c3 89 74 61 74  → 'd', "'", 0xC3, 0x89 (UTF-8 É), 't', 'a', 't'
hex around "compétent": 63 6f 6d 70 c3 a9 74 65 6e 74  → 'c','o','m','p', 0xC3 0xA9 (UTF-8 é), 't','e','n','t'
hex around "n°":        6e c2 b0  → 'n', 0xC2 0xB0 (UTF-8 °)
contains 0xc3 0x89: TRUE   contains 0xc2 0xb0: TRUE
lone 0xc9 / 0xb0 / 0xe9 (NOT preceded by 0xc3 / 0xc2 lead):  0 occurrences
contains 0xef 0xbf 0xbd (UTF-8 U+FFFD literal):  FALSE
```

### §2.3 — Why both items scored 1.0

The mock returned well-formed answers that contained both gold citations and the substantive substance. The mock judge, given any non-empty judge prompt, blindly returns `{score: 4, fabricated_citation: false}` — i.e. the mock is a **deterministic rating always-max** model. That makes per-item score a coincidence of the mock fixture, not a real measurement of model quality.

---

## §3. Aggregate — what `summary.json` says

```json
{
  "run_id": "gwh-022-2025-mock-v2",
  "model_spec": {
    "kind": "openai_compat",
    "model_name": "mock",
    "base_url": "http://127.0.0.1:8765/v1"
  },
  "judge_specs": [
    {"kind": "openai_compat", "model_name": "mock-judge",
     "base_url": "http://127.0.0.1:8765/v1"}
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
        "core": {"n": 2, "mean_pct": 100.0,
                  "ci_low_pct": 100.0, "ci_high_pct": 100.0}
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

Read top to bottom:

- **`n_items=2`, `n_unscored_no_judge=0`** — every item got a final score; no items dropped due to missing judge.
- **`tracks["constitutional_federalism"]`** is the **only** track present (the items exercise Track 11). Both items are `difficulty="core"`, so `by_difficulty` has just one entry, also 100%.
- **`ci_low == ci_high == 100.0`** — bootstrap CIs degenerate at n=2. The percentile method needs ≥20 resamples to produce a meaningful interval; with two items, both resamples either pick both or pick none, so `ci_low == ci_high == mean`. Real benchmarking requires n ≥ 20 per cell (methodology §0).
- **`bilingual_parity["constitutional_federalism"]: parity_ratio=1.0`** — both NL and FR items scored equally. With 1 vs 1, this is a degenerate test of parity; a real signal requires ≥10 mirror pairs.
- **`note:`** — methodology §0 publication gate applies. This run is structurally valid but its numbers are not publishable benchmark results until `provenance.validated_by` is set on each item.

---

## §4. What this run CAN prove

- **The harness compiles, runs, and produces output.** `python -m harness.run_eval` imports cleanly, reads the JSONL, builds judge prompts, calls the `--model` and `--judge` clients, writes per-item rows, and aggregates to `summary.json`. No exceptions, no crashes.
- **The mock-server boundary works.** A model spec of the form `{"kind":"openai_compat","model_name":"...","base_url":"http://..."}` is achievable in-process without an external API key.
- **The judge-routing logic distinguishes content.** The mock's `RUBRIC:` / `fabricated_citation` / `Score on a 0-4` heuristic correctly routes user prompts into the judge-return branch, and the call flows through `_parse_judge_json`.
- **The schema is end-to-end enforceable.** Two real items conforming to `schema/eval_item.schema.json` were loaded, scored, and aggregated without schema validation errors.
- **Bilingual parity is wired up at this scale.** The aggregator in `run_eval.py` correctly recognises that 1 NL + 1 FR in the same track under the same `parity_group` produce a parity ratio block.
- **UTF-8 round-trip works on Windows (after the §9 fix).** FR `État`, `compétent`, `n°` characters survive open-write-read-close on `cp1252`-default Python with the explicit `encoding="utf-8"` kwarg.

---

## §5. What this run CANNOT prove

- **Any measure of model quality.** The mock returns always-correct answers; the mock judge always scores 4. The fact `mean_pct=100` says nothing about *your* model.
- **Numerical stability of CIs.** With n=2, bootstrap CIs degenerate. A real run needs ≥20 NL items per difficulty and ≥20 FR items per difficulty before the percentile CI is meaningful (methodology §0).
- **Language-pair sensitivity.** With 1 NL + 1 FR, the parity ratio is either 1.0 (both score-aligned) or 0.5 (one-sided failure) — there's no in-between. A meaningful NL↔FR parity signal needs ≥10 mirror pairs.
- **Judge-ensemble divergence.** A single mock judge always agrees with itself, so the `agreement` field is uniformly `"tight"`. With a real *different-lineage* judge added (e.g. GPT-4 vs Claude-Sonnet-4.6), divergence patterns start surfacing.
- **Citation-integrity discrimination.** The mock returns no fabricated ECLIs but also no wrong-name court mistakes. The structural-error cap (`cap at 1` for Council of State vs Court of Cassation confusion on `be-administrative-v1`) was not exercised. A real model would.

---

## §6. Failure modes the mock CANNOT reproduce

For diagnostic value when you switch to a real model, recall the case's expected traps (§6 of the walkthrough):

| Failure | Where caught | Cap / signal |
|---|---|---|
| Council of State vs Court of Cassation | judge on `be-administrative-v1` | score ≤ 1 |
| Wrong article number (art. 159 / 161 GW) | judge on `be-constitutional-v1` | score ≤ 2 |
| Cross-track contamination (`art. 6.5 BW`) | `must_not_include: ["1382 BW"]` keyword gate | score = 0 |
| NL↔FR divergence | `bilingual_parity.parity_ratio != 1.0` | drift signal |
| Fabricated ECLI | `citation_validity` + judge fabrication flag | score = 0 |

A real model run exposes these. The mock run does not.

---

## §7. Limitations of n=2 statistical reporting

Two sample points cannot tell you whether 100% is *actually* 100% or 100% with ±30% confidence. The bootstrap CI computation in `harness/stats.py` correctly reports `ci_low == ci_high` at degenerate n; the rounding makes it look precise when it isn't.

**Cell-size rule of thumb** (from `docs/methodology.md §0`):

> 14 tracks × 2 languages (NL+FR) × 3 difficulty levels = 84 cells.
> For stable per-track bootstrap CIs (10,000 resamples, 95 % percentile method) at ~20 items per cell, you want ~1,680 items. With ~130 items (e.g. a launch set), report per-track numbers as **directional only** with wide CIs.

This run is well below that. Treat it as a smoke-test of the pipeline, not as benchmark data.

---

## §8. Recommended next step: a real-model run

Drop-in replacement for the mock invocation (note: the FR fixture only needs `État`/`compétent`/`n°` to reach this server, which the harness now writes correctly thanks to §9):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...

be-lexbench \
  --items data/real_cases/gwh_022_2025.jsonl \
  --model '{"kind":"openai_compat","model_name":"gpt-4o","base_url":"https://api.openai.com/v1","api_key_env":"OPENAI_API_KEY"}' \
  --judge '{"kind":"anthropic","model_name":"claude-sonnet-4-6","api_key_env":"ANTHROPIC_API_KEY"}' \
  --run-id gwh-022-2025-real-v1 \
  --out-dir ./results
```

Now `mean_pct` reflects actual behaviour, `bilingual_parity.parity_ratio` is a real signal, and the judge ensemble exposes model-vs-judge disagreement patterns.

---

## §9. Encoding incident (the bug this run discovered, and how it was fixed)

### §9.1 — Symptom

`gwh-022-2025-mock-v1` ran end-to-end without exceptions. The harness reported `n_items=2`, `n_unscored_no_judge=0`, `mean_pct=100.0`. The summary looked clean. **But the FR item's `response` field, read back from `items.jsonl` with `encoding="utf-8"`, contained U+FFFD (U+FFFD) wherever `É`, `é`, or `°` should have been.** This was a real corruption, not a terminal display artefact.

### §9.2 — Root cause (verified at the byte level)

Running the harness on Windows: `locale.getpreferredencoding()` returns `"cp1252"`. Without an explicit `encoding` kwarg, `open(path, "a")` writes Python `str` characters through cp1252. For FR content:

| Character (Unicode) | UTF-8 bytes (correct) | cp1252 bytes (what got written on Windows) |
|---|---|---|
| U+00C9 `É` | `0xC3 0x89` | `0xC9` alone |
| U+00E9 `é` | `0xC3 0xA9` | `0xE9` alone |
| U+00B0 `°` | `0xC2 0xB0` | `0xB0` alone |

The bytes `0xC9`, `0xE9`, `0xB0` are valid cp1252 single bytes but **invalid UTF-8 lead bytes**. So the bytes on disk were wrong from the moment of write, and any subsequent UTF-8 read of the file (`encoding="utf-8"` with `errors='replace'` is what most modern readers, including Python's `open`, use) re-introduced U+FFFD at those positions.

The U+FFFD never landed on disk; it was re-introduced each time the corrupted-bytes file was read with UTF-8. The earlier hypothesis that "it's only a terminal display issue" (recorded in the prior version of this §2.2) was wrong.

### §9.3 — The fix

Two sites were changed:

**1. `harness/run_eval.py`** — every `open()` now specifies `encoding="utf-8"`:
- `load_items`: `open(path, encoding="utf-8")`
- `load_done`: `open(results_path, encoding="utf-8")`
- main write loop: `open(results_path, "a", encoding="utf-8")`
- `aggregate` rows read: `open(results_path, encoding="utf-8")`
- summary write: `open(summary_path, "w", encoding="utf-8")`

A module-level docstring block ("File-encoding invariant") documents the rationale and the cross-OS behaviour, so future contributors do not silently re-introduce the bug.

The combination `ensure_ascii=False` (already present) + `encoding="utf-8"` (new) is a **partial** self-check, not a full one: if a future regression accidentally drops `encoding="utf-8"`, the cp1252 codec will raise `UnicodeEncodeError` on codepoints *outside* its range (en-dash `–`, em-dash `—`, smart quotes `'`/`"`, ellipsis `…`, ligatures `œ`/`Æ`, the euro sign `€`), so writing legal text containing those characters fails loudly at write time. For codepoints that *are* in cp1252 — including all of this corpus's FR/NL text (`É` U+00C9, `é` U+00E9, `°` U+00B0, `à` U+00E0, `ç` U+00E7, `ï` U+00EF) — the combination is silent and reproduces the original bug. The explicit `encoding="utf-8"` kwarg itself is therefore the primary safeguard; the cp1252 `UnicodeEncodeError` on out-of-range chars is useful but not sufficient.

**2. `tools/dev_mock_openai.py`** — defence-in-depth on the mock's Content-Type:
- `Content-Type: application/json` → `Content-Type: application/json; charset=utf-8`
- Inline comment cites RFC 8259, which leaves JSON's default charset implicit, justifying why an explicit `charset=utf-8` is required for cross-client reliability.

### §9.4 — Verification (post-fix)

`gwh-022-2025-mock-v2` was produced after the fix. Byte-level checks on its `items.jsonl`:

```
hex around "d'État":    64 27 c3 89 74 61 74
hex around "compétent": 63 6f 6d 70 c3 a9 74 65 6e 74
hex around "n°":        6e c2 b0
contains 0xc3 0x89: TRUE   contains 0xc2 0xb0: TRUE
lone 0xc9 / 0xb0 / 0xe9 (NOT preceded by 0xc3 / 0xc2 lead): 0 occurrences
contains 0xef 0xbf 0xbd (UTF-8 U+FFFD literal):          FALSE
```

UTF-8 round-trip (`json.loads(open(path, encoding="utf-8"))`) returns the response with literal `État`, `compétent`, `n°` and no U+FFFD.

`gwh-022-2025-mock-v1` (the corrupted-bytes run) has been **deleted** from `results/`. It was a development artefact, not data; carrying it forward would have meant anyone re-reading that file would re-introduce U+FFFD on read.

### §9.5 — Implications for production

If you ever swap the mock for a real OpenAI-compatible provider on Windows and the response contains `État`, `compétent`, `n°`, the published `items.jsonl` will preserve them correctly. This is now the same behaviour across Linux (default UTF-8), macOS (default UTF-8), and Windows (forced UTF-8).

A future-proof condition: if anyone adds a file `open()` to `harness/` without `encoding="utf-8"`, the same bug returns. The module-level invariant line in `run_eval.py` and the corresponding invariant line suggested for `judge.py` (no current file I/O but critical to add before any debug-write) are the primary defenses.

---

## Appendix A — actual `summary.json` from `gwh-022-2025-mock-v2`

Reproduced verbatim from `results/gwh-022-2025-mock-v2/summary.json`. (The run-id `mock-v1` in the body of older reproductions of this doc refers to the now-deleted pre-fix run; do not confuse them.)

```json
{
  "run_id": "gwh-022-2025-mock-v2",
  "model_spec": {
    "kind": "openai_compat",
    "model_name": "mock",
    "base_url": "http://127.0.0.1:8765/v1"
  },
  "judge_specs": [
    {
      "kind": "openai_compat",
      "model_name": "mock-judge",
      "base_url": "http://127.0.0.1:8765/v1"
    }
  ],
  "n_items": 2,
  "n_unscored_no_judge": 0,
  "tracks": {
    "constitutional_federalism": {
      "n": 2, "mean_pct": 100.0,
      "ci_low_pct": 100.0, "ci_high_pct": 100.0,
      "by_difficulty": {
        "core": {"n": 2, "mean_pct": 100.0,
                  "ci_low_pct": 100.0, "ci_high_pct": 100.0}
      }
    }
  },
  "bilingual_parity": {
    "constitutional_federalism": {
      "nl_acc_pct": 100.0, "fr_acc_pct": 100.0,
      "parity_ratio": 1.0, "n_nl": 1, "n_fr": 1
    }
  },
  "note": "Seed run. Items require SME validation before these numbers are publishable (see docs/methodology.md §0)."
}
```

## Appendix B — actual `items.jsonl` from `gwh-022-2025-mock-v2`

UTF-8 preserved on disk. Read with `open(path, encoding="utf-8")` and you get the literal characters:

```
NL line:
{"id": "real-case-gwh-022-2025-nl-001", "track": "constitutional_federalism",
 "language": "nl", "difficulty": "core", "parity_group": "real-case-gwh-022-2025",
 "response": "De Raad van State is exclusief bevoegd voor het beroep tegen de stedenbouwkundige vergunning. Zie GwH nr. 22/2025, ECLI:BE:GHCC:2025:ARR.22, op grond van artikel 160 GW.",
 "latency_s": 0.0, "score": 1.0, "scoring_method": "rubric",
 "programmatic": null,
 "judge": {"score01": 1.0, "votes": [{"score": 4, "rationale": "Correct court, correct constitutional basis, citations accurate.", "fabricated_citation": false, "judge_model": "mock-judge"}], "agreement": "tight"},
 "canary": "DEMO-REAL-CASE-gwh-022-2025-NOT-IN-SCORING-SET"}

FR line (UTF-8 bytes intact — État, compétent, n° preserved):
{"id": "real-case-gwh-022-2025-fr-001", "track": "constitutional_federalism",
 "language": "fr", "difficulty": "core", "parity_group": "real-case-gwh-022-2025",
 "response": "Le Conseil d'État est exclusivement compétent pour le recours en annulation contre les permis d'urbanisme. Voir C.C. n° 22/2025, ECLI:BE:GHCC:2025:ARR.22, sur la base de l'article 160 de la Constitution.",
 "latency_s": 0.0, "score": 1.0, "scoring_method": "rubric",
 "programmatic": null,
 "judge": {"score01": 1.0, "votes": [{"score": 4, "rationale": "Correct court, correct constitutional basis, citations accurate.", "fabricated_citation": false, "judge_model": "mock-judge"}], "agreement": "tight"},
 "canary": "DEMO-REAL-CASE-gwh-022-2025-NOT-IN-SCORING-SET"}
```

---

*Use:* This is a reference for what success and failure look like at the output layer — including how a Windows-only `cp1252`-default Python install can silently corrupt a UTF-8 pipeline until you look at bytes directly. Compare a real-model run's output side by side; that's where the diagnostic value lives.
