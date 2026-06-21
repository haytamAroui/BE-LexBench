#!/usr/bin/env python3
# Copyright 2026 Haytam Aroui
# SPDX-License-Identifier: GPL-3.0-only
"""
be-lexbench runner.

Run one model over a be-lexbench item set, score every item, and write a
publication-shaped summary with per-track means + 95% bootstrap CIs.

Resumable: per-item results are appended to a JSONL as they complete, so a
re-run skips already-scored items.

Usage:
  python -m harness.run_eval \
    --items your_items.jsonl \
    --model '{"kind":"openai_compat","model_name":"your-model-name","base_url":"http://localhost:8000/v1"}' \
    --run-id your-model-v1 \
    --judge '{"kind":"anthropic","model_name":"claude-sonnet-4-6","api_key_env":"ANTHROPIC_API_KEY"}' \
    --out-dir ./results

Notes:
  * --model and --judge take a JSON client spec (see harness/models.py, build_client).
  * Greedy decoding (temperature 0) by default — the fairness protocol default.
  * The judge spec is optional; without it, rubric items are left unscored and
    flagged, and only programmatic tracks produce final numbers.
  * The canonical judge for comparable scores is claude-sonnet-4-6 (see
    docs/methodology.md §5.2); any judge may be used for self-evaluation.
  * Pass --judge twice (or a JSON list) to use a judge ENSEMBLE.

File-encoding invariant (READ THIS BEFORE OPENING A FILE IN THIS MODULE)
------------------------------------------------------------------------
On Windows, `locale.getpreferredencoding()` returns "cp1252" by default. Every
`open()` in this module therefore specifies `encoding="utf-8"` explicitly.
Without this, FR/NL legal characters (É, °, ï, ...) get encoded as single
cp1252 bytes (0xc9, 0xb0, 0xef) by Python's file writer and on every subsequent
UTF-8 read they re-render as U+FFFD — corrupting the published items.jsonl.
On Linux/macOS where UTF-8 is the platform default, the explicit encoding kwarg
is harmless and keeps behaviour identical across OSes. The same rule applies
to any future contributor adding a file open() to this module.
"""

from __future__ import annotations
import argparse
import asyncio
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Optional, Any

from . import models as M
from . import scorers as S
from . import judge as J
from . import stats as ST

# Setup logger for the run_eval module
logger = logging.getLogger("be-lexbench")

# Schema path relative to the package root (cblre-main/schema/).
_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "schema", "eval_item.schema.json")


class AsyncRateLimiter:
    """Delay-based rate limiter for API requests."""
    def __init__(self, requests_per_minute: Optional[float] = None):
        self.rpm = requests_per_minute
        self.delay = 60.0 / requests_per_minute if requests_per_minute else 0.0
        self.last_call = 0.0
        self.lock = asyncio.Lock()

    async def wait(self) -> None:
        if not self.rpm:
            return
        async with self.lock:
            now = time.time()
            elapsed = now - self.last_call
            to_wait = self.delay - elapsed
            if to_wait > 0:
                await asyncio.sleep(to_wait)
                self.last_call = time.time()
            else:
                self.last_call = now


def _validate_items(items: list[dict]) -> None:
    """Validate items against eval_item.schema.json if jsonschema is installed.

    Catches malformed items (missing scoring.method, invalid track, etc.) at
    load time rather than mid-run inside score_one(). If jsonschema is not
    installed, prints a one-time warning and returns — the harness still runs,
    just without upfront validation.
    """
    try:
        import jsonschema
    except ImportError:
        logger.warning("[run] jsonschema not installed — skipping item validation. "
                       "Install with: pip install jsonschema")
        return
    if not os.path.exists(_SCHEMA_PATH):
        logger.warning(f"[run] schema file not found at {_SCHEMA_PATH} — skipping validation")
        return
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    for i, item in enumerate(items):
        try:
            jsonschema.validate(item, schema)
        except jsonschema.ValidationError as e:
            raise ValueError(
                f"Item {i} (id={item.get('id', '???')}) failed schema validation: "
                f"{e.message}"
            ) from e
    logger.info(f"[run] {len(items)} items validated against schema")


