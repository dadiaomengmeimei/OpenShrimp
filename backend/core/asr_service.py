"""
Shared ASR service – wraps Whisper / compatible API for all sub-apps.
"""
from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Optional

from openai import AsyncOpenAI

from backend.config import asr_settings


def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=asr_settings.api_key or "sk-placeholder",
        base_url=asr_settings.api_base,
    )


async def transcribe(
    audio_file: BinaryIO | Path,
    *,
    model: Optional[str] = None,
    language: Optional[str] = None,
) -> str:
    """Transcribe an audio file and return plain text."""
    client = _get_client()
    if isinstance(audio_file, Path):
        audio_file = open(audio_file, "rb")

    resp = await client.audio.transcriptions.create(
        model=model or asr_settings.model,
        file=audio_file,
        language=language,
    )
    return resp.text
