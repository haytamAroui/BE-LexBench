# Copyright 2026 Haytam Aroui
# SPDX-License-Identifier: GPL-3.0-only
"""
be-lexbench model adapters.

Every model — the author's and every competitor — goes through one of these
clients under identical conditions (greedy decode by default, identical prompts).
Per-model adaptation is limited to *format* (chat template, tool-call shape) and
must be documented; never change item content.

Client kinds (use as --model / --judge JSON specs):
  hf_local          : a local Hugging Face / transformers checkpoint
  openai_compat     : any server speaking /v1/chat/completions
                      (your-model serve_openai.py, vLLM, OpenAI GPT-4o, Together,
                      Groq, Fireworks, OpenRouter, ...)
  anthropic         : Claude via the native Anthropic API — CANONICAL JUDGE
                      (claude-sonnet-4-6; needs only ANTHROPIC_API_KEY)
  vertex_anthropic  : the same Claude models via Google Vertex AI, for teams
                      already on GCP — same model, so judge scores stay comparable

A "completion" is the assistant's text. Tool-call items additionally expose the
raw text so the track-9 scorer can parse whatever format the model emitted.
"""

from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class GenResult:
    text: str
    raw: dict = field(default_factory=dict)
    model_id: str = ""
    latency_s: float = 0.0


class ModelClient:
    """Abstract client. Subclasses implement .generate()."""

    model_id: str = "unknown"

    def generate(self, prompt: str, system: Optional[str] = None,
                 context: Optional[Any] = None, tools: Optional[list] = None,
                 max_tokens: int = 512, temperature: float = 0.0) -> GenResult:
        raise NotImplementedError

    @staticmethod
    def _build_messages(prompt, system, context):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if context:
            ctx = "\n\n".join(str(c) for c in context) if isinstance(context, list) else str(context)
            messages.append({"role": "system", "content": f"Context:\n{ctx}"})
        messages.append({"role": "user", "content": prompt})
        return messages

    @staticmethod
    def _build_system_and_user(prompt, system, context):
        """For Messages-API providers (Anthropic/Vertex): system is a separate
        top-level field, not a message. Returns (system_str_or_None, user_str)."""
        sys_parts = []
        if system:
            sys_parts.append(system)
        if context:
            ctx = "\n\n".join(str(c) for c in context) if isinstance(context, list) else str(context)
            sys_parts.append(f"Context:\n{ctx}")
        return ("\n\n".join(sys_parts) if sys_parts else None), prompt

    @staticmethod
    def _openai_tools_to_anthropic(tools):
        out = []
        for t in tools or []:
            fn = t.get("function", t)
            out.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return out


