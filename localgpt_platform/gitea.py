from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .config import GiteaConfig
from .result import PlatformError


class GiteaClient:
    def __init__(self, config: GiteaConfig):
        self.config = config

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        require_token: bool = True,
        step: str | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        response = await self._request(
            method,
            path,
            params=params,
            json_body=json_body,
            require_token=require_token,
        )
        evidence = self._evidence(method, path, response, params=params, step=step)
        if not response.content:
            return None, evidence
        try:
            return response.json(), evidence
        except ValueError as exc:
            raise PlatformError(
                "invalid_json",
                "Gitea 返回了非 JSON 响应",
                {"path": path, "status_code": response.status_code},
            ) from exc

    async def request_text(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        require_token: bool = True,
        step: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        response = await self._request(
            method,
            path,
            params=params,
            require_token=require_token,
        )
        return response.text, self._evidence(method, path, response, params=params, step=step)

    async def download(
        self,
        path: str,
        target_path: Path,
        *,
        params: dict[str, Any] | None = None,
        step: str | None = None,
    ) -> dict[str, Any]:
        response = await self._request("GET", path, params=params, require_token=True)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(response.content)
        evidence = self._evidence("GET", path, response, params=params, step=step)
        evidence["download_path"] = str(target_path)
        evidence["bytes"] = len(response.content)
        evidence["content_type"] = response.headers.get("content-type", "")
        return evidence

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        require_token: bool = True,
    ) -> httpx.Response:
        headers = {"Accept": "application/json"}
        if self.config.token:
            headers["Authorization"] = f"token {self.config.token}"
        elif require_token:
            raise PlatformError(
                "missing_token",
                "缺少 GITEA_TOKEN 环境变量",
                {"env": "GITEA_TOKEN"},
            )

        url = f"{self.config.api_base_url}{path}"
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout,
                verify=self.config.verify_ssl,
                follow_redirects=True,
            ) as client:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise PlatformError(
                "request_timeout",
                "请求 Gitea API 超时",
                {"method": method, "path": path},
            ) from exc
        except httpx.HTTPError as exc:
            raise PlatformError(
                "request_failed",
                "请求 Gitea API 失败",
                {"method": method, "path": path, "error": str(exc)},
            ) from exc

        if response.status_code >= 400:
            raise PlatformError(
                "gitea_api_error",
                "Gitea API 返回错误状态码",
                {
                    "method": method,
                    "path": path,
                    "status_code": response.status_code,
                    "body_preview": response.text[:1000],
                },
            )
        return response

    def _evidence(
        self,
        method: str,
        path: str,
        response: httpx.Response,
        *,
        params: dict[str, Any] | None = None,
        step: str | None = None,
    ) -> dict[str, Any]:
        value: dict[str, Any] = {
            "step": step or path.strip("/") or "request",
            "provider": "gitea",
            "base_url": self.config.base_url,
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "x_total_count": response.headers.get("x-total-count"),
            "link": response.headers.get("link"),
        }
        if params:
            value["params_summary"] = summarize_params(params)
        return value


def summarize_params(params: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in params.items():
        lowered = str(key).lower()
        if "token" in lowered or "secret" in lowered or "password" in lowered:
            safe[key] = "<redacted>"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            text = str(value) if isinstance(value, str) else value
            safe[key] = f"{text[:117]}..." if isinstance(text, str) and len(text) > 120 else text
        else:
            safe[key] = f"<{type(value).__name__}>"
    return safe


def repo_path(repo: str, suffix: str = "") -> str:
    owner, name = parse_repo(repo)
    base = f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"
    return f"{base}{suffix}"


def parse_repo(repo: str) -> tuple[str, str]:
    value = (repo or "").strip().strip("/")
    parts = value.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise PlatformError(
            "invalid_repo",
            "repo 必须使用 owner/repo 格式",
            {"repo": repo},
        )
    return parts[0], parts[1]


def extension_for_content_type(content_type: str) -> str:
    if not content_type:
        return ".bin"
    mime = content_type.split(";", 1)[0].strip().lower()
    return mimetypes.guess_extension(mime) or ".bin"
