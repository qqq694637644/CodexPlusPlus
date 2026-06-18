from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlatformError(Exception):
    code: str
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            value["details"] = self.details
        return value


def ok_result(
    *,
    operation: str,
    data: Any,
    evidence: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "operation": operation,
        "data": data,
    }
    if meta:
        result["meta"] = meta
    if evidence:
        result["evidence"] = evidence
    return result


def error_result(
    *,
    operation: str,
    error: PlatformError,
    evidence: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "operation": operation,
        "error": error.to_dict(),
    }
    if meta:
        result["meta"] = meta
    if evidence:
        result["evidence"] = evidence
    return result
