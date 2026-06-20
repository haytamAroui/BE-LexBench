# Quickstart — run your first be-lexbench evaluation in 5 minutes

This guide walks through installing the harness, running it against the synthetic sample items with a local or hosted model, and reading the output. No item bank access is required.

---

## 1. Install

```bash
# Local development checkout:
git clone https://github.com/BE-LexBench/be-lexbench.git && cd be-lexbench
pip install -e .
```

Verify the install:

```bash
be-lexbench --help
```

---

## 2. Get the sample items

The sample items live at `data/sample/sample.jsonl`. Copy it to a working path:

```bash
cp data/sample/sample.jsonl /tmp/sample.jsonl
```

---

## 3. Run evaluation — programmatic tracks only (no judge needed)

Point the harness at any OpenAI-compatible endpoint:

```bash
be-lexbench \
  --items /tmp/sample.jsonl \
  --model '{"kind":"openai_compat","model_name":"your-model-name","base_url":"http://localhost:8000/v1"}' \
  --run-id quickstart-test \
  --out-dir ./results
```

For a **hosted model** (e.g. GPT-4o via OpenAI):

```bash
export OPENAI_API_KEY=sk-...

be-lexbench \
  --items /tmp/sample.jsonl \
  --model '{"kind":"openai_compat","model_name":"gpt-4o","base_url":"https://api.openai.com/v1","api_key_env":"OPENAI_API_KEY"}' \
  --run-id gpt4o-quickstart \
  --out-dir ./results
```

---

## 4. Add the canonical judge for rubric-scored items

Open-ended (`format: open`) items require an LLM judge. The canonical judge is Claude Sonnet 4.6:

```bash
export ANTHROPIC_API_KEY=sk-ant-...

be-lexbench \
  --items /tmp/sample.jsonl \
  --model '{"kind":"openai_compat","model_name":"your-model-name","base_url":"http://localhost:8000/v1"}' \
  --judge '{"kind":"anthropic","model_name":"claude-sonnet-4-6","api_key_env":"ANTHROPIC_API_KEY"}' \
  --run-id quickstart-with-judge \
  --out-dir ./results
```

---

## 5. Read the results

Results are written to `./results/<run-id>/`:

```
results/quickstart-test/
  items.jsonl    # one row per item: response, latency, scores
  summary.json   # per-track means with 95% bootstrap CIs
```

Inspect the summary:

```bash
python -c "import json; s=json.load(open('results/quickstart-test/summary.json')); print(json.dumps(s['tracks'], indent=2))"
```

The run is **resumable**: if it is interrupted, re-running the same command skips already-scored items and continues from where it left off.
