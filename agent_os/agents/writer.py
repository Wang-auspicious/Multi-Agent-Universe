from __future__ import annotations

from agent_os.providers.base import ProviderBase


class WriterAgent:
    def __init__(self, provider: ProviderBase) -> None:
        self.provider = provider

    def system_prompt(self) -> str:
        return (
            "You are the Writer agent in a collaborative coding workflow. "
            "Your job is to write or rewrite docs, readme text, task summaries, explanations, and user-facing copy. "
            "When the user wants exact file contents, preserve the original wording instead of summarizing. "
            "Return JSON only when operating through the tool loop."
        )
