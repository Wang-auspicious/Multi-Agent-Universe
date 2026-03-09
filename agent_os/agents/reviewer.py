from __future__ import annotations


class ReviewerAgent:
    def review(self, coder_output: dict[str, object]) -> dict[str, object]:
        artifacts = coder_output.get("artifacts", [])
        failures: list[str] = []
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            code = item.get("exit_code", 0)
            cmd = item.get("command", "")
            if isinstance(code, int) and code != 0:
                failures.append(f"Command failed ({cmd}): exit_code={code}")

        approved = len(failures) == 0
        feedback = "Approved" if approved else "\n".join(failures)
        return {
            "approved": approved,
            "feedback": feedback,
            "risk_points": failures,
        }