class HFLocalClient(ModelClient):
    """
    Local transformers checkpoint. Handles the Qwen3.5 'thinking mode' quirk:
    enable_thinking=False is passed to the chat template so reasoning scaffolds
    do not leak into the scored output. For a model whose template does not
    accept enable_thinking, set thinking_kw=None.
    """

    def __init__(self, model_path: str, device: str = "cuda:0",
                 thinking_kw: Optional[str] = "enable_thinking",
                 adapter: Optional[str] = None):
        import torch
        self.torch = torch
        self.model_id = os.path.basename(model_path.rstrip("/"))
        self.thinking_kw = thinking_kw

        from transformers import (AutoModelForImageTextToText,
                                   AutoModelForCausalLM, AutoTokenizer)
        common = dict(dtype=torch.bfloat16, device_map=device,
                      trust_remote_code=True, low_cpu_mem_usage=True,
                      attn_implementation="sdpa")
        # Prefer the image-text class so vision-bearing checkpoints keep their
        # vision tower. Text-only checkpoints carry a text-only config that this
        # class rejects — fall back to the causal-LM class so the harness
        # runs on any checkpoint, vision or not.
        try:
            self.model = AutoModelForImageTextToText.from_pretrained(model_path, **common).eval()
            self.is_vision = True
        except (ValueError, KeyError) as e:
            print(f"[hf] {self.model_id}: not image-text ({type(e).__name__}); "
                  f"loading as text-only causal LM")
            self.model = AutoModelForCausalLM.from_pretrained(model_path, **common).eval()
            self.is_vision = False

        # Optional PEFT adapter on top of the base — lets the harness benchmark
        # an adapter BEFORE you merge it, which is the safe gate before merging.
        # If loading fails, raise loudly: a silently-skipped adapter would mean
        # benchmarking the base under the adapter's run-id, giving false "no
        # improvement" readings. Better to crash than to mislead.
        if adapter:
            from peft import PeftModel
            print(f"[hf] applying PEFT adapter: {adapter}")
            self.model = PeftModel.from_pretrained(self.model, adapter)
            self.model.eval()
            self.model_id = f"{self.model_id}+{os.path.basename(adapter.rstrip('/'))}"

        self.tok = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        self.device = device

    def generate(self, prompt, system=None, context=None, tools=None,
                 max_tokens=512, temperature=0.0) -> GenResult:
        messages = self._build_messages(prompt, system, context)
        tmpl_kwargs = dict(add_generation_prompt=True, return_tensors="pt", return_dict=True)
        if self.thinking_kw:
            tmpl_kwargs[self.thinking_kw] = False
        if tools:
            tmpl_kwargs["tools"] = tools
        t0 = time.time()
        try:
            enc = self.tok.apply_chat_template(messages, **tmpl_kwargs)
        except TypeError:
            tmpl_kwargs.pop("tools", None)
            tmpl_kwargs.pop(self.thinking_kw, None)
            enc = self.tok.apply_chat_template(messages, **tmpl_kwargs)
        enc = {k: v.to(self.device) for k, v in enc.items()}
        ilen = enc["input_ids"].shape[1]
        gen_kwargs = dict(max_new_tokens=max_tokens, do_sample=temperature > 0,
                          pad_token_id=self.tok.eos_token_id)
        if temperature > 0:
            gen_kwargs["temperature"] = temperature
        with self.torch.inference_mode():
            out = self.model.generate(**enc, **gen_kwargs)
        text = self.tok.decode(out[0][ilen:], skip_special_tokens=True)
        return GenResult(text=text.strip(), model_id=self.model_id, latency_s=time.time() - t0)


class OpenAICompatClient(ModelClient):
    """Any OpenAI-compatible /v1/chat/completions endpoint.

    Reasoning / thinking models
    ---------------------------
    Some models have a "thinking mode" that routes the answer through a separate
    reasoning field and leaves message.content null.  The harness detects this and
    warns; the fix depends on the model family:

    Qwen3 family (toggleable thinking via vLLM):
      Add "chat_template_kwargs": {"enable_thinking": false} to the model spec.
      This is injected at the top level of the raw request body — not under
      extra_body, which is an OpenAI Python SDK abstraction; we use requests.post
      directly so the field goes straight in the body (proven by curl against vLLM).

    DeepSeek-R1 / QwQ / always-on reasoning models:
      thinking cannot be disabled via chat_template_kwargs.  However, the harness
      is designed for this: mcq_exact uses a final-committed-answer strategy that
      works correctly on chain-of-thought output.  What matters is that vLLM's
      --reasoning-parser is configured so the model's answer appears in
      message.content (not only in reasoning_content).  If content is still null,
      adjust the vLLM serving config rather than the model spec.

    Non-thinking models (GPT-4o, Llama, Mistral, hosted APIs):
      Leave chat_template_kwargs unset (default None).  Sending a vLLM-specific
      field to hosted endpoints risks a 400 from strict servers.

    chat_template_kwargs defaults to None (opt-in, safe for all targets).
    """

    def __init__(self, model_name: str, base_url: str,
                 api_key: Optional[str] = None, send_tools: bool = True,
                 chat_template_kwargs: Optional[dict] = None):
        self.model_id = model_name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.send_tools = send_tools
        self.chat_template_kwargs = chat_template_kwargs

    def generate(self, prompt, system=None, context=None, tools=None,
                 max_tokens=512, temperature=0.0) -> GenResult:
        import sys
        import requests
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        def _post(msgs, send_tools):
            body = {"model": self.model_id, "messages": msgs,
                    "max_tokens": max_tokens, "temperature": temperature, "stream": False}
            if tools and self.send_tools and send_tools:
                body["tools"] = tools
            # chat_template_kwargs at the top level — vLLM raw requests path;
            # NOT nested under extra_body (that is the OpenAI Python SDK abstraction).
            if self.chat_template_kwargs is not None:
                body["chat_template_kwargs"] = self.chat_template_kwargs
            return requests.post(f"{self.base_url}/chat/completions",
                                 headers=headers, json=body, timeout=300)

        messages = self._build_messages(prompt, system, context)
        t0 = time.time()
        r = _post(messages, send_tools=True)
        if r.status_code == 400 and tools and self.send_tools:
            # vLLM rejected the tools param for this model. Retry without it,
            # folding the tool schema into the prompt so the model can still
            # emit a <tool_call> that the tool_call scorer reads.
            tool_desc = json.dumps(tools, ensure_ascii=False)
            aug = (prompt + "\n\nYou have access to the following tools (emit a "
                   "<tool_call>{...}</tool_call> JSON block to call one):\n" + tool_desc)
            messages = self._build_messages(aug, system, context)
            r = _post(messages, send_tools=False)
        r.raise_for_status()
        data = r.json()
        msg = data["choices"][0]["message"]
        text = msg.get("content") or ""

        # Harden: detect thinking-mode leakage — reasoning-mode models may route their
        # answer through a reasoning_content / reasoning field and leave content null.
        # We never read the reasoning text as the answer; scoring empty is correct.
        # Emit a diagnostic so the run log makes the root cause obvious.
        if not text:
            for reasoning_key in ("reasoning_content", "reasoning", "thinking"):
                if msg.get(reasoning_key):
                    print(
                        f"[be-lexbench] WARNING: message.content is null/empty but "
                        f"'{reasoning_key}' is present.\n"
                        f"  Qwen3 family: add \"chat_template_kwargs\": "
                        f"{{\"enable_thinking\": false}} to your --model spec.\n"
                        f"  DeepSeek-R1 / QwQ: check that vLLM's --reasoning-parser "
                        f"is routing the final answer into message.content.\n"
                        f"  Scoring this item as empty answer.",
                        file=sys.stderr,
                    )
                    break

        if msg.get("tool_calls"):
            text = (text + "\n" + json.dumps(msg["tool_calls"])).strip()
        return GenResult(text=text, raw=data, model_id=self.model_id, latency_s=time.time() - t0)


