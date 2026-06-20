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
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

from statistics import mean

from . import models as M
from . import scorers as S
from . import judge as J
from . import stats as ST

# Schema path relative to the package root (cblre-main/schema/).
_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "schema", "eval_item.schema.json")


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
        print("[run] WARNING: jsonschema not installed — skipping item validation. "
              "Install with: pip install jsonschema")
        return
    if not os.path.exists(_SCHEMA_PATH):
        print(f"[run] WARNING: schema file not found at {_SCHEMA_PATH} — skipping validation")
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
    print(f"[run] {len(items)} items validated against schema")


def _generate_with_retry(client, prompt, *, system=None, context=None,
                         tools=None, max_tokens=512, temperature=0.0,
                         max_attempts=3, backoff_base=2.0):
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
            print(
                f"[retry] attempt {attempt}/{max_attempts} failed: "
                f"{type(e).__name__}: {e}. Retrying in {wait:.0f}s...",
                file=sys.stderr,
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
      * If ``prog['needs_judge']`` is True AND a judge is configured, the
        final-score rule per method:
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
    if prog.get("needs_judge") and judge_clients:
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
    elif prog.get("needs_judge") and not judge_clients:
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--model", required=True, help="JSON client spec")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--judge", action="append", default=[],
                    help="JSON client spec; repeat for an ensemble")
    ap.add_argument("--out-dir", default="./results")
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--temperature", type=float, default=0.0)
    args = ap.parse_args()

    out_dir = os.path.join(args.out_dir, args.run_id)
    os.makedirs(out_dir, exist_ok=True)
    results_path = os.path.join(out_dir, "items.jsonl")
    summary_path = os.path.join(out_dir, "summary.json")

    items = load_items(args.items)
    _validate_items(items)
    done = load_done(results_path)
    print(f"[run] {len(items)} items, {len(done)} already done")

    client = M.build_client(json.loads(args.model))
    judge_clients = [M.build_client(json.loads(j)) for j in args.judge]
    if not judge_clients:
        print("[run] WARNING: no judge configured — rubric items will be unscored")

    with open(results_path, "a", encoding="utf-8") as out:
        for it in items:
            if it["id"] in done:
                continue
            # MCQ items must present the options to the model and constrain the
            # answer to a letter — otherwise the model answers in prose and there
            # is no letter to score. Applied identically to every model (format
            # protocol, not a content change).
            prompt = it["prompt"]
            if it.get("format") == "mcq" and it.get("choices"):
                prompt = (prompt.rstrip() + "\n" + "\n".join(it["choices"])
                          + "\n\nAnswer with ONLY the letter of the correct option.")
            gen = _generate_with_retry(
                client, prompt, system=it.get("system"),
                context=it.get("context"), tools=it.get("tools"),
                max_tokens=args.max_tokens, temperature=args.temperature,
            )
            scored = score_one(it, gen.text, judge_clients)
            row = {
                "id": it["id"], "track": it["track"], "language": it["language"],
                "difficulty": it["difficulty"], "parity_group": it.get("parity_group"),
                "response": gen.text, "latency_s": round(gen.latency_s, 2),
                "score": scored["final_score"], "scoring_method": it["scoring"]["method"],
                "programmatic": scored["programmatic"], "judge": scored["judge"],
                "canary": it["provenance"]["canary"],
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            ss = "?" if scored["final_score"] is None else f"{scored['final_score']:.2f}"
            print(f"  [{it['id']:<28}] {it['track']:<22} score={ss}")

    aggregate(results_path, summary_path, args.run_id,
              json.loads(args.model), [json.loads(j) for j in args.judge])
    print(f"[run] summary -> {summary_path}")


def aggregate(results_path, summary_path, run_id, model_spec, judge_specs):
    with open(results_path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    by_track = defaultdict(list)
    lang_acc = defaultdict(lambda: defaultdict(list))   # track -> lang -> scores
    diff_acc = defaultdict(lambda: defaultdict(list))   # track -> difficulty -> scores
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
