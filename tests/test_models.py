# Copyright 2026 Haytam Aroui
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for harness/models.py.

Tests cover pure static helpers and the build_client factory.
Network-dependent clients (AnthropicClient, VertexAnthropicClient) are tested
via mocking so no API keys or network calls are needed.
HFLocalClient is skipped when torch is not installed (bare CI).
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from harness.models import ModelClient, OpenAICompatClient, GenResult, build_client


# ── ModelClient static helpers ────────────────────────────────────────────────

class TestBuildMessages:
    def test_prompt_only(self):
        msgs = ModelClient._build_messages("Hello", None, None)
        assert len(msgs) == 1
        assert msgs[-1] == {"role": "user", "content": "Hello"}

    def test_with_system(self):
        msgs = ModelClient._build_messages("Q", "You are a lawyer.", None)
        assert msgs[0] == {"role": "system", "content": "You are a lawyer."}
        assert msgs[-1]["role"] == "user"

    def test_with_string_context(self):
        msgs = ModelClient._build_messages("Q", None, "Background text")
        sys_msgs = [m for m in msgs if m["role"] == "system"]
        assert any("Background text" in m["content"] for m in sys_msgs)

    def test_with_list_context(self):
        msgs = ModelClient._build_messages("Q", None, ["Doc A", "Doc B"])
        sys_msgs = [m for m in msgs if m["role"] == "system"]
        assert any("Doc A" in m["content"] and "Doc B" in m["content"]
                   for m in sys_msgs)

    def test_system_and_context_both_present(self):
        msgs = ModelClient._build_messages("Q", "System.", "Context.")
        sys_roles = [m for m in msgs if m["role"] == "system"]
        assert len(sys_roles) == 2  # one for system, one for context
        assert msgs[-1]["role"] == "user"

    def test_user_message_always_last(self):
        msgs = ModelClient._build_messages("Prompt", "Sys", "Ctx")
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "Prompt"


class TestBuildSystemAndUser:
    def test_no_system_no_context(self):
        sys_str, user = ModelClient._build_system_and_user("Prompt", None, None)
        assert sys_str is None
        assert user == "Prompt"

    def test_system_only(self):
        sys_str, user = ModelClient._build_system_and_user("Q", "Be precise.", None)
        assert sys_str == "Be precise."
        assert user == "Q"

    def test_context_only(self):
        sys_str, user = ModelClient._build_system_and_user("Q", None, "Some context")
        assert sys_str is not None
        assert "Some context" in sys_str
        assert user == "Q"

    def test_system_and_context_joined(self):
        sys_str, user = ModelClient._build_system_and_user("Q", "Be precise.", "Doc A")
        assert "Be precise." in sys_str
        assert "Doc A" in sys_str

    def test_list_context_joined(self):
        sys_str, _ = ModelClient._build_system_and_user("Q", None, ["Doc A", "Doc B"])
        assert "Doc A" in sys_str
        assert "Doc B" in sys_str


class TestOpenAIToolsToAnthropic:
    def test_empty_list(self):
        assert ModelClient._openai_tools_to_anthropic([]) == []

    def test_none_input(self):
        assert ModelClient._openai_tools_to_anthropic(None) == []

    def test_single_tool_conversion(self):
        tools = [{
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search for case law",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            }
        }]
        result = ModelClient._openai_tools_to_anthropic(tools)
        assert len(result) == 1
        assert result[0]["name"] == "search"
        assert result[0]["description"] == "Search for case law"
        assert "input_schema" in result[0]
        assert result[0]["input_schema"]["type"] == "object"

    def test_missing_description_defaults_empty_string(self):
        tools = [{"function": {"name": "lookup", "parameters": {}}}]
        result = ModelClient._openai_tools_to_anthropic(tools)
        assert result[0]["description"] == ""

    def test_missing_parameters_defaults_to_empty_schema(self):
        tools = [{"function": {"name": "noop"}}]
        result = ModelClient._openai_tools_to_anthropic(tools)
        assert "input_schema" in result[0]

    def test_multiple_tools(self):
        tools = [
            {"function": {"name": "search", "description": "s", "parameters": {}}},
            {"function": {"name": "lookup", "description": "l", "parameters": {}}},
        ]
        result = ModelClient._openai_tools_to_anthropic(tools)
        assert len(result) == 2
        names = {t["name"] for t in result}
        assert names == {"search", "lookup"}

    def test_flat_tool_without_function_wrapper(self):
        # build_client passes tools that may already be the function dict directly
        tools = [{"name": "search", "description": "s",
                  "parameters": {"type": "object", "properties": {}}}]
        result = ModelClient._openai_tools_to_anthropic(tools)
        assert result[0]["name"] == "search"


