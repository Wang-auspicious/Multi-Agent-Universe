from __future__ import annotations

import os
from typing import Callable

import google.generativeai as genai
from dotenv import load_dotenv

from agents.agent_log import LogEntry, log
from agents.cost_tracker import CostTracker

load_dotenv()

# ──────────────────────────────────────────────────────────────────────────────
# 配置 Gemini
# ──────────────────────────────────────────────────────────────────────────────
os.environ.setdefault("http_proxy", "http://127.0.0.1:7897")
os.environ.setdefault("https_proxy", "http://127.0.0.1:7897")

genai.configure(api_key=os.getenv("GEMINI_API_KEY"), transport="rest")

_cached_model: genai.GenerativeModel | None = None

def _get_working_model() -> genai.GenerativeModel:
    """动态探测并锁定一个可用的 Flash 模型 (严格排除 2.x 系列)"""
    global _cached_model
    if _cached_model:
        return _cached_model
        
    try:
        available = [
            m.name for m in genai.list_models()
            if "generateContent" in m.supported_generation_methods
        ]
        
        # 优先级：1. 强制 1.5-flash -> 2. 避开 2.x 的其他 flash -> 3. 兜底
        target = (
            next((m for m in available if "1.5-flash" in m.lower()), None)
            or next((m for m in available if "flash" in m.lower() and "2." not in m), None)
            or available[0]
        )
        
        _cached_model = genai.GenerativeModel(
            model_name=target,
            system_instruction=(
                "你是专业的信息分析师。"
                "请对给定的搜索结果进行深度分析，提炼核心观点、对比不同来源，"
                "输出结构化的中文分析报告（含摘要、要点、来源评估）。"
            ),
        )
        return _cached_model
    except Exception:
        # 最后的保底手动尝试
        return genai.GenerativeModel("models/gemini-1.5-flash")

def run(
    query: str,
    results: list[dict[str, str]],
    tracker: CostTracker | None = None,
    log_cb: Callable[[LogEntry], None] | None = None,
) -> str:
    log("AnalysisAgent", f"开始深度分析 {len(results)} 条搜索结果...", log_cb)

    # 动态获取当前账户下真正叫什么的那个模型
    model = _get_working_model()
    log("AnalysisAgent", f"探测到可用模型: {model.model_name}", log_cb)

    # 构建分析上下文
    context = f"用户问题：{query}\n\n搜索结果：\n"
    for i, r in enumerate(results, 1):
        context += f"\n[{i}] 标题: {r['title']}\n摘要: {r['snippet']}\n来源: {r['link']}\n"

    try:
        # Gemini 调用
        resp = model.generate_content(context)
        analysis = resp.text
        
        # 计费统计
        if tracker and hasattr(resp, "usage_metadata"):
            in_tok = resp.usage_metadata.prompt_token_count or 0
            out_tok = resp.usage_metadata.candidates_token_count or 0
            cost = tracker.add(in_tok, out_tok, model="gemini-flash")
            log(
                "AnalysisAgent",
                f"分析完成 | tokens: in={in_tok} out={out_tok} | cost=${cost:.4f}",
                log_cb,
            )
        else:
            log("AnalysisAgent", "分析完成", log_cb)

    except Exception as e:
        log("AnalysisAgent", f"分析失败: {e}", log_cb)
        raise

    return analysis
