from __future__ import annotations

import os
import socket
import warnings
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

from agent_os.providers.base import ProviderBase, ProviderResponse


def _port_open(host: str, port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class GeminiFlashProvider(ProviderBase):
    def __init__(self, model_name: str = "") -> None:
        self.model_name = model_name
        self._client = None
        self._available = False
        self._genai = None
        self._probed = False
        self._candidate_models: list[str] = []
        self._failed_models: set[str] = set()
        self._last_error = ""

        env_path = Path.cwd() / ".env"
        load_dotenv(env_path)
        env_values = dotenv_values(env_path)

        if not os.getenv("http_proxy") and not os.getenv("HTTP_PROXY") and _port_open("127.0.0.1", 7897):
            os.environ.setdefault("http_proxy", "http://127.0.0.1:7897")
        if not os.getenv("https_proxy") and not os.getenv("HTTPS_PROXY") and _port_open("127.0.0.1", 7897):
            os.environ.setdefault("https_proxy", "http://127.0.0.1:7897")

        api_key = (os.getenv("GEMINI_API_KEY", "") or env_values.get("GEMINI_API_KEY") or "").strip()
        if not api_key:
            self._last_error = "GEMINI_API_KEY is not configured."
            return

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                import google.generativeai as genai

            genai.configure(api_key=api_key, transport="rest")
            self._genai = genai
            self._candidate_models = self._candidate_model_names(genai)
            if self.model_name:
                self._candidate_models = [self.model_name] + [m for m in self._candidate_models if m != self.model_name]
            self.model_name = self._candidate_models[0] if self._candidate_models else (self.model_name or "models/gemini-2.5-flash")
            self._client = genai.GenerativeModel(model_name=self.model_name)
            self._available = True
        except Exception as exc:
            self._last_error = str(exc)
            self._available = False
            self._client = None

    @property
    def last_error(self) -> str:
        return self._last_error

    def _candidate_model_names(self, genai) -> list[str]:
        try:
            names = [
                m.name
                for m in genai.list_models()
                if "generateContent" in getattr(m, "supported_generation_methods", [])
            ]
        except Exception as exc:
            self._last_error = str(exc)
            return ["models/gemini-2.5-flash", "models/gemini-flash-lite-latest"]

        def allowed(name: str) -> bool:
            lowered = name.lower()
            if "flash" not in lowered:
                return False
            blocked = ("image", "tts", "embedding", "aqa", "live")
            return not any(token in lowered for token in blocked)

        filtered = [name for name in names if allowed(name)]

        def rank(name: str) -> tuple[int, str]:
            lowered = name.lower()
            if "2.5-flash" in lowered and "lite" not in lowered and "preview" not in lowered:
                return (0, lowered)
            if "flash-lite-latest" in lowered:
                return (1, lowered)
            if "2.5-flash-lite" in lowered and "preview" not in lowered:
                return (2, lowered)
            if "2.5-flash-lite" in lowered:
                return (3, lowered)
            if "flash-latest" in lowered:
                return (4, lowered)
            if "2.0-flash" in lowered and "lite" not in lowered:
                return (5, lowered)
            if "2.0-flash-lite" in lowered:
                return (6, lowered)
            return (10, lowered)

        ordered = sorted(dict.fromkeys(filtered), key=rank)
        return ordered or ["models/gemini-2.5-flash", "models/gemini-flash-lite-latest"]

    def _set_client(self, model_name: str) -> None:
        if self._genai is None:
            raise RuntimeError("Gemini client is not initialized.")
        self.model_name = model_name
        self._client = self._genai.GenerativeModel(model_name=model_name)

    def _probe(self, force: bool = False) -> bool:
        if not self._available or self._genai is None:
            return False
        if self._probed and not force:
            return self._available

        candidates = [m for m in self._candidate_models if m not in self._failed_models]
        if not candidates and self.model_name:
            candidates = [self.model_name]

        for model_name in candidates:
            try:
                self._set_client(model_name)
                resp = self._client.generate_content("Reply with exactly OK.")
                text = (getattr(resp, "text", "") or "").strip()
                if text:
                    self._last_error = ""
                    self._available = True
                    self._probed = True
                    return True
                self._last_error = f"{model_name} returned empty probe response."
                self._failed_models.add(model_name)
            except Exception as exc:
                self._last_error = str(exc)
                self._failed_models.add(model_name)
                continue

        self._available = False
        self._probed = True
        return False

    def is_available(self) -> bool:
        return self._probe()

    def generate(self, prompt: str, system: str = "") -> ProviderResponse:
        if self.is_available():
            try:
                final_prompt = f"{system}\n\n{prompt}" if system else prompt
                resp = self._client.generate_content(final_prompt)
                usage = getattr(resp, "usage_metadata", None)
                in_toks = getattr(usage, "prompt_token_count", 0) or 0
                out_toks = getattr(usage, "candidates_token_count", 0) or 0
                text = getattr(resp, "text", "") or ""
                if not text:
                    text = "Model returned empty text."
                self._last_error = ""
                return ProviderResponse(text=text, input_tokens=in_toks, output_tokens=out_toks, model=self.model_name)
            except Exception as exc:
                self._last_error = str(exc)
                if self.model_name:
                    self._failed_models.add(self.model_name)
                self._probed = False
                self._available = True
                if self._probe(force=True):
                    return self.generate(prompt, system=system)
                self._available = False

        estimate_in = max(1, len(prompt) // 4)
        reason = self._last_error or "Gemini unavailable."
        output = f"Offline fallback: {reason}"
        estimate_out = max(1, len(output) // 4)
        return ProviderResponse(text=output, input_tokens=estimate_in, output_tokens=estimate_out, model="offline-fallback")
