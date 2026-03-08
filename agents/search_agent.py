from __future__ import annotations

import os
from typing import Callable

import google.generativeai as genai
from dotenv import load_dotenv

from Tools.web_search import SearchError, web_search
from agents.agent_log import LogEntry, log
from agents.cost_tracker import CostTracker

load_dotenv()

os.environ.setdefault("http_proxy", "http://127.0.0.1:7897")
os.environ.setdefault("https_proxy", "http://127.0.0.1:7897")

genai.configure(api_key=os.getenv("GEMINI_API_KEY"), transport="rest")

_flash: genai.GenerativeModel | None = None


def _get_flash() -> genai.GenerativeModel:
    """懒加载：运行时动态选最新可用 Flash 模型，避免 v1beta 废弃路径。"""
    global _flash
    if _flash is not None:
        return _flash
    available = [
        m.name for m in genai.list_models()
        if "generateContent" in m.supported_generation_methods
    ]
    # 优先 flash-2，其次任意 flash，兜底第一个可用模型
    target = (
        next((m for m in available if "flash-2" in m or "2.0-flash" in m or "2.5-flash" in m), None)
        or next((m for m in available if "flash" in m), None)
        or available[0]
    )
    _flash = genai.GenerativeModel(
        model_name=target,
        system_instruction="你是搜索关键词优化专家。将用户输入提炼为最精准的搜索词，直接输出关键词，不加任何解释。",
    )
    return _flash


def run(
    query: str,
    tracker: CostTracker | None = None,
    log_cb: Callable[[LogEntry], None] | None = None,
) -> list[dict[str, str]]:
    log("SearchAgent", f"收到查询: {query}", log_cb)

    # Gemini Flash 优化查询词（懒加载模型）
    try:
        resp = _get_flash().generate_content(query)
        refined = resp.text.strip()
        # Gemini Flash token 计费
        if tracker and hasattr(resp, "usage_metadata"):
            tracker.add(
                resp.usage_metadata.prompt_token_count or 0,
                resp.usage_metadata.candidates_token_count or 0,
                model="gemini-flash",
            )
        log("SearchAgent", f"Gemini Flash 优化查询词 → {refined}", log_cb)
    except Exception as e:
        refined = query
        log("SearchAgent", f"关键词优化失败，使用原始输入: {e}", log_cb)

    # 调用 Tavily 搜索
    log("SearchAgent", f"调用 Tavily 搜索: {refined}", log_cb)
    try:
        results = web_search(refined, num_results=5)
        log("SearchAgent", f"获取到 {len(results)} 条结果", log_cb)
    except SearchError as e:
        log("SearchAgent", f"搜索失败: {e}", log_cb)
        raise

    return results
