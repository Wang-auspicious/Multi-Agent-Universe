from __future__ import annotations

import os
import sys
import io
import traceback
import streamlit as st
import google.generativeai as genai
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────────────────────
# 强制环境编码修复 (必须在所有导入前尽可能早)
# ──────────────────────────────────────────────────────────────────────────────
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import streamlit as st
import google.generativeai as genai
from dotenv import load_dotenv

# ── 基础配置 & 代理设置 ────────────────────────────────────────────────────────
load_dotenv()
os.environ.setdefault("http_proxy", "http://127.0.0.1:7897")
os.environ.setdefault("https_proxy", "http://127.0.0.1:7897")

st.set_page_config(page_title="Multi-Agent Universe", page_icon="🤖", layout="wide")

from agents.cost_tracker import CostTracker
from agents.agent_log import LogEntry
from agents.orchestrator import run as orchestrate

BUDGET = 3.97

# ── Session State 初始化 ──────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "tracker" not in st.session_state:
    st.session_state.tracker = CostTracker(budget=BUDGET)

# ── 辅助函数：动态获取可用的 Gemini 模型 ──────────────────────────────────────
def get_fallback_model():
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"), transport="rest")
    try:
        available = [
            m.name for m in genai.list_models()
            if "generateContent" in m.supported_generation_methods
        ]
        # 严格过滤：锁定 1.5-flash，避开 2.x
        target = (
            next((m for m in available if "1.5-flash" in m.lower()), None) or
            next((m for m in available if "flash" in m.lower() and "2." not in m), None) or
            available[0]
        )
        return genai.GenerativeModel(
            model_name=target,
            system_instruction="你是一个高级助理，请简短回答。",
        )
    except Exception:
        return genai.GenerativeModel("models/gemini-1.5-flash")

# ── 侧边栏 ────────────────────────────────────────────────────────────────────
def render_sidebar(tracker: CostTracker) -> None:
    with st.sidebar:
        st.title("📊 实时监控")
        st.divider()
        col1, col2 = st.columns(2)
        col1.metric("已用金额", f"${tracker.used:.4f}")
        col2.metric("剩余余额", f"${tracker.remaining:.4f}")
        st.divider()
        st.caption(f"累计 Tokens: {tracker.total_tokens:,}")

render_sidebar(st.session_state.tracker)

# ── 主界面 ────────────────────────────────────────────────────────────────────
st.title("🤖 Multi-Agent Universe")
st.divider()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── 输入处理 ──────────────────────────────────────────────────────────────────
if prompt := st.chat_input("输入指令..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        log_container = st.empty()
        result_container = st.empty()
        live_logs: list[LogEntry] = []

        def log_cb(entry: LogEntry) -> None:
            live_logs.append(entry)
            lines = [f"`[{e.timestamp}]` **{e.agent}** — {e.message}" for e in live_logs]
            log_container.markdown("\n".join(lines))

        try:
            result, tracker = orchestrate(
                prompt,
                tracker=st.session_state.tracker,
                log_cb=log_cb,
            )
            st.session_state.tracker = tracker
            log_container.empty()
            
            with st.expander("🔍 Agent 执行日志", expanded=False):
                for e in live_logs:
                    st.caption(f"[{e.timestamp}] **{e.agent}** — {e.message}")

            if result:
                result_container.markdown(result)
                st.session_state.messages.append({"role": "assistant", "content": result})
            else:
                model = get_fallback_model()
                gemini_resp = model.generate_content(prompt)
                answer = gemini_resp.text
                result_container.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})

        except Exception as e:
            log_container.empty()
            error_details = traceback.format_exc()
            result_container.error(f"❌ 执行失败: {e}")
            with st.expander("📄 错误详情 (Traceback)", expanded=True):
                st.code(error_details)
            
            st.session_state.messages.append({"role": "assistant", "content": f"❌ 执行失败: {e}"})
            st.stop()

    st.rerun()
