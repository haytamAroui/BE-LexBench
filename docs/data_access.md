# Requesting the be-lexbench Evaluation Set

## What is gated

The following are not published in this repository:

- The full item bank (currently expert-reviewed items in the validation set; SME validation ongoing)
- Gold answers and scoring keys
- The held-out scoring split used for official evaluation

Only a small set of **synthetic illustrative items** in `data/sample/` is published here, clearly labeled as non-scoring.

## Why gated

Benchmark contamination — models trained on test items before evaluation — is a documented and growing problem in LLM evaluation. Publishing only the harness and methodology while gating the item bank means:

1. Evaluators can inspect and audit the full scoring logic
2. Models cannot be trained on items prior to evaluation
3. Official scoring on the held-out split preserves the instrument's integrity over multiple leaderboard refreshes

## How to request access

Open an [Evaluation Set Access Request](https://github.com/BE-LexBench/be-lexbench/issues/new?template=access-request.yml) on this repository's issue tracker.

## Self-evaluation with your own items

If you want to test the harness before requesting official evaluation, you can:

1. Install the harness from local source or repository
2. Write items conforming to [`schema/eval_item.schema.json`](../schema/eval_item.schema.json)
3. Run `be-lexbench --items your_items.jsonl ...` (or `python -m harness.run_eval --items your_items.jsonl ...`)
4. Inspect the per-item output and summary

## Timeframe and contact

Access requests and data license questions are handled through the [repository issue tracker](https://github.com/BE-LexBench/be-lexbench/issues).
