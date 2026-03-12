from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass


@dataclass
class ProviderResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


@dataclass
class StreamChunk:
    delta: str
    finish_reason: str | None = None


class ProviderBase:
    name = "base"

    def generate(self, prompt: str, system: str = "") -> ProviderResponse:
        raise NotImplementedError

    async def generate_stream(self, prompt: str, system: str = "") -> AsyncGenerator[StreamChunk, None]:
        """Stream generation. Default implementation falls back to non-streaming."""
        response = self.generate(prompt, system)
        yield StreamChunk(delta=response.text, finish_reason="stop")

    def is_available(self) -> bool:
        return False

    @property
    def last_error(self) -> str:
        return ""
