# Development Guide

Everything a contributor needs to set up a local environment, run tests, and understand the project structure.

---

## Prerequisites

- Python 3.10, 3.11, or 3.12
- Git

No GPU, no API keys, and no external services are required to run the test suite or work on the harness code.

---

## Local setup

```bash
git clone https://github.com/BE-LexBench/be-lexbench.git
cd be-lexbench

# Editable install — harness/ is importable as a package immediately
pip install -e .

# Install test runner
pip install pytest

# Smoke-test the install
python -c "from harness import scorers, judge, run_eval, models, stats"
be-lexbench --help
```

### Optional extras

```bash
# Vertex AI judge path (GCP ADC auth — adds google-cloud-aiplatform)
pip install -e ".[vertex]"

# Local HuggingFace checkpoint evaluation (adds torch, transformers, peft)
pip install -e ".[local]"
```

---

## Running the test suite

```bash
python -m pytest -q                        # full suite, quiet output
python -m pytest -v                        # verbose (shows every test name)
python -m pytest tests/test_scorers.py     # single file
python -m pytest -k "test_mcq"             # tests matching a keyword
```

The full suite runs in under 10 seconds with no network calls, no GPU, and no API keys.

**Test files and what they cover:**

| File | Module | Key scenarios |
|---|---|---|
| `tests/test_scorers.py` | `harness/scorers.py` | All 7 scorers, extraction patterns, needs_judge gate |
| `tests/test_stats.py` | `harness/stats.py` | Bootstrap CI/diff, parity ratio, edge cases |
| `tests/test_judge.py` | `harness/judge.py` | Rubric prompt, JSON parsing, ensemble voting |
| `tests/test_run_eval.py` | `harness/run_eval.py` | load/score/aggregate, all scoring paths |
| `tests/test_models.py` | `harness/models.py` | build_client factory, static helpers, client init |

---

## Project structure

```
be-lexbench/
├── harness/                # The scoring harness (published, GPL-3.0-only)
│   ├── __init__.py
│   ├── models.py           # Model clients (OpenAI-compat, Anthropic, Vertex, HF local)
│   ├── scorers.py          # Programmatic scorers (mcq_exact, citation_validity, …)
│   ├── judge.py            # LLM-as-judge: rubrics, ensemble, fabrication cap
│   ├── run_eval.py         # CLI entry point + aggregation
│   └── stats.py            # Bootstrap CI, diff test, parity ratio
├── tests/                  # Pytest test suite
├── schema/
│   └── eval_item.schema.json   # Item format (JSON Schema)
├── data/
│   └── sample/             # Synthetic illustrative items (NOT scoring items)
├── docs/
│   ├── quickstart.md       # 5-minute end-to-end guide
│   ├── methodology.md      # Scoring protocol and design decisions
│   └── data_access.md      # How to request the gated item bank
└── .github/
    ├── ISSUE_TEMPLATE/     # Bug report, feature request, access request
    └── workflows/          # CI (pytest) and release-please automation
```

---

## Commit conventions

