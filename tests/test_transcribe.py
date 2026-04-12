"""Tests for audio transcription module."""

from __future__ import annotations

from pathlib import Path

import pytest

from eduinsight.transcribe import (
    SUPPORTED_FORMATS,
    GroqTranscriber,
    OpenAITranscriber,
    StubTranscriber,
    TranscriptResult,
    TranscriptSegment,
    _mime_type,
    _validate_audio_file,
    auto_transcriber,
)

# ------------------------------------------------------------------
# TranscriptResult / TranscriptSegment tests
# ------------------------------------------------------------------


class TestTranscriptResult:
    def test_basic_fields(self):
        result = TranscriptResult(
            text="Hello world", language="en", duration=10.5, provider="test",
        )
        assert result.text == "Hello world"
        assert result.language == "en"
        assert result.duration == 10.5
        assert result.segments == []
        assert result.provider == "test"

    def test_with_segments(self):
        seg = TranscriptSegment(start=0.0, end=5.0, text="First part")
        result = TranscriptResult(
            text="First part Second part",
            language="zh",
            duration=10.0,
            segments=[seg],
        )
        assert len(result.segments) == 1
        assert result.segments[0].start == 0.0
        assert result.segments[0].text == "First part"


# ------------------------------------------------------------------
# Validation tests
# ------------------------------------------------------------------


class TestValidateAudioFile:
    def test_missing_file(self):
        with pytest.raises(FileNotFoundError, match="Audio file not found"):
            _validate_audio_file(Path("/nonexistent/audio.mp3"))

    def test_unsupported_format(self, tmp_path):
        bad = tmp_path / "lecture.txt"
        bad.write_text("not audio")
        with pytest.raises(ValueError, match="Unsupported format"):
            _validate_audio_file(bad)

    def test_empty_file(self, tmp_path):
        empty = tmp_path / "empty.mp3"
        empty.write_bytes(b"")
        with pytest.raises(ValueError, match="empty"):
            _validate_audio_file(empty)

    def test_valid_file(self, tmp_path):
        valid = tmp_path / "test.mp3"
        valid.write_bytes(b"\xff" * 100)
        # Should not raise
        _validate_audio_file(valid)

    def test_all_supported_formats(self, tmp_path):
        for ext in SUPPORTED_FORMATS:
            f = tmp_path / f"test{ext}"
            f.write_bytes(b"\x00" * 10)
            _validate_audio_file(f)  # Should not raise


# ------------------------------------------------------------------
# MIME type tests
# ------------------------------------------------------------------


class TestMimeType:
    def test_mp3(self):
        assert _mime_type(Path("test.mp3")) == "audio/mpeg"

    def test_wav(self):
        assert _mime_type(Path("test.wav")) == "audio/wav"

    def test_m4a(self):
        assert _mime_type(Path("test.m4a")) == "audio/mp4"

    def test_unknown(self):
        assert _mime_type(Path("test.xyz")) == "application/octet-stream"


# ------------------------------------------------------------------
# StubTranscriber tests
# ------------------------------------------------------------------


class TestStubTranscriber:
    @pytest.mark.asyncio
    async def test_default_output(self, tmp_path):
        audio = tmp_path / "lecture.mp3"
        audio.write_bytes(b"\xff" * 100)

        t = StubTranscriber()
        result = await t.transcribe(audio)
        assert "lecture.mp3" in result.text
        assert result.provider == "stub"
        assert result.duration == 60.0
        assert len(result.segments) == 1

    @pytest.mark.asyncio
    async def test_custom_text(self, tmp_path):
        audio = tmp_path / "test.wav"
        audio.write_bytes(b"\xff" * 100)

        t = StubTranscriber(text="Custom transcript", language="en")
        result = await t.transcribe(audio)
        assert result.text == "Custom transcript"
        assert result.language == "en"

    @pytest.mark.asyncio
    async def test_language_override(self, tmp_path):
        audio = tmp_path / "test.mp3"
        audio.write_bytes(b"\xff" * 100)

        t = StubTranscriber()
        result = await t.transcribe(audio, language="ja")
        assert result.language == "ja"


# ------------------------------------------------------------------
# auto_transcriber tests
# ------------------------------------------------------------------


class TestAutoTranscriber:
    def test_no_keys_returns_stub(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        t = auto_transcriber()
        assert isinstance(t, StubTranscriber)

    def test_groq_key_returns_groq(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        t = auto_transcriber()
        assert isinstance(t, GroqTranscriber)

    def test_openai_key_returns_openai(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        t = auto_transcriber()
        assert isinstance(t, OpenAITranscriber)

    def test_groq_takes_priority(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "groq-key")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
        t = auto_transcriber()
        assert isinstance(t, GroqTranscriber)


# ------------------------------------------------------------------
# GroqTranscriber / OpenAITranscriber validation tests
# ------------------------------------------------------------------


class TestGroqTranscriberValidation:
    @pytest.mark.asyncio
    async def test_no_api_key_raises(self, tmp_path):
        audio = tmp_path / "test.mp3"
        audio.write_bytes(b"\xff" * 100)
        t = GroqTranscriber(api_key="")
        with pytest.raises(ValueError, match="GROQ_API_KEY"):
            await t.transcribe(audio)


class TestOpenAITranscriberValidation:
    @pytest.mark.asyncio
    async def test_no_api_key_raises(self, tmp_path):
        audio = tmp_path / "test.mp3"
        audio.write_bytes(b"\xff" * 100)
        t = OpenAITranscriber(api_key="")
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            await t.transcribe(audio)