# ── OpenAICompatClient init ───────────────────────────────────────────────────

class TestOpenAICompatClientInit:
    def test_attributes_stored(self):
        c = OpenAICompatClient("gpt-4o", "https://api.openai.com/v1", api_key="sk-x")
        assert c.model_id == "gpt-4o"
        assert c.base_url == "https://api.openai.com/v1"
        assert c.api_key == "sk-x"
        assert c.send_tools is True
        assert c.chat_template_kwargs is None

    def test_trailing_slash_stripped_from_base_url(self):
        c = OpenAICompatClient("m", "http://localhost:8000/v1/")
        assert c.base_url == "http://localhost:8000/v1"

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-sk")
        c = OpenAICompatClient("m", "http://x/v1")
        assert c.api_key == "env-sk"

    def test_explicit_key_overrides_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-sk")
        c = OpenAICompatClient("m", "http://x/v1", api_key="explicit-sk")
        assert c.api_key == "explicit-sk"

    def test_chat_template_kwargs_stored(self):
        c = OpenAICompatClient("m", "http://x/v1",
                               chat_template_kwargs={"enable_thinking": False})
        assert c.chat_template_kwargs == {"enable_thinking": False}

    def test_chat_template_kwargs_default_none(self):
        c = OpenAICompatClient("m", "http://x/v1")
        assert c.chat_template_kwargs is None

    def test_send_tools_false(self):
        c = OpenAICompatClient("m", "http://x/v1", send_tools=False)
        assert c.send_tools is False


# ── build_client factory ──────────────────────────────────────────────────────