def _generate_with_retry(client: Any, prompt: str, *, system: Optional[str] = None,
                         context: Optional[Any] = None, tools: Optional[list] = None,
                         max_tokens: int = 512, temperature: float = 0.0,
                         max_attempts: int = 3, backoff_base: float = 2.0) -> Any:
    """Wrap client.generate() with exponential backoff for transient failures.

    Catches network errors, timeouts, and server-side failures (5xx). On the
    final attempt, re-raises the exception so the caller can decide whether
    to crash or skip. Logs retries to stderr so the run log explains delays.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return client.generate(
                prompt, system=system, context=context, tools=tools,
                max_tokens=max_tokens, temperature=temperature,
            )
        except Exception as e:
            if attempt == max_attempts:
                raise
            wait = backoff_base ** (attempt - 1)
            logger.warning(
                f"[retry] attempt {attempt}/{max_attempts} failed: "
                f"{type(e).__name__}: {e}. Retrying in {wait:.0f}s..."
            )
            time.sleep(wait)


def load_items(path: str) -> list[dict]:
    items = []
    # encoding="utf-8" is REQUIRED, not optional: on Windows the default
    # encoding is the active console codepage (usually cp1252), which encodes
    # FR/NL legal text (É, °, ï, …) as single bytes that then re-render as
    # U+FFFD when the file is later read as UTF-8. Every open() in this
    # module spells the encoding out explicitly to keep behaviour identical
    # across Linux/macOS/Windows. Same note applies to all open() sites below.
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def load_done(results_path: str) -> set:
    done = set()
    if os.path.exists(results_path):
        with open(results_path, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["id"])
                except Exception:
                    pass
    return done


def score_one(item: dict, response: str, judge_clients: list) -> dict:
    """Score one item end-to-end. Gate order, gate semantics, and per-row status surface:

    Rubric path (``method = 'rubric'``):
      1. **Keyword gate** via ``S.PROGRAMMATIC['keyword_coverage']`` — fires
         BEFORE the judge on cross-track contamination (e.g. a civil-law item
         mentioning forbidden article 1382 BW). On fire: ``final_score=0.0``,
         ``judge.status='KEYWORD_GATE_FAILED'``, ``judge.reason`` carries the
         ``keyword_coverage.detail`` (missing required / present forbidden).
      2. **Language gate** via ``S.PROGRAMMATIC['language_adherence']`` —
         fires BEFORE the judge on wrong-language response. On fire:
         ``final_score=0.0``, ``judge.status='LANGUAGE_GATE_FAILED'``.
      3. **Judge pass** via ``J.judge_item`` — only runs if both gates pass AND
         a judge is configured. ``final_score=jr['score01']``.
      4. If both gates pass but no judge is configured:
         ``final_score=None``, ``judge.status='NO_JUDGE_CONFIGURED'``.

    Non-rubric path (mcq_exact / language_adherence / citation_validity /
    keyword_coverage / refusal / tool_call):
      * The single programmatic scorer runs first.
      * If ``prog['needs_judge']`` is True:
        - The Keyword Gate runs first (if method != keyword_coverage) to catch
          contamination before the judge.
        - The Language Gate runs next (if method != language_adherence) to catch
          wrong language before the judge.
        - On gate failure: ``final_score=0.0``, LLM judge is skipped.
        - On pass, if a judge is configured, the final-score rule per method:
          - ``method='keyword_coverage'``: gate cap wins — if
            ``prog['score']==0.0``, ``final_score=0.0`` (judge can run but
            cap holds); on pass, ``final_score = jr['score01']``.
          - ``method='tool_call'``: ``final_score = prog['score'] +
            0.5*jr['score01']`` (intent score from prog, quality from judge).
          - ``method='refusal'``: ``final_score = prog['score']`` (binary
            correctness; judge annotates quality but does not change the
            score).
          - else (mcq_exact, language_adherence, citation_validity):
            ``final_score = jr['score01']``.
      * If ``prog['needs_judge']`` is True but no judge is configured:
        refusal/tool_call keep their partial programmatic score and the
        ``judge.status`` notes ``NO_JUDGE_CONFIGURED_quality_unscored``;
        everything else returns ``final_score=None``.

    Gate semantics live HERE, not in ``scorers.keyword_coverage``. The scorer
    is a 0/1 detector; whether that 0.0 is a hard cap depends on this
    function's branch logic. See ``docs/real_cases/gwh_022_2025_run_results.md``
    §9 + ``docs/real_cases/gwh_022_2025_e2e_walkthrough.md`` §6 for the
    failure-mode tables the gate order implements.
    """
    method = item["scoring"]["method"]

    # Rubric items are scored by the LLM judge, BUT the two hard gates (keyword
    # coverage -> wrong-keyword failure, language adherence -> wrong-language
    # failure) ZERO the score BEFORE the judge is consulted. This matches the
    # rubric anchor (fabricated citation = cap at 0) — gates are first-class
    # caps regardless of item format. See docs/real_cases/... §9 + docs
    # walkthrough §6: these are the cross-track contamination + wrong-language
    # gates the docs already promise.
    if method == "rubric":
        kw = S.PROGRAMMATIC["keyword_coverage"](response, item)
        if kw["score"] == 0.0:
            return {"programmatic": {"keyword_coverage": kw, "language_adherence": None},
                    "judge": {"status": "KEYWORD_GATE_FAILED",
                              "reason": kw["detail"]},
                    "final_score": 0.0}
        la = S.PROGRAMMATIC["language_adherence"](response, item)
        if la["score"] == 0.0:
            return {"programmatic": {"keyword_coverage": None, "language_adherence": la},
                    "judge": {"status": "LANGUAGE_GATE_FAILED",
                              "reason": la["detail"]},
                    "final_score": 0.0}
        if not judge_clients:
            return {"programmatic": {"keyword_coverage": None, "language_adherence": None},
                    "judge": {"status": "NO_JUDGE_CONFIGURED"},
                    "final_score": None}
        jr = J.judge_item(item, response, judge_clients)
        return {"programmatic": {"keyword_coverage": None, "language_adherence": None},
                "judge": jr, "final_score": jr["score01"]}

    prog = S.PROGRAMMATIC[method](response, item)
    result = {"programmatic": prog, "judge": None, "final_score": prog["score"]}

    if prog.get("needs_judge"):
        # Run Keyword Gate if item format is open (unless this method IS keyword_coverage, which we already ran)
        if item.get("format") == "open" and method != "keyword_coverage":
            kw = S.PROGRAMMATIC["keyword_coverage"](response, item)
            if kw["score"] == 0.0:
                result["judge"] = {"status": "KEYWORD_GATE_FAILED", "reason": kw["detail"]}
                result["final_score"] = 0.0
                return result

        # Run Language Gate if item format is open (unless this method IS language_adherence or tool_call)
        if item.get("format") == "open" and method != "language_adherence" and method != "tool_call":
            la = S.PROGRAMMATIC["language_adherence"](response, item)
            if la["score"] == 0.0:
                result["judge"] = {"status": "LANGUAGE_GATE_FAILED", "reason": la["detail"]}
                result["final_score"] = 0.0
                return result

        if judge_clients:
            jr = J.judge_item(item, response, judge_clients)
            result["judge"] = jr
            if jr["score01"] is not None:
                # For open/rubric items the judge sets the final score. For gated
                # programmatic methods (keyword/tool/refusal) combine: a hard gate
                # failure stays 0; otherwise the judge score governs quality.
                if method in ("keyword_coverage",) and prog["score"] == 0.0:
                    result["final_score"] = 0.0  # required-term gate failed
                elif method == "tool_call":
                    # name match (prog 0.5) + judged arg quality (other 0.5)
                    result["final_score"] = prog["score"] + 0.5 * jr["score01"]
                elif method == "refusal":
                    # refusal correctness is binary; judge only annotates quality
                    result["final_score"] = prog["score"]
                else:
                    result["final_score"] = jr["score01"]
        elif not judge_clients:
            # No judge available. For methods whose PROGRAMMATIC score is authoritative
            # (refusal correctness is binary; tool_call name-match is a real partial score),
            # keep the programmatic score and note the judge was skipped (quality unscored).
            if method in ("refusal", "tool_call"):
                result["final_score"] = prog["score"]
                result["judge"] = {"status": "NO_JUDGE_CONFIGURED_quality_unscored"}
            else:
                result["final_score"] = None  # genuinely cannot finalize without a judge
                result["judge"] = {"status": "NO_JUDGE_CONFIGURED"}
    return result


async def run_async(
    args: argparse.Namespace,
    client: M.ModelClient,
    judge_clients: list[M.ModelClient],
    items: list[dict],
    done: set[str],
    results_path: str,
) -> None:
    sem = asyncio.Semaphore(args.concurrency)
    rate_limiter = AsyncRateLimiter(args.rpm)
    write_lock = asyncio.Lock()

    with open(results_path, "a", encoding="utf-8") as out:
        async def process_item(it: dict) -> None:
            if it["id"] in done:
                return
            async with sem:
                await rate_limiter.wait()
                prompt = it["prompt"]
                if it.get("format") == "mcq" and it.get("choices"):
                    prompt = (prompt.rstrip() + "\n" + "\n".join(it["choices"])
                              + "\n\nAnswer with ONLY the letter of the correct option.")
                gen = await asyncio.to_thread(
                    _generate_with_retry,
                    client, prompt, system=it.get("system"),
                    context=it.get("context"), tools=it.get("tools"),
                    max_tokens=args.max_tokens, temperature=args.temperature,
                )
                scored = await asyncio.to_thread(score_one, it, gen.text, judge_clients)
                row = {
                    "id": it["id"], "track": it["track"], "language": it["language"],
                    "difficulty": it["difficulty"], "parity_group": it.get("parity_group"),
                    "response": gen.text, "latency_s": round(gen.latency_s, 2),
                    "score": scored["final_score"], "scoring_method": it["scoring"]["method"],
                    "programmatic": scored["programmatic"], "judge": scored["judge"],
                    "canary": it["provenance"]["canary"],
                }
                async with write_lock:
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    out.flush()
                    ss = "?" if scored["final_score"] is None else f"{scored['final_score']:.2f}"
                    logger.info(f"  [{it['id']:<28}] {it['track']:<22} score={ss}")

        tasks = [process_item(it) for it in items]
        await asyncio.gather(*tasks)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--model", required=True, help="JSON client spec")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--judge", action="append", default=[],
                    help="JSON client spec; repeat for an ensemble")
    ap.add_argument("--out-dir", default="./results")
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--concurrency", type=int, default=1, help="Max concurrent model calls")
    ap.add_argument("--rpm", "--requests-per-minute", type=float, default=None, help="Rate limit in requests per minute")
    args = ap.parse_args()

    # Configure logging
    logging.basicConfig(level=logging.WARNING)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False

    out_dir = os.path.join(args.out_dir, args.run_id)
    os.makedirs(out_dir, exist_ok=True)
    results_path = os.path.join(out_dir, "items.jsonl")
    summary_path = os.path.join(out_dir, "summary.json")

    items = load_items(args.items)
    _validate_items(items)
    done = load_done(results_path)
    logger.info(f"[run] {len(items)} items, {len(done)} already done")

    client = M.build_client(json.loads(args.model))
    judge_clients = [M.build_client(json.loads(j)) for j in args.judge]
    if not judge_clients:
        logger.warning("[run] no judge configured — rubric items will be unscored")

    asyncio.run(run_async(args, client, judge_clients, items, done, results_path))

    aggregate(results_path, summary_path, args.run_id,
              json.loads(args.model), [json.loads(j) for j in args.judge])
    logger.info(f"[run] summary -> {summary_path}")


def aggregate(results_path: str, summary_path: str, run_id: str, model_spec: dict, judge_specs: list[dict]) -> None:
    with open(results_path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    by_track = defaultdict(list)
    lang_acc: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))   # track -> lang -> scores
    diff_acc: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))   # track -> difficulty -> scores
    unscored = 0
    for r in rows:
        if r["score"] is None:
            unscored += 1
            continue
        by_track[r["track"]].append(r["score"])
        lang_acc[r["track"]][r["language"]].append(r["score"])
        diff_acc[r["track"]][r["difficulty"]].append(r["score"])

    tracks = {}
    for tr, scores in sorted(by_track.items()):
        entry = ST.bootstrap_ci(scores)
        # difficulty breakdown
        entry["by_difficulty"] = {
            d: ST.bootstrap_ci(v) for d, v in sorted(diff_acc[tr].items())
        }
        tracks[tr] = entry

    # Track-1 parity headline (and any track with both languages present)
    parity = {}
    for tr in by_track:
        nl = lang_acc[tr].get("nl", [])
        fr = lang_acc[tr].get("fr", [])
        en = lang_acc[tr].get("en", [])
        if nl and fr:
            parity[tr] = {
                "nl_acc_pct": round(100 * mean(nl), 2),
                "fr_acc_pct": round(100 * mean(fr), 2),
                **ST.bilingual_accuracy_ratio(mean(fr), mean(nl), "fr", "nl"),
                "n_nl": len(nl), "n_fr": len(fr),
            }
        elif en and fr:
            parity[tr] = {
                "en_acc_pct": round(100 * mean(en), 2),
                "fr_acc_pct": round(100 * mean(fr), 2),
                **ST.bilingual_accuracy_ratio(mean(fr), mean(en), "fr", "en"),
                "n_en": len(en), "n_fr": len(fr),
            }

    summary = {
        "run_id": run_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model_spec": model_spec,
        "judge_specs": judge_specs,
        "n_items": len(rows),
        "n_unscored_no_judge": unscored,
        "tracks": tracks,
        "bilingual_parity": parity,
        "note": "Seed run. Items require SME validation before these numbers are publishable (see docs/methodology.md §0).",
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
