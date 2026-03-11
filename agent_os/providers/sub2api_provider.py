from __future__ import annotations

import json
import os
from pathlib import Path
from urllib import error, request

from dotenv import load_dotenv

from agent_os.providers.base import ProviderBase, ProviderResponse


class Sub2ApiResponsesProvider(ProviderBase):
    name = "sub2api_responses"

    def __init__(
        self,
        model_name: str = "gpt-5.4",
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        reasoning_effort: str | None = None,
        verbosity: str | None = None,
    ) -> None:
        load_dotenv(Path.cwd() / ".env")
        self.model_name = model_name
        self.base_url = (
            base_url
            or os.getenv("SUB2API_BASE_URL", "")
            or os.getenv("OPENAI_BASE_URL", "")
            or "https://vpsairobot.com"
        ).rstrip("/")
        self.api_key = (api_key or os.getenv("SUB2API_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")).strip()
        self.reasoning_effort = (
            reasoning_effort
            or os.getenv("SUB2API_REASONING_EFFORT", "")
            or os.getenv("OPENAI_REASONING_EFFORT", "")
            or "high"
        ).strip()
        self.verbosity = (
            verbosity
            or os.getenv("SUB2API_VERBOSITY", "")
            or os.getenv("OPENAI_VERBOSITY", "")
            or "high"
        ).strip()
        self._last_error = ""
        self._available = bool(self.api_key)
        self._probed = False

    @property
    def last_error(self) -> str:
        return self._last_error

    def _endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/responses"
        if self.base_url.endswith("/responses"):
            return self.base_url
        return f"{self.base_url}/v1/responses"

    def _build_payload(self, prompt: str, system: str = "") -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model_name,
            "input": prompt,
            "store": False,
        }
        if system:
            payload["instructions"] = system
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        if self.verbosity:
            payload["text"] = {"verbosity": self.verbosity}
        return payload

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
        with request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _extract_output_text(self, data: dict[str, object]) -> str:
        direct = str(data.get("output_text", "") or "").strip()
        if direct:
            return direct

        output = data.get("output") or []
        if not isinstance(output, list):
            return ""

        chunks: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                kind = str(content.get("type", ""))
                if kind == "output_text":
                    text = str(content.get("text", "") or "").strip()
                    if text:
                        chunks.append(text)
                elif kind == "refusal":
                    refusal = str(content.get("refusal", "") or "").strip()
                    if refusal:
                        chunks.append(refusal)
        return "\n".join(chunks).strip()

    def _usage_tokens(self, data: dict[str, object]) -> tuple[int, int]:
        usage = data.get("usage") or {}
        if not isinstance(usage, dict):
            return (0, 0)
        input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
        output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
        return input_tokens, output_tokens

    def is_available(self) -> bool:
        if not self._available:
            if not self.api_key:
                self._last_error = "SUB2API_API_KEY or OPENAI_API_KEY is not configured."
            return False
        if self._probed:
            return self._available
        try:
            self._request(self._build_payload("Reply with exactly OK."))
            self._last_error = ""
            self._available = True
        except Exception as exc:
            self._available = False
            self._last_error = str(exc)
        self._probed = True
        return self._available

    def generate(self, prompt: str, system: str = "") -> ProviderResponse:
        if not self.is_available():
            output = f"Offline fallback: {self._last_error or 'Sub2API unavailable.'}"
            return ProviderResponse(
                text=output,
                input_tokens=max(1, len(prompt) // 4),
                output_tokens=max(1, len(output) // 4),
                model="offline-fallback",
            )

        try:
            data = self._request(self._build_payload(prompt, system=system))
            text = self._extract_output_text(data) or "Model returned empty text."
            input_tokens, output_tokens = self._usage_tokens(data)
            self._last_error = ""
            return ProviderResponse(
                text=text,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=str(data.get("model", self.model_name)),
            )
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self._last_error = f"HTTP {exc.code}: {detail[:400]}"
        except Exception as exc:
            self._last_error = str(exc)

        output = f"Offline fallback: {self._last_error or 'Sub2API unavailable.'}"
        return ProviderResponse(
            text=output,
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=max(1, len(output) // 4),
            model="offline-fallback",
        )
