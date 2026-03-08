from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class LogEntry:
    agent: str
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))


# CLI 模式下的全局日志列表
_log: list[LogEntry] = []


def log(agent: str, message: str, callback=None) -> LogEntry:
    # 强制确保 agent 和 message 为字符串且可处理中文
    safe_agent = str(agent)
    safe_message = str(message)
    
    entry = LogEntry(agent=safe_agent, message=safe_message)
    _log.append(entry)
    
    if callback:
        try:
            callback(entry)
        except Exception:
            # 如果回调失败（例如编码问题），忽略它以防止中断主流程
            pass
    return entry


def get_all() -> list[LogEntry]:
    return list(_log)


def clear() -> None:
    _log.clear()