class AnthropicClient(ModelClient):
    """Native Anthropic API (api.anthropic.com). Works with any model available
    via api.anthropic.com. Auth via ANTHROPIC_API_KEY or explicit api_key."""

    def __init__(self, model_name: str, api_key: Optional[str] = None):
        import anthropic
        self.model_id = model_name
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def generate(self, prompt, system=None, context=None, tools=None,
                 max_tokens=512, temperature=0.0) -> GenResult:
        sys_str, user_str = self._build_system_and_user(prompt, system, context)
        kwargs = dict(
            model=self.model_id,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": user_str}],
        )
        if sys_str:
            kwargs["system"] = sys_str
        if tools:
            kwargs["tools"] = self._openai_tools_to_anthropic(tools)
        t0 = time.time()
        msg = self.client.messages.create(**kwargs)
        text_parts = []
        for block in msg.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(block.text)
            elif getattr(block, "type", None) == "tool_use":
                text_parts.append(
                    "<tool_call>"
                    + json.dumps({"name": block.name, "arguments": block.input})
                    + "</tool_call>"
                )
        return GenResult(text="\n".join(text_parts).strip(),
                         raw={"id": getattr(msg, "id", ""),
                              "model": getattr(msg, "model", "")},
                         model_id=self.model_id, latency_s=time.time() - t0)


class VertexAnthropicClient(ModelClient):
    """
    Claude via Google Vertex AI (anthropic[vertex]). Alternative access path to
    the canonical judge for teams already on GCP — same model as the native
    Anthropic API, so judge scores remain comparable. Can also benchmark Claude
    models as competitors.

    Auth: Application Default Credentials. On a GCP VM this is the attached
    service account (needs roles/aiplatform.user); off-VM, `gcloud auth
    application-default login`. No API key is passed.

    Model availability varies by region; us-east5 is the broadest default.
    """

    def __init__(self, model_name: str, project: str, region: str = "us-east5"):
        from anthropic import AnthropicVertex  # local import; optional dep
        self.model_id = model_name
        self.project = project
        self.region = region
        self.client = AnthropicVertex(project_id=project, region=region)

    def generate(self, prompt, system=None, context=None, tools=None,
                 max_tokens=512, temperature=0.0) -> GenResult:
        sys_str, user_str = self._build_system_and_user(prompt, system, context)
        kwargs = dict(
            model=self.model_id,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": user_str}],
        )
        if sys_str:
            kwargs["system"] = sys_str
        if tools:
            kwargs["tools"] = self._openai_tools_to_anthropic(tools)
        t0 = time.time()
        msg = self.client.messages.create(**kwargs)
        text_parts = []
        for block in msg.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(block.text)
            elif getattr(block, "type", None) == "tool_use":
                # Serialize into the trained <tool_call> shape so the Track-9
                # scorer parses Claude's tool use uniformly with every other model.
                text_parts.append(
                    "<tool_call>"
                    + json.dumps({"name": block.name, "arguments": block.input})
                    + "</tool_call>"
                )
        return GenResult(text="\n".join(text_parts).strip(),
                         raw={"id": getattr(msg, "id", ""),
                              "model": getattr(msg, "model", "")},
                         model_id=self.model_id, latency_s=time.time() - t0)


