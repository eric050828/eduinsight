"""Tests for the LLM provider and memory-augmented conversation."""

import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from eduinsight.llm import LLMClient, LLMConfig, resolve_llm_config


class TestResolveLLMConfig:
    def test_explicit_params(self) -> None:
        cfg = resolve_llm_config(model="m", base_url="http://x/", api_key="k")
        assert cfg.model == "m"
        assert cfg.base_url == "http://x/"
        assert cfg.api_key == "k"

    def test_gemini_from_env(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gem-key"}, clear=False):
            # Remove other keys to ensure Gemini is selected
            env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
            with patch.dict(os.environ, env, clear=True):
                cfg = resolve_llm_config()
                assert "gemini" in cfg.model
                assert cfg.api_key == "gem-key"

    def test_openai_takes_priority(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "oai-key", "GEMINI_API_KEY": "gem-key"},
            clear=True,
        ):
            cfg = resolve_llm_config()
            assert cfg.api_key == "oai-key"

    def test_no_key_raises(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="No LLM API key found"):
                resolve_llm_config()


class TestLLMClient:
    @pytest.mark.asyncio
    async def test_chat_success(self) -> None:
        config = LLMConfig(model="test-model", base_url="http://llm.test/v1/", api_key="test")
        client = LLMClient(config)

        mock_response = httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "Polymorphism means many forms."}}
                ]
            },
            request=httpx.Request("POST", "http://llm.test/v1/chat/completions"),
        )

        async with client:
            with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_response
                reply = await client.chat("What is polymorphism?", system_prompt="You are a tutor.")
                assert reply == "Polymorphism means many forms."

                # Verify the request payload
                call_args = mock_post.call_args
                payload = call_args.kwargs["json"]
                assert payload["model"] == "test-model"
                assert len(payload["messages"]) == 2
                assert payload["messages"][0]["role"] == "system"
                assert payload["messages"][1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_chat_no_system_prompt(self) -> None:
        config = LLMConfig(model="test-model", base_url="http://llm.test/v1/", api_key="test")
        client = LLMClient(config)

        mock_response = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Hello!"}}]},
            request=httpx.Request("POST", "http://llm.test/v1/chat/completions"),
        )

        async with client:
            with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_response
                reply = await client.chat("Hi")
                assert reply == "Hello!"
                payload = mock_post.call_args.kwargs["json"]
                assert len(payload["messages"]) == 1  # No system prompt

    @pytest.mark.asyncio
    async def test_context_manager_required(self) -> None:
        config = LLMConfig(model="m", base_url="http://x/", api_key="k")
        client = LLMClient(config)
        with pytest.raises(RuntimeError, match="context manager"):
            await client.chat("test")

    @pytest.mark.asyncio
    async def test_api_error_raises_runtime_error(self) -> None:
        config = LLMConfig(model="m", base_url="http://llm.test/v1/", api_key="k")
        client = LLMClient(config)

        mock_response = httpx.Response(
            500,
            text="Internal Server Error",
            request=httpx.Request("POST", "http://llm.test/v1/chat/completions"),
        )

        async with client:
            with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_response
                with pytest.raises(RuntimeError, match="LLM API error 500"):
                    await client.chat("test")
