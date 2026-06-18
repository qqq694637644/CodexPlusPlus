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


def _evidence_list(evidence: Any | None) -> list[dict[str, Any]]:
    if evidence is None:
        return []
    if isinstance(evidence, list):
        return [entry for entry in evidence if isinstance(entry, dict)]
    if isinstance(evidence, dict):
        return [evidence]
    return []


def ok_result(
    *,
    operation: str,
    data: Any,
    evidence: Any | None = None,
    meta: dict[str, Any] | None = None,
    warnings: list[Any] | None = None,
    next_suggested_operations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": operation,
        "data": data,
        "meta": meta or {},
        "evidence": _evidence_list(evidence),
        "warnings": warnings or [],
        "next_suggested_operations": next_suggested_operations or [],
        "error": None,
    }


def error_result(
    *,
    operation: str,
    error: PlatformError,
    evidence: Any | None = None,
    meta: dict[str, Any] | None = None,
    warnings: list[Any] | None = None,
    next_suggested_operations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "operation": operation,
        "data": None,
        "meta": meta or {},
        "evidence": _evidence_list(evidence),
        "warnings": warnings or [],
        "next_suggested_operations": next_suggested_operations or [],
        "error": error.to_dict(),
    }