See [CONTRIBUTING.md](CONTRIBUTING.md#commit-convention). The short version:

```
<type>(<scope>): <subject>

One intro sentence.

- bullet point
- bullet point
```

Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`, `perf`.

---

## What requires maintainer approval

The following files must not be changed without explicit maintainer approval — changes affect scoring validity and may invalidate published benchmark numbers:

- `harness/scorers.py` — programmatic scoring logic
- `harness/judge.py` — LLM judge rubrics and ensemble logic
- `schema/eval_item.schema.json` — item format
- `data/` — item content (most of this directory is gitignored)

Everything else — model clients, CLI, statistics, documentation, CI — is open for contribution via the normal PR flow.

---

## Release process

Releases are automated via [release-please](https://github.com/googleapis/release-please). On every push to `main`, release-please maintains an open release PR that accumulates changes in `CHANGELOG.md`. Merging that PR bumps the version, tags the commit, and creates a GitHub Release.

No manual version bumps or PyPI publishing are needed.

---

## Coding style

- **Formatter / linter:** `ruff` (line length 100, single quotes) — run `ruff check harness/ tests/` locally
- **Type hints:** used throughout; `from __future__ import annotations` in every module
- **Comments:** only when the *why* is non-obvious — no docstrings restating the function name
- **Test naming:** `test_<thing>_<condition>` — readable as a specification

---

## Process rules & failure modes

This section captures hard-won lessons about *working with the codebase* rather
than *modifying the code*. The three rules below were all violated during
multi-round debugging sessions and cost rounds; they exist so the next
contributor (human or AI) doesn't repeat the cycle.

### Bytes.fromhex rewrite (workstream origin)

When a `write_file` of `tests/test_scorers.py::TestToolCall::test_json_tag_name_match`
was authored via the standard LLM prompt pipeline, the literal string
`tool_call{...}tool_call` (the LLM tool-call XML-with-JSON wire format) was
stripped of its `<`, `>`, and `/` characters by an upstream rendering layer,
leaving the unbracketed 9-letter token in place of the canonical tags. The
resulting test failure (`assert 0.5 == 0.0` because the regex could not
recover the opening/closing tags) was misdiagnosed multiple times as a
coding-style issue rather than the byte-level inline-substitution issue it
was. The recovery involved replacing the two corrupted tokens with the
correct tag bytes via `Path.read_bytes()` + `bytes.fromhex()`, scoped by a
unique JSON anchor (`{"name": "search_cases", "arguments": {"query": "art.
6.5 BW"}}`) so the four INTENTIONAL unbracketed 9-letter token references
in this file's docstrings were *not* touched. The diagnosis-and-fix sequence
took five rounds. Two later rounds of that trace were spent on the rules
below — each rule was a mistake the agent made that could have been avoided
with the rule it now specifies.

A few false starts preceded the correct diagnosis. In particular, an earlier
hypothesised cp1252 interpretation turned out to be a real but unrelated
UTF-8 em-dash sequence (`0xe2 0x80 0x94`) — a one-byte-overlap coincidence
that consumed two rounds before the actual byte-vs-render distinction
became visible. The five-round diagnosis sequence:

1. `str_replace` reported "no change" on what should have been a different
   old/new pair. Agent re-sent the same string with cosmetic variations
   for several rounds.
2. Agent theorised about cp1252 codepages + UTF-8 decode errors without
   byte-level evidence, investigating a real but unrelated em-dash sequence.
3. Agent eventually ran a Python heredoc that printed `repr(...)` of the
   affected bytes — that confirmed the corruption.
4. Agent then ran a byte-level `Path.read_bytes()` + `bytes.fromhex()`
   rewrite, scoped by a unique anchor to avoid collateral damage.
5. Agent added a breadcrumb comment in the test fixture pointing at this
   section.

Rules 1, 2, 3 below codify different compression points at which that
diagnosis could have collapsed to one round.

### Rule 1 — When a deterministic tool reports "no change" / "not found" non-deterministically, stop pattern-matching and **measure the bytes**.

**Trigger.** A deterministic tool (typically `str_replace`, `write_file`)
returns an unexpected-result failure — `"no change"`, `"old string not found"`,
`"ambiguous identifier"` — **once** on any input where there's a plausible
hypothesis that the tool is mis-rendering the input (i.e. a byte-vs-render
gap in front of the tool). Two failures on the same input is a STRONGER
signal but not necessary: one unexplained failure following a re-send with
cosmetic variations is enough.

**Banned moves after the first unexplained tool failure.**
- Re-sending the same string with cosmetic variations. The input reached
  the tool; the tool did not behave as expected. The cause is upstream of
  the tool, not in your input's formatting.
- Theorising about encoding layers (cp1252 vs UTF-8 vs JSON canonicalisation)
  without byte-level evidence. The agent that did this burned three rounds
  chasing an unrelated em-dash sequence before measuring the actual bytes.
- Asserting "no change" means "nothing to do". It means "old and new resolved
  to the same bytes after whatever layer sits in front of the tool; status
  quo is unchanged".

**Required next step.** `basher` a Python heredoc that prints `repr()` of the
actual bytes at the suspected location:

```bash
python -c "import re; print(repr(open('path/to/file', 'rb').read()[idx-50:idx+50]))"
```

If any character is suspicious, compare in HEX. *Only* retry with different
input **after** you have bytes confirming what the target really is — not
before.

### Rule 2 — When a function's gate-or-return contract changes, audit every test caller BEFORE the first `python -m pytest` run.

**Trigger.** A function's behavioural contract changes. Examples in this
codebase: `score_one()` had keyword + language gates added to its rubric
branch so non-NL/non-FR responses now zero the score; `keyword_coverage()`
had a gate-or-cap semantic change distinguishing its standalone-method call
from its rubric-call. Any future change to `judge.jl_logic` or
`stats.bilingual_accuracy_ratio` falls in the same category.

**It's not acceptable.** Run pytest, see failures, patch the failing tests,
run pytest, see more failures, patch those, repeat. That cycle ran three
rounds in this codebase when the rubric-but-not-gate audit could have caught
it in one pass.

**Required audit (5 minutes, before the first pytest run):**
1. Enumerate every test class that calls the function whose contract changed.
2. Brain-trace each test: with the new contract, what does the function
   return for the existing fixture inputs?
3. For tests whose fixtures no longer produce the documented expected
   outputs, rewrite the fixture BEFORE running pytest.
4. Now run pytest. Either your audit was right (no failures) or your audit
   was incomplete (the failures now tell you what you missed — usually
   one or two cases, not a long cascade).

### Rule 3 — When a fix is meant to normalise handling of edge case X, validate it against the minimum exercise case, not the original buggy data.

**Trigger.** A function's "buggy" data has a particular misalignment (e.g.
plural-vs-singular mismatch, encoding ambiguity, trailing whitespace) and
you're introducing a fix specifically for that misalignment.

**It's not acceptable.** Reuse the original buggy data as the test fixture
and expect the fix to bridge the gap. The test encodes the buggy
assumption it was meant to dismantle, then *correctly* fails for the
*right reason* while you debug it for the *wrong* one.

**Required fixture construction.** Write the fixture to be the
*minimum-required-to-exercise-X* case — for a plural-vs-singular fixer
that's the singular form; for an encoding fixer, the byte sequence that
demonstrates the encoding boundary. If the original buggy data additionally
exercises a separate path, keep both with distinct names: `test_<fix>_minimum`
for the minimum exercise case, `test_<fix>_realworld_corpus_case` for the
original data.
