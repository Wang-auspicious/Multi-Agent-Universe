from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PermissionPolicy:
    repo_path: Path
    command_whitelist: set[str] = field(
        default_factory=lambda: {"git", "python", "pytest", "node", "npm", "pnpm"}
    )
    blocked_path_fragments: tuple[str, ...] = (".env", "id_rsa", "id_ed25519", "secret", "token")
    blocked_tokens: tuple[str, ...] = ("rm -rf", "del /f", "format", "shutdown", "reboot", "deploy", "push")

    def validate_command(self, command: str) -> tuple[bool, str]:
        lowered = command.lower()
        for token in self.blocked_tokens:
            if token in lowered:
                return False, f"Command blocked by token: {token}"
        try:
            head = shlex.split(command, posix=False)[0]
        except Exception:
            return False, "Unable to parse command"
        root = head.lower().replace(".exe", "")
        if root not in self.command_whitelist:
            return False, f"Command not in whitelist: {root}"
        return True, "ok"

    def validate_path(self, path: Path) -> tuple[bool, str]:
        resolved = path.resolve()
        repo = self.repo_path.resolve()
        if repo not in resolved.parents and resolved != repo:
            return False, "Path is outside repository"
        lowered = str(resolved).lower()
        for fragment in self.blocked_path_fragments:
            if fragment in lowered:
                return False, f"Path blocked by fragment: {fragment}"
        return True, "ok"
