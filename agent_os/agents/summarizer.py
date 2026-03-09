from __future__ import annotations

from agent_os.providers.base import ProviderBase


class SummarizerAgent:
    def __init__(self, provider: ProviderBase) -> None:
        self.provider = provider

    def _humanize_local(self, goal: str, coder_output: dict[str, object], review: dict[str, object]) -> str:
        summary = str(coder_output.get("summary", "")).strip()
        executor = str(coder_output.get("executor", "unknown"))

        if any(token in goal for token in ("查看我的本地文件", "访问本地文件", "本地文件吗")):
            return "可以。我能读取和修改当前仓库目录内的文件；你直接说要看哪个文件或要改什么即可。"

        if not summary:
            summary = "任务已完成。"

        return (
            f"已完成。执行器：{executor}。\n"
            f"审查结果：{review.get('feedback', 'Approved')}。\n"
            f"结果：{summary[:1200]}"
        )

    def summarize(self, goal: str, coder_output: dict[str, object], review: dict[str, object]) -> tuple[str, int]:
        executor = str(coder_output.get("executor", ""))
        raw_summary = str(coder_output.get("summary", "")).strip()

        if executor in {"local_agent", "collab_agent"}:
            text = raw_summary or self._humanize_local(goal, coder_output, review)
            est_tokens = max(1, len(text) // 4)
            return text, est_tokens

        prompt = (
            "请用简洁中文直接回答用户，不要使用 markdown 表格，不要写 workflow summary。\n"
            "如果是能力问题，先直接回答 可以/不可以。\n"
            "如果创建或修改了文件，明确说出文件名和结果。\n"
            "尽量控制在 3 行内。\n\n"
            f"用户任务: {goal}\n"
            f"执行器输出: {raw_summary}\n"
            f"审查结果: {review}\n"
        )
        resp = self.provider.generate(prompt, system="你是 coding agent 的中文总结器。")

        if resp.model == "offline-fallback":
            text = self._humanize_local(goal, coder_output, review)
            return text, resp.input_tokens + resp.output_tokens

        text = (resp.text or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.replace("markdown", "", 1).strip()
        return text or self._humanize_local(goal, coder_output, review), resp.input_tokens + resp.output_tokens
