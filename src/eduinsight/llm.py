"""LLM provider for generating AI responses.

Uses Gemini via its OpenAI-compatible endpoint (no extra dependencies).
Falls back to: OPENAI_API_KEY > GEMINI_API_KEY > GROQ_API_KEY.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Gemini OpenAI-compatible endpoint (same pattern as Lite-Mem)
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
_GROQ_BASE_URL = "https://api.groq.com/openai/v1/"
_GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"


@dataclass
class LLMConfig:
    """Resolved LLM configuration."""

    model: str
    base_url: str
    api_key: str


def resolve_llm_config(
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> LLMConfig:
    """Auto-detect LLM provider from environment variables.

    Priority: explicit params > OPENAI_API_KEY > GEMINI_API_KEY > GROQ_API_KEY.

    Raises:
        ValueError: If no API key is found.
    """
    if api_key and base_url and model:
        return LLMConfig(model=model, base_url=base_url, api_key=api_key)

    openai_key = os.environ.get("OPENAI_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")

    if openai_key:
        return LLMConfig(
            model=model or _OPENAI_DEFAULT_MODEL,
            base_url=base_url or "https://api.openai.com/v1/",
            api_key=api_key or openai_key,
        )

    if gemini_key:
        return LLMConfig(
            model=model or _GEMINI_DEFAULT_MODEL,
            base_url=base_url or _GEMINI_BASE_URL,
            api_key=api_key or gemini_key,
        )

    if groq_key:
        return LLMConfig(
            model=model or _GROQ_DEFAULT_MODEL,
            base_url=base_url or _GROQ_BASE_URL,
            api_key=api_key or groq_key,
        )

    raise ValueError(
        "No LLM API key found. Set one of: GEMINI_API_KEY, OPENAI_API_KEY, GROQ_API_KEY"
    )


class ClaudeCLIClient:
    """LLM client that shells out to `claude -p` for AI responses.

    Uses the Claude Code CLI with haiku model — no API key needed,
    uses the user's existing Claude Code subscription.

    Usage::

        async with ClaudeCLIClient() as llm:
            reply = await llm.chat("Hello, explain polymorphism.")
    """

    def __init__(self, model: str = "haiku") -> None:
        self._model = model

    async def __aenter__(self) -> ClaudeCLIClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        pass

    async def chat(
        self,
        user_message: str,
        *,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        """Call claude -p to generate a response."""
        import asyncio
        import shutil

        claude_bin = shutil.which("claude")
        if not claude_bin:
            raise RuntimeError("claude CLI not found in PATH")

        prompt = ""
        if system_prompt:
            prompt += f"[System]\n{system_prompt}\n\n"
        prompt += user_message

        proc = await asyncio.create_subprocess_exec(
            claude_bin, "-p", prompt,
            "--model", self._model,
            "--max-turns", "1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            err = stderr.decode(errors="replace")[:300]
            raise RuntimeError(f"claude CLI error (rc={proc.returncode}): {err}")

        return stdout.decode(errors="replace").strip()


class LLMClient:
    """Async LLM client using OpenAI-compatible chat completions API.

    Works with Gemini, OpenAI, Groq, or any OpenAI-compatible endpoint.

    Usage::

        async with LLMClient() as llm:
            reply = await llm.chat("Hello, explain polymorphism.")
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        self._config = config
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> LLMClient:
        cfg = self._config or resolve_llm_config()
        self._config = cfg
        self._http = httpx.AsyncClient(
            base_url=cfg.base_url,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=60.0,
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    async def chat(
        self,
        user_message: str,
        *,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        """Send a chat completion request and return the assistant's reply.

        Args:
            user_message: The user's message.
            system_prompt: Optional system prompt prepended to the conversation.
            temperature: Sampling temperature (0.0 = deterministic).
            max_tokens: Maximum tokens in the response.

        Returns:
            The assistant's reply text.

        Raises:
            RuntimeError: If the LLM call fails after retries.
        """
        if self._http is None:
            raise RuntimeError("LLMClient must be used as async context manager")

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        payload = {
            "model": self._config.model,  # type: ignore[union-attr]
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                resp = await self._http.post("chat/completions", json=payload)
                if resp.status_code == 429 and attempt < max_retries:
                    wait = [10, 30, 60][attempt]
                    logger.warning(
                        "LLM 429 rate limit, retrying in %ds (attempt %d/%d)",
                        wait,
                        attempt + 1,
                        max_retries,
                    )
                    import asyncio

                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as e:
                if attempt < max_retries and e.response.status_code == 429:
                    continue
                raise RuntimeError(
                    f"LLM API error {e.response.status_code}: {e.response.text[:300]}"
                ) from e
            except httpx.RequestError as e:
                raise RuntimeError(f"LLM API connection error: {e}") from e

        raise RuntimeError("LLM API: max retries exceeded")
