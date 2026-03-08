from __future__ import annotations

import os
import sys

import google.generativeai as genai
from dotenv import load_dotenv

from agents.orchestrator import run as orchestrate
from agents.agent_log import get_all, clear
from agents.cost_tracker import get as get_tracker

os.environ["http_proxy"] = "http://127.0.0.1:7897"
os.environ["https_proxy"] = "http://127.0.0.1:7897"

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"), transport="rest")


def _build_gemini_chat():
    models = [
        m.name for m in genai.list_models()
        if "generateContent" in m.supported_generation_methods
    ]
    if not models:
        raise RuntimeError("No available Gemini models.")
    target = next((m for m in models if "flash" in m), models[0])
    print(f"✅ Gemini 对话模型: {target}")
    model = genai.GenerativeModel(
        model_name=target,
        system_instruction="你是一个高级助理，请简短回答。",
    )
    return model.start_chat(enable_automatic_function_calling=True)


def run_cli() -> None:
    print("=" * 55)
    print("  Multi-Agent Universe — CLI 模式")
    print("  含「搜索/查询」→ SearchAgent + AnalysisAgent")
    print("  其他输入 → Gemini 对话 | 输入 exit 退出")
    print("=" * 55)

    tracker = get_tracker()
    chat = _build_gemini_chat()

    while True:
        try:
            user_input = input("\n你: ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        clear()  # 清空本轮日志

        def cli_log(entry):
            print(f"  [{entry.timestamp}] {entry.agent}: {entry.message}")

        result, tracker = orchestrate(user_input, tracker=tracker, log_cb=cli_log)

        print(f"\n{tracker.metrics_str()}")

        if result:
            print(f"\n🔍 分析结果:\n{result}")
        else:
            resp = chat.send_message(user_input)
            print(f"\n🤖 Gemini: {resp.text}")


def run_dashboard() -> None:
    import subprocess
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "dashboard.py"],
        check=True,
        env=env
    )


if __name__ == "__main__":
    if "--dashboard" in sys.argv or "-d" in sys.argv:
        run_dashboard()
    else:
        run_cli()
