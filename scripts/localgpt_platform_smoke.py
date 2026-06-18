from __future__ import annotations

import asyncio
import io
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from localgpt_platform.operations import (
    HANDLERS,
    OPERATION_SPECS,
    artifact_sync_for_run,
    ci_prepare_failure_context,
    describe_operations,
    execute_operation,
    pr_preflight,
)
import localgpt_platform.operations as operations_module
from localgpt_platform.result import PlatformError


class FakeGiteaClient:
    def __init__(self, *, broken: str | None = None) -> None:
        self.broken = broken

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
        evidence = {"step": step or path, "method": method, "path": path, "status_code": 200, "params_summary": params or {}}
        if path.endswith("/pulls/7"):
            return {
                "number": 7,
                "state": "open",
                "title": "Test",
                "head": {"sha": "abc", "ref": "gpt/x"},
                "base": {"sha": "def", "ref": "main"},
            }, evidence
        if path.endswith("/pulls/7/files"):
            if self.broken == "pr_files":
                return {"broken_files": []}, evidence
            return [{"filename": "a.py", "status": "modified", "additions": 1, "deletions": 0, "changes": 1}], evidence
        if path.endswith("/actions/runs"):
            if self.broken == "runs":
                return {"broken_runs": []}, evidence
            return {"workflow_runs": [{"id": 10, "status": "failure", "conclusion": "failure", "head_sha": "abc"}]}, evidence
        if path.endswith("/actions/runs/10"):
            return {"id": 10, "status": "failure", "conclusion": "failure", "head_sha": "abc"}, evidence
        if path.endswith("/actions/runs/10/jobs"):
            if self.broken == "jobs":
                return {"broken_jobs": [{"id": 99}]}, evidence
            return {"jobs": [{"id": 99, "name": "test", "status": "failure", "conclusion": "failure"}]}, evidence
        if path.endswith("/actions/runs/10/artifacts"):
            if self.broken == "artifacts":
                return {"broken_artifacts": []}, evidence
            return {"artifacts": [{"id": 123, "name": "test-results", "size_in_bytes": 3}]}, evidence
        raise AssertionError(path)

    async def request_text(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        require_token: bool = True,
        step: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        return "failed log", {"step": step or path, "method": method, "path": path, "status_code": 200}

    async def download(
        self,
        path: str,
        target_path: Path,
        *,
        params: dict[str, Any] | None = None,
        step: str | None = None,
    ) -> dict[str, Any]:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("result.txt", "ok")
        target_path.write_bytes(buffer.getvalue())
        return {"step": step or path, "method": "GET", "path": path, "status_code": 200, "download_path": str(target_path), "bytes": target_path.stat().st_size}


class FakeConfig:
    base_url = "https://gitea.example"
    token = "bad-token"
    timeout = 30
    verify_ssl = True

    @property
    def api_base_url(self) -> str:
        return f"{self.base_url}/api/v1"


class BadAuthClient:
    def __init__(self, config: FakeConfig) -> None:
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
        if path == "/version":
            return {"version": "1.2.3"}, {"step": step or path, "method": method, "path": path, "status_code": 200}
        if path == "/user":
            raise PlatformError("gitea_api_error", "auth failed", {"status_code": 401})
        raise AssertionError(path)


async def expect_shape_error(coro: Any) -> None:
    try:
        await coro
    except PlatformError as exc:
        assert exc.code == "unexpected_response_shape", exc.to_dict()
        details = exc.details or {}
        assert details.get("actual_keys"), details
        assert details.get("expected"), details
        return
    raise AssertionError("expected unexpected_response_shape")


async def main() -> None:
    assert set(OPERATION_SPECS) == set(HANDLERS)
    assert "actions.get_job_log" not in OPERATION_SPECS

    assert describe_operations(category="artifact", detail="brief")["ok"] is True
    invalid_category = describe_operations(category="nope")
    assert invalid_category["ok"] is False
    assert invalid_category["error"]["code"] == "invalid_category"
    full = describe_operations(operation="ci.prepare_failure_context", detail="full")
    assert full["ok"] is True
    assert full["operation"]["writes_local_files"] is True

    forbidden = await execute_operation("actions.download_artifact", repo="owner/repo", params={"target_dir": "x"})
    assert forbidden["ok"] is False
    assert forbidden["error"]["code"] == "forbidden_param", forbidden
    missing = await execute_operation("ci.prepare_failure_context", repo="owner/repo", params={})
    assert missing["ok"] is False
    assert missing["error"]["code"] == "missing_param", missing

    original_config_loader = operations_module.load_gitea_config
    original_client = operations_module.GiteaClient
    try:
        operations_module.load_gitea_config = lambda *, require_token=True: FakeConfig()  # type: ignore[assignment]
        operations_module.GiteaClient = BadAuthClient  # type: ignore[assignment]
        status = await operations_module.check_status()
        assert status["ok"] is False, status
        assert status["error"]["code"] == "gitea_api_error", status
    finally:
        operations_module.load_gitea_config = original_config_loader  # type: ignore[assignment]
        operations_module.GiteaClient = original_client  # type: ignore[assignment]

    client = FakeGiteaClient()
    pr = await pr_preflight(client, "owner/repo", {"pr_number": 7})
    assert pr["ok"] is True
    assert pr["data"]["head_sha"] == "abc"
    assert pr["next_suggested_operations"] == ["ci.prepare_failure_context"]

    with tempfile.TemporaryDirectory() as tmp:
        ci = await ci_prepare_failure_context(client, "owner/repo", {"cwd": tmp, "run_id": 10})
        assert ci["ok"] is True
        assert ci["data"]["failed_job_count"] == 1
        assert ci["data"]["log_paths"]
        assert Path(ci["data"]["log_paths"][0]).read_text(encoding="utf-8") == "failed log"

        sync = await artifact_sync_for_run(client, "owner/repo", {"cwd": tmp, "run_id": 10, "artifact_name_pattern": "test-*"})
        assert sync["ok"] is True
        assert sync["data"]["file_count"] == 1
        assert Path(sync["data"]["manifest_path"]).is_file()

        await expect_shape_error(ci_prepare_failure_context(FakeGiteaClient(broken="jobs"), "owner/repo", {"cwd": tmp, "run_id": 10}))
        await expect_shape_error(artifact_sync_for_run(FakeGiteaClient(broken="artifacts"), "owner/repo", {"cwd": tmp, "run_id": 10}))
        await expect_shape_error(pr_preflight(FakeGiteaClient(broken="pr_files"), "owner/repo", {"pr_number": 7}))
        await expect_shape_error(pr_preflight(FakeGiteaClient(broken="runs"), "owner/repo", {"pr_number": 7}))

    print("localgpt platform smoke passed")


if __name__ == "__main__":
    asyncio.run(main())
