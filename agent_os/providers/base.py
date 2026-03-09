from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class ProviderResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class ProviderBase:
    name = "base"

    def generate(self, prompt: str, system: str = "") -> ProviderResponse:
        raise NotImplementedError

    def is_available(self) -> bool:
        return False

    @property
    def last_error(self) -> str:
        return ""
