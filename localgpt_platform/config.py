from __future__ import annotations

import os
from dataclasses import dataclass

from .result import PlatformError


@dataclass(frozen=True)
class GiteaConfig:
    base_url: str
    token: str | None
    timeout: float
    verify_ssl: bool

    @property
    def api_base_url(self) -> str:
        return f"{self.base_url}/api/v1"


def load_gitea_config(*, require_token: bool = True) -> GiteaConfig:
    base_url = os.environ.get("GITEA_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        raise PlatformError(
            "missing_base_url",
            "缺少 GITEA_BASE_URL 环境变量",
            {"env": "GITEA_BASE_URL"},
        )
    if not (base_url.startswith("https://") or base_url.startswith("http://")):
        raise PlatformError(
            "invalid_base_url",
            "GITEA_BASE_URL 必须以 http:// 或 https:// 开头",
            {"base_url": base_url},
        )

    token = os.environ.get("GITEA_TOKEN", "").strip() or None
    if require_token and not token:
        raise PlatformError(
            "missing_token",
            "缺少 GITEA_TOKEN 环境变量",
            {"env": "GITEA_TOKEN"},
        )

    timeout_raw = os.environ.get("GITEA_TIMEOUT", "30").strip()
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:
        raise PlatformError(
            "invalid_timeout",
            "GITEA_TIMEOUT 必须是数字",
            {"value": timeout_raw},
        ) from exc
    if timeout <= 0:
        raise PlatformError(
            "invalid_timeout",
            "GITEA_TIMEOUT 必须大于 0",
            {"value": timeout_raw},
        )

    verify_raw = os.environ.get("GITEA_VERIFY_SSL", "true").strip().lower()
    verify_ssl = verify_raw not in {"0", "false", "no"}
    return GiteaConfig(
        base_url=base_url,
        token=token,
        timeout=timeout,
        verify_ssl=verify_ssl,
    )
