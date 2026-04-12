"""Audio transcription for lecture recordings.

Supports multiple backends:
- Groq Whisper API (free tier, fast)
- OpenAI Whisper API (paid)
- Stub (offline testing)

Auto-selects based on available API keys: GROQ_API_KEY > OPENAI_API_KEY.

Usage::

    transcriber = auto_transcriber()
    result = await transcriber.transcribe("lecture.mp3")
    print(result.text)
    for seg in result.segments:
        print(f"[{seg.start:.1f}s] {seg.text}")
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

# Supported audio formats
SUPPORTED_FORMATS = {".mp3", ".mp4", ".m4a", ".wav", ".webm", ".ogg", ".flac"}
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB (Whisper API limit)


@dataclass
class TranscriptSegment:
    """A segment of transcribed audio with timing."""

    start: float  # seconds
    end: float  # seconds
    text: str


@dataclass
class TranscriptResult:
    """Full transcription result."""

    text: str  # full transcript text
    language: str  # detected language code (e.g. "zh", "en")
    duration: float  # audio duration in seconds
    segments: list[TranscriptSegment] = field(default_factory=list)
    provider: str = ""  # which backend produced this


class Transcriber(Protocol):
    """Protocol for audio transcription backends."""

    async def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptResult: ...


class GroqTranscriber:
    """Transcription via Groq's Whisper API.

    Groq offers whisper-large-v3-turbo with fast inference.
    Free tier: 28,800 audio-seconds/day.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("GROQ_API_KEY", "")

    async def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptResult:
        if not self._api_key:
            raise ValueError("GROQ_API_KEY not set")

        path = Path(audio_path)
        _validate_audio_file(path)

        data: dict[str, str] = {
            "model": "whisper-large-v3-turbo",
            "response_format": "verbose_json",
        }
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt

        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(path, "rb") as f:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    data=data,
                    files={"file": (path.name, f, _mime_type(path))},
                )
            resp.raise_for_status()
            body = resp.json()

        segments = [
            TranscriptSegment(
                start=s.get("start", 0.0),
                end=s.get("end", 0.0),
                text=s.get("text", "").strip(),
            )
            for s in body.get("segments", [])
        ]

        return TranscriptResult(
            text=body.get("text", "").strip(),
            language=body.get("language", ""),
            duration=body.get("duration", 0.0),
            segments=segments,
            provider="groq-whisper",
        )


class OpenAITranscriber:
    """Transcription via OpenAI's Whisper API."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    async def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptResult:
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY not set")

        path = Path(audio_path)
        _validate_audio_file(path)

        data: dict[str, str] = {
            "model": "whisper-1",
            "response_format": "verbose_json",
        }
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt

        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(path, "rb") as f:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    data=data,
                    files={"file": (path.name, f, _mime_type(path))},
                )
            resp.raise_for_status()
            body = resp.json()

        segments = [
            TranscriptSegment(
                start=s.get("start", 0.0),
                end=s.get("end", 0.0),
                text=s.get("text", "").strip(),
            )
            for s in body.get("segments", [])
        ]

        return TranscriptResult(
            text=body.get("text", "").strip(),
            language=body.get("language", ""),
            duration=body.get("duration", 0.0),
            segments=segments,
            provider="openai-whisper",
        )


class StubTranscriber:
    """Stub transcriber for testing — returns a fixed transcript."""

    def __init__(self, text: str = "", language: str = "zh") -> None:
        self._text = text
        self._language = language

    async def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptResult:
        return TranscriptResult(
            text=self._text or f"[Stub transcript for {Path(audio_path).name}]",
            language=language or self._language,
            duration=60.0,
            segments=[
                TranscriptSegment(start=0.0, end=60.0, text=self._text or "stub segment"),
            ],
            provider="stub",
        )


def auto_transcriber() -> GroqTranscriber | OpenAITranscriber | StubTranscriber:
    """Auto-detect transcription backend from environment variables.

    Priority: GROQ_API_KEY > OPENAI_API_KEY > StubTranscriber.
    """
    if os.environ.get("GROQ_API_KEY"):
        logger.info("Using Groq Whisper for transcription")
        return GroqTranscriber()
    if os.environ.get("OPENAI_API_KEY"):
        logger.info("Using OpenAI Whisper for transcription")
        return OpenAITranscriber()
    logger.warning("No transcription API key found, using StubTranscriber")
    return StubTranscriber()


def _validate_audio_file(path: Path) -> None:
    """Validate an audio file before transcription."""
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format: {path.suffix}. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )
    size = path.stat().st_size
    if size > MAX_FILE_SIZE:
        max_mb = MAX_FILE_SIZE // 1024 // 1024
        raise ValueError(f"File too large: {size / 1024 / 1024:.1f}MB (max {max_mb}MB)")
    if size == 0:
        raise ValueError("Audio file is empty")


def _mime_type(path: Path) -> str:
    """Get MIME type for an audio file."""
    mime_map = {
        ".mp3": "audio/mpeg",
        ".mp4": "audio/mp4",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".webm": "audio/webm",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }
    return mime_map.get(path.suffix.lower(), "application/octet-stream")
