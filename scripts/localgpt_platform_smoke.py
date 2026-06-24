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
    cache_diagnose,
    ci_find_run_candidates,
    ci_get_run_summary,
    ci_prepare_failure_context,
    describe_operations,
    download_artifact,
    execute_operation,
    pr_comment,
    pr_merge,
    pr_publish,
    pr_preflight,
    runner_diagnose_queue,
    workflow_dispatch_and_track,
    workflow_rerun_job,
    workflow_rerun_run,
)
import localgpt_platform.operations.registry as operations_module
from localgpt_platform.result import PlatformError


class FakeGiteaClient:
    REPO = "/repos/owner/repo"

    def __init__(self, *, broken: str | None = None) -> None:
        self.broken = broken
        self.calls: list[dict[str, Any]] = []
        self.routes = self._build_routes()

    def _build_routes(self) -> dict[tuple[str, str], Any]:
        repo = self.REPO
        return {
            ("GET", f"{repo}/actions/workflows/ci.yml/runs"): self._workflow_runs,
            ("POST", f"{repo}/actions/workflows/ci.yml/dispatches"): self._workflow_dispatch,
            ("GET", f"{repo}/pulls/7"): self._get_pr,
            ("PATCH", f"{repo}/pulls/7"): self._patch_pr,
            ("GET", f"{repo}/pulls/7/files"): self._pr_files,
            ("POST", f"{repo}/pulls"): self._create_pr,
            ("POST", f"{repo}/issues/7/comments"): self._create_comment,
            ("POST", f"{repo}/pulls/7/merge"): self._merge_pr,
            ("GET", f"{repo}/actions/runs"): self._runs,
            ("GET", f"{repo}/actions/runs/10"): self._run_10,
            ("POST", f"{repo}/actions/runs/10/rerun"): self._rerun_run_10,
            ("GET", f"{repo}/actions/runs/10/jobs"): self._run_10_jobs,
            ("GET", f"{repo}/actions/jobs/99"): self._job_99,
            ("POST", f"{repo}/actions/jobs/99/rerun"): self._forbid_old_job_rerun,
            ("POST", f"{repo}/actions/runs/10/jobs/99/rerun"): self._rerun_job_99,
            ("GET", f"{repo}/actions/runs/10/artifacts"): self._run_10_artifacts,
            ("GET", f"{repo}/actions/runners"): self._runners,
        }

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
        call = {
            "method": method,
            "path": path,
            "params": params or {},
            "json_body": json_body or {},
            "step": step or path,
        }
        self.calls.append(call)
        evidence = {"step": step or path, "method": method, "path": path, "status_code": 200, "params_summary": params or {}}
        handler = self.routes.get((method, path))
        if handler is None:
            raise AssertionError(f"unexpected route: {method} {path}")
        return handler(params or {}, json_body or {}), evidence

    async def request_text(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        require_token: bool = True,
        step: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        expected_path = f"{self.REPO}/actions/jobs/99/logs"
        if (method, path) != ("GET", expected_path):
            raise AssertionError(f"unexpected text route: {method} {path}")
        self.calls.append({"method": method, "path": path, "params": params or {}, "json_body": {}, "step": step or path})
        return "failed log", {"step": step or path, "method": method, "path": path, "status_code": 200}

    async def download(
        self,
        path: str,
        target_path: Path,
        *,
        params: dict[str, Any] | None = None,
        step: str | None = None,
    ) -> dict[str, Any]:
        expected_path = f"{self.REPO}/actions/artifacts/123/zip"
        if path != expected_path:
            raise AssertionError(f"unexpected download route: {path}")
        self.calls.append({"method": "GET", "path": path, "params": params or {}, "json_body": {}, "step": step or path})
        target_path.parent.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("result.txt", "ok")
        target_path.write_bytes(buffer.getvalue())
        return {"step": step or path, "method": "GET", "path": path, "status_code": 200, "download_path": str(target_path), "bytes": target_path.stat().st_size}

    def assert_called(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None) -> None:
        for call in self.calls:
            if call["method"] != method or call["path"] != path:
                continue
            if params is not None and call["params"] != params:
                continue
            if json_body is not None and call["json_body"] != json_body:
                continue
            return
        raise AssertionError({"expected": {"method": method, "path": path, "params": params, "json_body": json_body}, "calls": self.calls})

    def assert_not_called(self, method: str, path: str) -> None:
        for call in self.calls:
            if call["method"] == method and call["path"] == path:
                raise AssertionError({"unexpected_call": call, "calls": self.calls})

    def assert_no_json_keys(self, *keys: str) -> None:
        forbidden = set(keys)
        for call in self.calls:
            found = forbidden.intersection(call["json_body"])
            if found:
                raise AssertionError({"forbidden_keys": sorted(found), "call": call, "calls": self.calls})

    def _workflow_runs(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        return {"workflow_runs": [{"id": 11, "status": "queued", "head_branch": "main", "head_sha": "abc", "created_at": "2026-01-01T00:00:00Z"}]}

    def _workflow_dispatch(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        assert params == {"return_run_details": True}, params
        assert "return_run_details" not in json_body, json_body
        if self.broken in {"dispatch_no_run_id", "dispatch_tracking_404"}:
            return None
        if self.broken == "dispatch_wrong_shape":
            return {"run_id": 11}
        return {"workflow_run_id": 11, "run_url": "https://gitea.example/api/v1/repos/owner/repo/actions/runs/11", "html_url": "https://gitea.example/owner/repo/actions/runs/11"}

    def _get_pr(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        return {"number": 7, "state": "open", "title": "Test", "head": {"sha": "abc", "ref": "gpt/x"}, "base": {"sha": "def", "ref": "main"}}

    def _patch_pr(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        return {"number": 7, "state": "open", "title": json_body.get("title", "Updated"), "head": {"sha": "abc", "ref": "gpt/x"}, "base": {"sha": "def", "ref": "main"}}

    def _pr_files(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        if self.broken == "pr_files":
            return {"broken_files": []}
        return [{"filename": "a.py", "status": "modified", "additions": 1, "deletions": 0, "changes": 1}]

    def _create_pr(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        return {"number": 8, "state": "open", "title": json_body.get("title", "Created"), "head": {"sha": "abc", "ref": json_body.get("head", "gpt/x")}, "base": {"sha": "def", "ref": json_body.get("base", "main")}}

    def _create_comment(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        return {"id": 900, "html_url": "https://gitea.example/comment/900", "created_at": "2026-01-01T00:00:00Z"}

    def _merge_pr(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        return {"merged": True}

    def _runs(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        if self.broken == "dispatch_tracking_404":
            raise PlatformError(
                "gitea_api_error",
                "Gitea API 返回错误状态码",
                {"method": "GET", "path": f"{self.REPO}/actions/runs", "status_code": 404, "body_preview": "404 page not found\n"},
            )
        if self.broken == "runs":
            return {"broken_runs": []}
        if params.get("event") == "workflow_dispatch":
            return {"workflow_runs": [{"id": 11, "status": "queued", "event": "workflow_dispatch", "head_branch": "main", "head_sha": "abc", "path": "ci.yml@refs/heads/main", "started_at": "2026-01-01T00:00:01Z", "actor": {"login": "alice"}, "trigger_actor": {"login": "alice"}}]}
        if self.broken == "merge_ci_success":
            return {"workflow_runs": [{"id": 30, "status": "success", "conclusion": "success", "head_sha": "abc", "created_at": "2026-01-01T00:00:00Z"}]}
        if self.broken == "merge_ci_in_progress":
            return {"workflow_runs": [
                {"id": 30, "status": "success", "conclusion": "success", "head_sha": "abc", "created_at": "2026-01-01T00:00:00Z"},
                {"id": 31, "status": "in_progress", "conclusion": None, "head_sha": "abc", "created_at": "2026-01-01T00:01:00Z"},
            ]}
        return {"workflow_runs": [{"id": 10, "status": "failure", "conclusion": "failure", "head_sha": "abc", "created_at": "2026-01-01T00:00:00Z"}]}

    def _run_10(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        return {"id": 10, "status": "failure", "conclusion": "failure", "head_sha": "abc"}

    def _rerun_run_10(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        return {"rerun": "run"}

    def _run_10_jobs(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        if self.broken == "jobs":
            return {"broken_jobs": [{"id": 99}]}
        if self.broken == "workflow_jobs":
            return {"workflow_jobs": [{"id": 99, "name": "test", "status": "failure", "conclusion": "failure"}]}
        return {"jobs": [
            {"id": 99, "name": "test", "status": "failure", "conclusion": "failure"},
            {"id": 100, "name": "queued", "status": "queued", "conclusion": None},
            {"id": 101, "name": "build", "status": "in_progress", "conclusion": None},
        ]}

    def _job_99(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        return {"id": 99, "run_id": 10, "name": "test", "status": "failure", "conclusion": "failure"}

    def _forbid_old_job_rerun(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        raise AssertionError("workflow.rerun_job must use /actions/runs/{run}/jobs/{job_id}/rerun")

    def _rerun_job_99(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        return {"rerun": "job"}

    def _run_10_artifacts(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        if self.broken == "artifacts":
            return {"broken_artifacts": []}
        return {"artifacts": [{"id": 123, "name": "test-results", "size_in_bytes": 3}]}

    def _runners(self, params: dict[str, Any], json_body: dict[str, Any]) -> Any:
        return {"runners": [{"id": 1, "name": "runner-1", "status": "online", "busy": False, "disabled": False, "labels": ["windows-latest"]}]}


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
    for operation in describe_operations(detail="brief")["operations"]:
        assert operation["name"] in OPERATION_SPECS, operation
        assert "name" not in OPERATION_SPECS[operation["name"]], operation
    invalid_category = describe_operations(category="nope")
    assert invalid_category["ok"] is False
    assert invalid_category["error"]["code"] == "invalid_category"
    full = describe_operations(operation="ci.prepare_failure_context", detail="full")
    assert full["ok"] is True
    assert full["operation"]["writes_local_files"] is True

    forbidden = await execute_operation("actions.download_artifact", repo="owner/repo", params={"target_dir": "x"})
    assert forbidden["ok"] is False
    assert forbidden["error"]["code"] == "forbidden_param", forbidden
    typo = await execute_operation("actions.list_runs", repo="owner/repo", params={"limt": 5})
    assert typo["ok"] is False
    assert typo["error"]["code"] == "unknown_param", typo
    assert typo["error"]["details"]["unknown_params"] == ["limt"], typo
    assert "limit" in typo["error"]["details"]["allowed_params"], typo
    combo_typo = await execute_operation("ci.prepare_failure_context", repo="owner/repo", params={"cwd": ".", "runid": 10})
    assert combo_typo["ok"] is False
    assert combo_typo["error"]["code"] == "unknown_param", combo_typo
    assert combo_typo["error"]["details"]["unknown_params"] == ["runid"], combo_typo
    assert "run_id" in combo_typo["error"]["details"]["allowed_params"], combo_typo
    summary_typo = await execute_operation("ci.get_run_summary", repo="owner/repo", params={"runid": 10})
    assert summary_typo["ok"] is False
    assert summary_typo["error"]["code"] == "unknown_param", summary_typo
    write_without_confirm = await execute_operation("workflow.rerun_job", repo="owner/repo", params={"run_id": 10, "job_id": 99})
    assert write_without_confirm["ok"] is False
    assert write_without_confirm["error"]["code"] == "missing_param", write_without_confirm
    write_confirm_false = await execute_operation("workflow.rerun_job", repo="owner/repo", params={"run_id": 10, "job_id": 99, "confirm": False})
    assert write_confirm_false["ok"] is False
    assert write_confirm_false["error"]["code"] == "confirmation_required", write_confirm_false
    write_confirm_string = await execute_operation("workflow.rerun_job", repo="owner/repo", params={"run_id": 10, "job_id": 99, "confirm": "true"})
    assert write_confirm_string["ok"] is False
    assert write_confirm_string["error"]["code"] == "confirmation_required", write_confirm_string
    bad_dispatch_inputs = await execute_operation(
        "workflow.dispatch_and_track",
        repo="owner/repo",
        params={"workflow_id": "ci.yml", "ref": "main", "inputs": {"debug": True, "retries": 3}, "confirm": True},
    )
    assert bad_dispatch_inputs["ok"] is False
    assert bad_dispatch_inputs["error"]["code"] == "invalid_param", bad_dispatch_inputs
    assert bad_dispatch_inputs["error"]["details"]["invalid_entries"] == {"debug": "bool", "retries": "int"}, bad_dispatch_inputs
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
    candidates = await ci_find_run_candidates(client, "owner/repo", {"head_sha": "abc"})
    assert candidates["ok"] is True
    assert candidates["data"]["candidate_count"] == 1
    assert candidates["next_suggested_operations"] == ["ci.get_run_summary"]
    summary = await ci_get_run_summary(client, "owner/repo", {"run_id": 10})
    assert summary["ok"] is True
    assert summary["operation"] == "ci.get_run_summary"
    assert summary["data"]["job_count"] == 3
    assert summary["data"]["failed_like_job_count"] == 1
    assert "failed_cancelled_timed_out_job_count" not in summary["data"], summary
    assert summary["data"]["queued_in_progress_job_count"] == 2
    assert summary["data"]["status_counts"] == {"failure": 1, "in_progress": 1, "queued": 1}
    assert summary["data"]["conclusion_counts"] == {"<missing>": 2, "failure": 1}
    assert summary["data"]["content_returned"] is False
    assert summary["next_suggested_operations"] == ["ci.prepare_failure_context"]
    queue = await runner_diagnose_queue(client, "owner/repo", {"limit": 10})
    assert queue["ok"] is True
    assert queue["data"]["runner_summary"]["runner_count"] == 1
    assert queue["data"]["queued_run_count"] == 1
    cache = await cache_diagnose(client, "owner/repo", {"limit": 10})
    assert cache["ok"] is True
    assert cache["data"]["official_cache_management_api"] is False

    rerun_job = await workflow_rerun_job(client, "owner/repo", {"run_id": 10, "job_id": 99, "expected_status": "failure", "expected_conclusion": "failure", "confirm": True})
    assert rerun_job["ok"] is True
    assert rerun_job["data"]["rerun_response"] == {"rerun": "job"}
    assert any(item["path"].endswith("/actions/runs/10/jobs/99/rerun") for item in rerun_job["evidence"]), rerun_job
    client.assert_called("POST", "/repos/owner/repo/actions/runs/10/jobs/99/rerun", params={}, json_body={})
    client.assert_not_called("POST", "/repos/owner/repo/actions/jobs/99/rerun")
    rerun_run = await workflow_rerun_run(client, "owner/repo", {"run_id": 10, "expected_head_sha": "abc", "expected_status": "failure", "confirm": True})
    assert rerun_run["ok"] is True
    assert rerun_run["data"]["rerun_response"] == {"rerun": "run"}
    dispatch_client = FakeGiteaClient()
    dispatch = await workflow_dispatch_and_track(dispatch_client, "owner/repo", {"workflow_id": "ci.yml", "ref": "main", "confirm": True})
    assert dispatch["ok"] is True
    dispatch_client.assert_called("POST", "/repos/owner/repo/actions/workflows/ci.yml/dispatches", params={"return_run_details": True}, json_body={"ref": "main"})
    dispatch_client.assert_not_called("GET", "/repos/owner/repo/actions/runs")
    dispatch_client.assert_not_called("GET", "/repos/owner/repo/actions/workflows/ci.yml/runs")
    assert dispatch["data"]["workflow_run_id"] == "11"
    assert dispatch["data"]["candidate_count"] == 0
    assert dispatch["data"]["dispatch_run_details"]["workflow_run_id"] == "11"
    assert dispatch["data"]["matched"] is True
    assert dispatch["data"]["match_status"] == "dispatch_run_details"
    dispatch_inputs_client = FakeGiteaClient()
    dispatch_inputs = await workflow_dispatch_and_track(
        dispatch_inputs_client,
        "owner/repo",
        {"workflow_id": "ci.yml", "ref": "main", "inputs": {"env": "prod", "debug": "true"}, "confirm": True},
    )
    assert dispatch_inputs["ok"] is True
    dispatch_inputs_client.assert_called(
        "POST",
        "/repos/owner/repo/actions/workflows/ci.yml/dispatches",
        params={"return_run_details": True},
        json_body={"ref": "main", "inputs": {"env": "prod", "debug": "true"}},
    )
    dispatch_full_ref_client = FakeGiteaClient(broken="dispatch_no_run_id")
    dispatch_full_ref = await workflow_dispatch_and_track(dispatch_full_ref_client, "owner/repo", {"workflow_id": "ci.yml", "ref": "refs/heads/main", "confirm": True})
    assert dispatch_full_ref["ok"] is True
    assert dispatch_full_ref["data"]["workflow_run_id"] == "11"
    dispatch_full_ref_client.assert_called(
        "GET",
        "/repos/owner/repo/actions/runs",
        params={"event": "workflow_dispatch", "branch": "main", "limit": 10},
    )
    dispatch_tag_ref_client = FakeGiteaClient(broken="dispatch_no_run_id")
    dispatch_tag_ref = await workflow_dispatch_and_track(dispatch_tag_ref_client, "owner/repo", {"workflow_id": "ci.yml", "ref": "refs/tags/v1.0.0", "confirm": True})
    assert dispatch_tag_ref["ok"] is True
    assert dispatch_tag_ref["data"]["workflow_run_id"] == "11"
    dispatch_tag_ref_client.assert_called(
        "GET",
        "/repos/owner/repo/actions/runs",
        params={"event": "workflow_dispatch", "limit": 10},
    )
    dispatch_no_run_id_client = FakeGiteaClient(broken="dispatch_no_run_id")
    dispatch_no_run_id = await workflow_dispatch_and_track(dispatch_no_run_id_client, "owner/repo", {"workflow_id": "ci.yml", "ref": "main", "actor": "alice", "created_after": "2026-01-01T00:00:00Z", "confirm": True})
    assert dispatch_no_run_id["ok"] is True
    assert dispatch_no_run_id["data"]["workflow_run_id"] == "11"
    assert dispatch_no_run_id["data"]["match_status"] == "candidate_runs", dispatch_no_run_id
    assert dispatch_no_run_id["data"]["candidate_count"] == 1
    dispatch_no_run_id_client.assert_called("GET", "/repos/owner/repo/actions/runs", params={"event": "workflow_dispatch", "branch": "main", "actor": "alice", "limit": 10})
    assert any(warning["code"] == "missing_dispatch_run_details" for warning in dispatch_no_run_id["warnings"]), dispatch_no_run_id
    dispatch_wrong_shape = await workflow_dispatch_and_track(FakeGiteaClient(broken="dispatch_wrong_shape"), "owner/repo", {"workflow_id": "ci.yml", "ref": "main", "confirm": True})
    assert dispatch_wrong_shape["ok"] is True
    assert dispatch_wrong_shape["data"]["workflow_run_id"] == "11"
    assert dispatch_wrong_shape["data"]["match_status"] == "candidate_runs", dispatch_wrong_shape
    assert any(warning["code"] == "missing_dispatch_workflow_run_id" for warning in dispatch_wrong_shape["warnings"]), dispatch_wrong_shape
    dispatch_tracking_404 = await workflow_dispatch_and_track(FakeGiteaClient(broken="dispatch_tracking_404"), "owner/repo", {"workflow_id": "ci.yml", "ref": "main", "confirm": True})
    assert dispatch_tracking_404["ok"] is True
    assert dispatch_tracking_404["data"]["workflow_run_id"] is None
    assert dispatch_tracking_404["data"]["matched"] is False
    assert dispatch_tracking_404["data"]["match_status"] == "tracking_failed", dispatch_tracking_404
    assert dispatch_tracking_404["data"]["candidate_count"] == 0
    assert any(warning["code"] == "candidate_run_tracking_failed" for warning in dispatch_tracking_404["warnings"]), dispatch_tracking_404

    published = await pr_publish(client, "owner/repo", {"mode": "create", "head": "gpt/x", "base": "main", "title": "Created", "expected_head_sha": "abc", "confirm": True})
    assert published["ok"] is True
    assert published["data"]["created_or_updated"] == "created"
    updated = await pr_publish(client, "owner/repo", {"mode": "update", "existing_pr_number": 7, "title": "Updated", "expected_head_sha": "abc", "confirm": True})
    assert updated["ok"] is True
    assert updated["data"]["created_or_updated"] == "updated"
    comment = await pr_comment(client, "owner/repo", {"pr_number": 7, "body": "hello", "confirm": True})
    assert comment["ok"] is True
    assert comment["data"]["body_length"] == 5
    try:
        await pr_merge(FakeGiteaClient(broken="merge_ci_in_progress"), "owner/repo", {"pr_number": 7, "expected_head_sha": "abc", "base_branch": "main", "merge_method": "merge", "confirm": True})
    except PlatformError as exc:
        assert exc.code == "ci_not_complete", exc.to_dict()
    else:
        raise AssertionError("expected pr.merge to reject in-progress CI")
    merge_success_client = FakeGiteaClient(broken="merge_ci_success")
    merge_success = await pr_merge(merge_success_client, "owner/repo", {"pr_number": 7, "expected_head_sha": "abc", "base_branch": "main", "merge_method": "merge", "confirm": True})
    assert merge_success["ok"] is True
    merge_success_client.assert_called("POST", "/repos/owner/repo/pulls/7/merge", params={}, json_body={"do": "merge", "head_commit_id": "abc"})
    merge_success_client.assert_no_json_keys("Do", "MergeTitleField", "MergeMessageField")
    merge = await pr_merge(client, "owner/repo", {"pr_number": 7, "expected_head_sha": "abc", "base_branch": "main", "merge_method": "merge", "confirm": True, "require_ci_success": False})
    assert merge["ok"] is True
    assert merge["data"]["merge_response"] == {"merged": True}
    client.assert_called("POST", "/repos/owner/repo/pulls/7/merge", params={}, json_body={"do": "merge", "head_commit_id": "abc"})
    client.assert_no_json_keys("Do", "MergeTitleField", "MergeMessageField")

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
        assert "retained_zip_paths" not in sync["data"], sync
        assert Path(sync["data"]["manifest_path"]).is_file()
        manifest = Path(sync["data"]["manifest_path"]).read_text(encoding="utf-8")
        assert '"evidence"' in manifest, manifest
        assert not list(Path(sync["data"]["artifact_dir"]).glob("*.zip")), sync

        single = await download_artifact(client, "owner/repo", {"cwd": tmp, "job_id": 77, "artifact_id": 123, "artifact_name": "single-result"})
        assert single["ok"] is True
        assert "zip_path" not in single["data"], single
        assert "transport_zip_path" not in single["data"], single
        assert "transport_zip_removed" not in single["data"], single
        assert any(item.get("temporary_zip_deleted") is True for item in single["evidence"]), single
        assert not list(Path(single["data"]["artifact_dir"]).glob("*.zip")), single

        await expect_shape_error(ci_prepare_failure_context(FakeGiteaClient(broken="jobs"), "owner/repo", {"cwd": tmp, "run_id": 10}))
        await expect_shape_error(ci_get_run_summary(FakeGiteaClient(broken="workflow_jobs"), "owner/repo", {"run_id": 10}))
        await expect_shape_error(ci_get_run_summary(FakeGiteaClient(broken="jobs"), "owner/repo", {"run_id": 10}))
        await expect_shape_error(artifact_sync_for_run(FakeGiteaClient(broken="artifacts"), "owner/repo", {"cwd": tmp, "run_id": 10}))
        await expect_shape_error(pr_preflight(FakeGiteaClient(broken="pr_files"), "owner/repo", {"pr_number": 7}))
        await expect_shape_error(pr_preflight(FakeGiteaClient(broken="runs"), "owner/repo", {"pr_number": 7}))

    print("localgpt platform smoke passed")


if __name__ == "__main__":
    asyncio.run(main())