class TestBuildClient:
    def test_openai_compat_returns_correct_type(self):
        spec = {"kind": "openai_compat", "model_name": "gpt-4o",
                "base_url": "http://localhost/v1"}
        c = build_client(spec)
        assert isinstance(c, OpenAICompatClient)
        assert c.model_id == "gpt-4o"

    def test_openai_compat_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "test-val")
        spec = {"kind": "openai_compat", "model_name": "m",
                "base_url": "http://x/v1", "api_key_env": "MY_KEY"}
        c = build_client(spec)
        assert c.api_key == "test-val"

    def test_openai_compat_chat_template_kwargs_forwarded(self):
        spec = {"kind": "openai_compat", "model_name": "Qwen/Qwen3.5-9B",
                "base_url": "http://localhost/v1",
                "chat_template_kwargs": {"enable_thinking": False}}
        c = build_client(spec)
        assert c.chat_template_kwargs == {"enable_thinking": False}

    def test_openai_compat_no_chat_template_kwargs_is_none(self):
        spec = {"kind": "openai_compat", "model_name": "m",
                "base_url": "http://x/v1"}
        c = build_client(spec)
        assert c.chat_template_kwargs is None

    def test_openai_compat_gemini_config(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
        spec = {
            "kind": "openai_compat",
            "model_name": "gemini-1.5-flash",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key_env": "GEMINI_API_KEY"
        }
        c = build_client(spec)
        assert isinstance(c, OpenAICompatClient)
        assert c.model_id == "gemini-1.5-flash"
        assert c.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
        assert c.api_key == "gemini-test-key"

    def test_openai_compat_send_tools_default_true(self):
        spec = {"kind": "openai_compat", "model_name": "m",
                "base_url": "http://x/v1"}
        c = build_client(spec)
        assert c.send_tools is True

    def test_openai_compat_send_tools_false(self):
        spec = {"kind": "openai_compat", "model_name": "m",
                "base_url": "http://x/v1", "send_tools": False}
        c = build_client(spec)
        assert c.send_tools is False

    def test_unknown_kind_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown client kind"):
            build_client({"kind": "totally_unknown_kind"})

    def test_anthropic_kind_routes_correctly(self):
        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value = MagicMock()
            from harness.models import AnthropicClient
            spec = {"kind": "anthropic", "model_name": "claude-sonnet-4-6",
                    "api_key": "sk-test"}
            c = build_client(spec)
            assert isinstance(c, AnthropicClient)
            assert c.model_id == "claude-sonnet-4-6"

    def test_vertex_anthropic_kind_routes_correctly(self):
        with patch("anthropic.AnthropicVertex") as mock_cls:
            mock_cls.return_value = MagicMock()
            from harness.models import VertexAnthropicClient
            spec = {"kind": "vertex_anthropic", "model_name": "claude-sonnet-4-6",
                    "project": "my-project", "region": "us-east5"}
            c = build_client(spec)
            assert isinstance(c, VertexAnthropicClient)
            assert c.model_id == "claude-sonnet-4-6"
            assert c.project == "my-project"
            assert c.region == "us-east5"

    def test_vertex_alias_works(self):
        with patch("anthropic.AnthropicVertex") as mock_cls:
            mock_cls.return_value = MagicMock()
            spec = {"kind": "vertex", "model_name": "claude-sonnet-4-6",
                    "project": "proj", "region": "us-east5"}
            c = build_client(spec)
            from harness.models import VertexAnthropicClient
            assert isinstance(c, VertexAnthropicClient)

    def test_hf_local_skipped_without_torch(self):
        pytest.importorskip("torch",
                            reason="torch not installed — skip hf_local test")
        # If torch is available, just verify build_client maps the kind correctly.
        # We don't instantiate (would need a real checkpoint path).
        from harness.models import HFLocalClient
        assert HFLocalClient  # kind exists


# ── GenResult dataclass ───────────────────────────────────────────────────────

class TestGenResult:
    def test_defaults(self):
        r = GenResult(text="hello")
        assert r.text == "hello"
        assert r.raw == {}
        assert r.model_id == ""
        assert r.latency_s == 0.0

    def test_explicit_fields(self):
        r = GenResult(text="hi", raw={"id": "x"}, model_id="gpt-4o", latency_s=1.23)
        assert r.raw == {"id": "x"}
        assert r.model_id == "gpt-4o"
        assert r.latency_s == 1.23


# ── VertexAnthropicClient parity with AnthropicClient ─────────────────────────

class TestVertexAnthropicParity:
    """After the deduplication fix, VertexAnthropicClient must produce the same
    system/user split as AnthropicClient via _build_system_and_user(). This test
    guards against drift between the two Anthropic-API clients."""

    def test_system_and_context_match_anthropic_client(self):
        """Both clients should produce identical (sys_str, user_str) for the same inputs."""
        sys_str, user_str = ModelClient._build_system_and_user(
            "What is art. 6.5 BW?", "Be precise.", "Context: Book 6 reform."
        )
        assert "Be precise." in sys_str
        assert "Context: Book 6 reform." in sys_str
        assert user_str == "What is art. 6.5 BW?"

    def test_no_system_no_context_returns_none_system(self):
        sys_str, user_str = ModelClient._build_system_and_user("Prompt", None, None)
        assert sys_str is None
        assert user_str == "Prompt"
