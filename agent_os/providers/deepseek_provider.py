from __future__ import annotations

import json
import os
from pathlib import Path
from urllib import error, request

from dotenv import load_dotenv

from agent_os.providers.base import ProviderBase, ProviderResponse


class DeepSeekChatProvider(ProviderBase):
    name = "deepseek"

    def __init__(self, model_name: str = "deepseek-reasoner") -> None:
        load_dotenv(Path.cwd() / ".env")
        self.model_name = model_name
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self._last_error = ""
        self._available = bool(self.api_key)
        self._probed = False

    @property
    def last_error(self) -> str:
        return self._last_error

    def _endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _request(self, payload: dict[str, object]) -> dict[str, object]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self._endpoint(),
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def is_available(self) -> bool:
        if not self._available:
            if not self.api_key:
                self._last_error = "DEEPSEEK_API_KEY is not configured."
            return False
        if self._probed:
            return self._available
        try:
            self._request(
                {
                    "model": self.model_name,
                    "messages": [{"role": "user", "content": "Reply with exactly OK."}],
                    "max_tokens": 8,
                    "temperature": 0,
                    "stream": False,
                }
            )
            self._last_error = ""
            self._available = True
        except Exception as exc:
            self._available = False
            self._last_error = str(exc)
        self._probed = True
        return self._available

    def generate(self, prompt: str, system: str = "") -> ProviderResponse:
        if not self.is_available():
            output = f"Offline fallback: {self._last_error or 'DeepSeek unavailable.'}"
            return ProviderResponse(text=output, input_tokens=max(1, len(prompt) // 4), output_tokens=max(1, len(output) // 4), model="offline-fallback")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            data = self._request(
                {
                    "model": self.model_name,
                    "messages": messages,
                    "temperature": 0.2,
                    "stream": False,
                }
            )
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            usage = data.get("usage") or {}
            text = str(message.get("content", "") or "").strip() or "Model returned empty text."
            self._last_error = ""
            return ProviderResponse(
                text=text,
                input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage.get("completion_tokens", 0) or 0),
                model=str(data.get("model", self.model_name)),
            )
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self._last_error = f"HTTP {exc.code}: {detail[:400]}"
        except Exception as exc:
            self._last_error = str(exc)
        output = f"Offline fallback: {self._last_error or 'DeepSeek unavailable.'}"
        return ProviderResponse(text=output, input_tokens=max(1, len(prompt) // 4), output_tokens=max(1, len(output) // 4), model="offline-fallback")
