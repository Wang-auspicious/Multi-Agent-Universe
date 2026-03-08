
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()

_TAVILY_KEY: str | None = os.getenv("TAVILY_KEY")


class SearchError(Exception):
    pass


def web_search(
    query: str,
    num_results: int = 5,
) -> list[dict[str, str]]:
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")

    if not _TAVILY_KEY:
        raise EnvironmentError("TAVILY_KEY not found in environment variables")

    try:
        client = TavilyClient(api_key=_TAVILY_KEY)
        response: dict[str, Any] = client.search(
            query=query.strip(),
            max_results=num_results,
            search_depth="basic",
        )
    except Exception as e:
        raise SearchError(f"Tavily search failed: {e}") from e

    results: list[dict[str, str]] = [
        {
            "title": item.get("title", ""),
            "link": item.get("url", ""),
            "snippet": item.get("content", ""),
        }
        for item in response.get("results", [])
        if isinstance(item, dict)
    ]

    return results
