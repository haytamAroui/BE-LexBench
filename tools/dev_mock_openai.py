# Copyright 2026 Haytam Aroui
# SPDX-License-Identifier: GPL-3.0-only
"""
Minimal mock OpenAI-compatible /v1/chat/completions endpoint.

Purpose: smoke-test be-lexbench end-to-end without a real model API.

Behaviour:
- Detects whether a request is a model call or a judge call by inspecting the
  user content (presence of `RUBRIC:` and `fabricated_citation` or
  `Score on a 0-4` indicates a judge request).
- For model calls: selects one of two Dutch/French canned Belgian-legal
  answers based on the question's language and topic.
- For judge calls: returns a raw JSON blob shaped like
  `{"score": 4, "rationale": "...", "fabricated_citation": false}`,
  matching what `_parse_judge_json` in harness/judge.py expects.

This is a DEV tool only — never use as a production endpoint.
"""

from __future__ import annotations
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        return

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_error(404, "use /v1/chat/completions")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            self.send_error(400, "malformed JSON body")
            return

        user_text = " ".join(
            m.get("content", "") for m in body.get("messages", [])
            if m.get("role") == "user"
        ).strip()
        request_model = body.get("model", "mock")

        # Judge detection — matches the JUDGE_TEMPLATE prelude in harness/judge.py
        is_judge = (
            "RUBRIC:" in user_text
            or "fabricated_citation" in user_text
            or "Score on a 0-4" in user_text
        )

        if is_judge:
            content = json.dumps({
                "score": 4,
                "rationale": "Correct court, correct constitutional basis, citations accurate.",
                "fabricated_citation": False,
            }, ensure_ascii=False)
        elif (
            "permis d'urbanisme" in user_text
            or "Conseil d" in user_text  # covers "Conseil d'État"
            or "C.C. n° 22/2025" in user_text
            or "Région flamande" in user_text
        ):
            content = (
                "Le Conseil d'État est exclusivement compétent pour le recours "
                "en annulation contre les permis d'urbanisme. Voir C.C. n° "
                "22/2025, ECLI:BE:GHCC:2025:ARR.22, sur la base de l'article "
                "160 de la Constitution."
            )
        elif (
            "Raad van State" in user_text
            or "Vlaams" in user_text
            or "GwH nr. 22/2025" in user_text
        ):
            content = (
                "De Raad van State is exclusief bevoegd voor het beroep tegen "
                "de stedenbouwkundige vergunning. Zie GwH nr. 22/2025, "
                "ECLI:BE:GHCC:2025:ARR.22, op grond van artikel 160 GW."
            )
        else:
            content = "I cannot answer this question."

        payload = {
            "id": "mock-completion-1",
            "object": "chat.completion",
            "model": request_model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        # charset=utf-8 is required: RFC 8259 leaves JSON's default charset
        # implicit, but real OpenAI-compatible clients (requests, openai-python,
        # httpx) all honour the declared charset here. Without it, default
        # code paths can decode FR/NL multi-byte sequences as ISO-8859-1 or
        # Latin-1, producing U+FFFD that hides in transit before the harness
        # ever sees it.
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    addr = ("127.0.0.1", port)
    httpd = HTTPServer(addr, Handler)
    print(
        f"[mock-openai] listening on http://{addr[0]}:{addr[1]}/v1/chat/completions",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("[mock-openai] shutting down", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