def build_client(spec: dict) -> ModelClient:
    """
    Construct a client from a JSON spec. Examples:

      local HF checkpoint:
        {"kind":"hf_local","model_path":"/path/to/your/local/model"}

      OpenAI-compatible endpoint (standard / non-thinking model):
        {"kind":"openai_compat","model_name":"your-model-name","base_url":"http://localhost:8000/v1"}

      Qwen3 family via vLLM (suppress thinking mode for deterministic eval):
        {"kind":"openai_compat","model_name":"Qwen/Qwen3.5-9B","base_url":"http://localhost:8000/v1",
         "chat_template_kwargs":{"enable_thinking":false}}

      DeepSeek-R1 / QwQ (always-on reasoning — chat_template_kwargs has no effect):
        {"kind":"openai_compat","model_name":"deepseek-ai/DeepSeek-R1","base_url":"http://localhost:8000/v1"}
        # mcq_exact uses final-committed-answer strategy, so chain-of-thought output
        # scores correctly.  Ensure vLLM --reasoning-parser routes the final answer
        # into message.content.  Do NOT set chat_template_kwargs for these models.

      canonical judge (Claude Sonnet 4.6 via the native Anthropic API):
        {"kind":"anthropic","model_name":"claude-sonnet-4-6","api_key_env":"ANTHROPIC_API_KEY"}

      the same judge via Vertex AI (for teams on GCP; auth via ADC, no API key).
      From the Claude 4.6 generation onward the Vertex model ID is dateless;
      older models use the dated form (e.g. claude-haiku-4-5@20251001):
        {"kind":"vertex_anthropic","model_name":"claude-sonnet-4-6","region":"us-east5","project":"your-gcp-project"}

      base model for comparison (HF local):
        {"kind":"hf_local","model_path":"/path/to/base/model"}

      a competitor via a hosted OpenAI-compatible endpoint (e.g. Together):
        {"kind":"openai_compat","model_name":"meta-llama/Llama-4-...","base_url":"https://api.together.xyz/v1","api_key_env":"TOGETHER_API_KEY"}
    """
    kind = spec["kind"]
    if kind == "hf_local":
        return HFLocalClient(spec["model_path"], device=spec.get("device", "cuda:0"),
                             thinking_kw=spec.get("thinking_kw", "enable_thinking"),
                             adapter=spec.get("adapter"))
    if kind == "openai_compat":
        key = os.environ.get(spec["api_key_env"]) if spec.get("api_key_env") else spec.get("api_key")
        # chat_template_kwargs is opt-in (default None) — safe for all targets including
        # hosted APIs that reject unknown body fields.  Mirrors thinking_kw on hf_local.
        # Qwen3 via vLLM: set {"enable_thinking": false} in the spec explicitly.
        chat_template_kwargs = spec.get("chat_template_kwargs")
        return OpenAICompatClient(spec["model_name"], spec["base_url"],
                                  api_key=key, send_tools=spec.get("send_tools", True),
                                  chat_template_kwargs=chat_template_kwargs)
    if kind in ("vertex_anthropic", "vertex"):
        project = spec.get("project") or spec.get("project_id")
        region = spec.get("region", "us-east5")
        return VertexAnthropicClient(spec["model_name"], project, region=region)
    if kind == "anthropic":
        key = os.environ.get(spec["api_key_env"]) if spec.get("api_key_env") else spec.get("api_key")
        return AnthropicClient(spec["model_name"], api_key=key)
    raise ValueError(f"unknown client kind: {kind}")
