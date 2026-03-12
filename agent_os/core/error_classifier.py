from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ErrorClassification:
    error_type: str
    severity: str  # "low", "medium", "high"
    recoverable: bool
    suggested_strategy: str


def classify_error(error_text: str, context: dict[str, object] | None = None) -> ErrorClassification:
    """Classify error based on text patterns and context."""
    error_lower = error_text.lower()
    context = context or {}

    # Syntax errors
    if any(pattern in error_lower for pattern in ["syntaxerror", "invalid syntax", "unexpected indent", "unexpected eof"]):
        return ErrorClassification(
            error_type="SyntaxError",
            severity="medium",
            recoverable=True,
            suggested_strategy="rewrite_with_syntax_fix"
        )

    # Import errors
    if any(pattern in error_lower for pattern in ["importerror", "modulenotfounderror", "no module named", "cannot import"]):
        return ErrorClassification(
            error_type="ImportError",
            severity="medium",
            recoverable=True,
            suggested_strategy="add_missing_import_or_install"
        )

    # Name/Attribute errors
    if any(pattern in error_lower for pattern in ["nameerror", "name", "is not defined", "attributeerror", "has no attribute"]):
        return ErrorClassification(
            error_type="NameError",
            severity="medium",
            recoverable=True,
            suggested_strategy="fix_variable_or_attribute_name"
        )

    # Type errors
    if any(pattern in error_lower for pattern in ["typeerror", "type", "expected", "got"]):
        return ErrorClassification(
            error_type="TypeError",
            severity="medium",
            recoverable=True,
            suggested_strategy="fix_type_mismatch"
        )

    # File/Path errors
    if any(pattern in error_lower for pattern in ["filenotfounderror", "no such file", "file not found", "path does not exist"]):
        return ErrorClassification(
            error_type="FileNotFoundError",
            severity="low",
            recoverable=True,
            suggested_strategy="create_missing_file_or_fix_path"
        )

    # Permission errors
    if any(pattern in error_lower for pattern in ["permissionerror", "permission denied", "access denied"]):
        return ErrorClassification(
            error_type="PermissionError",
            severity="high",
            recoverable=False,
            suggested_strategy="request_user_intervention"
        )

    # Network/API errors
    if any(pattern in error_lower for pattern in ["connectionerror", "timeout", "connection refused", "network", "api error", "rate limit"]):
        return ErrorClassification(
            error_type="NetworkError",
            severity="medium",
            recoverable=True,
            suggested_strategy="retry_with_backoff"
        )

    # Tool execution errors
    if any(pattern in error_lower for pattern in ["tool failed", "command failed", "execution failed", "patch failed"]):
        return ErrorClassification(
            error_type="ToolError",
            severity="medium",
            recoverable=True,
            suggested_strategy="fallback_to_alternative_tool"
        )

    # Indentation errors
    if any(pattern in error_lower for pattern in ["indentationerror", "unexpected indent", "unindent"]):
        return ErrorClassification(
            error_type="IndentationError",
            severity="low",
            recoverable=True,
            suggested_strategy="fix_indentation"
        )

    # Runtime errors (generic)
    if any(pattern in error_lower for pattern in ["runtimeerror", "runtime error"]):
        return ErrorClassification(
            error_type="RuntimeError",
            severity="medium",
            recoverable=True,
            suggested_strategy="analyze_and_fix_logic"
        )

    # Default: unknown error
    return ErrorClassification(
        error_type="UnknownError",
        severity="medium",
        recoverable=True,
        suggested_strategy="generic_retry"
    )


def should_retry(classification: ErrorClassification, retry_count: int, max_retries: int = 3) -> bool:
    """Determine if error should be retried based on classification and retry count."""
    if retry_count >= max_retries:
        return False

    if not classification.recoverable:
        return False

    # High severity errors get fewer retries
    if classification.severity == "high" and retry_count >= 1:
        return False

    return True


def get_backoff_delay(retry_count: int) -> float:
    """Calculate exponential backoff delay in seconds."""
    return min(2 ** retry_count, 8)  # Cap at 8 seconds
