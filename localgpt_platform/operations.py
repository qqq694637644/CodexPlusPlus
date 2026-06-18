from __future__ import annotations

import fnmatch
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote

from .config import load_gitea_config
from .gitea import GiteaClient, repo_path
from .result import PlatformError, error_result, ok_result

OperationHandler = Callable[[GiteaClient, str | None, dict[str, Any]], Awaitable[dict[str, Any]]]

_REQUIRED_SPEC_FIELDS = {
    "category",
    "description",
    "repo_required",
    "read_only_remote",
    "writes_local_files",
    "writes_remote",
    "requires_cwd",
    "required_params",
    "optional_params",
    "returns",
    "example",
    "risk_level",
}

_BRIEF_FIELDS = (
    "name",
    "category",
    "description",
    "repo_required",
    "read_only_remote",
    "writes_local_files",
    "writes_remote",
    "requires_cwd",
    "risk_level",
)

_FAILED_CONCLUSIONS = {"failure", "cancelled", "timed_out", "startup_failure", "action_required"}
_FAILED_STATUSES = {"failure", "cancelled", "timed_out"}


def operation_spec(
    *,
    category: str,
    description: str,
    repo_required: bool,
    read_only_remote: bool,
    writes_local_files: bool,
    writes_remote: bool,
    requires_cwd: bool,
    required_params: dict[str, str],
    optional_params: dict[str, str],
    returns: dict[str, str],
    example: dict[str, Any],
    risk_level: str,
) -> dict[str, Any]:
    """Build one operation spec.

    Development-time rule: all metadata fields are explicit at every callsite.
    Do not add default metadata here; missing metadata must break import.
    """
    return {
        "category": category,
        "description": description,
        "repo_required": repo_required,
        "read_only_remote": read_only_remote,
        "writes_local_files": writes_local_files,
        "writes_remote": writes_remote,
        "requires_cwd": requires_cwd,
        "required_params": required_params,
        "optional_params": optional_params,
        "returns": returns,
        "example": example,
        "risk_level": risk_level,
    }


OPERATION_SPECS: dict[str, dict[str, Any]] = {
    "server.version": operation_spec(
        category="server",
        description="读取 Gitea 服务器版本。",
        repo_required=False,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={},
        optional_params={},
        returns={"data": "Gitea /version JSON object。", "evidence": "GET /version 调用证据。"},
        example={"operation": "server.version"},
        risk_level="low",
    ),
    "auth.whoami": operation_spec(
        category="auth",
        description="读取当前 token 对应用户。",
        repo_required=False,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={},
        optional_params={},
        returns={"data": "Gitea /user JSON object。", "evidence": "GET /user 调用证据。"},
        example={"operation": "auth.whoami"},
        risk_level="low",
    ),
    "repo.get": operation_spec(
        category="repo",
        description="读取仓库元数据。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={},
        optional_params={},
        returns={"data": "Gitea repository JSON object。", "evidence": "GET /repos/{owner}/{repo} 调用证据。"},
        example={"operation": "repo.get", "repo": "owner/repo"},
        risk_level="low",
    ),
    "actions.list_workflows": operation_spec(
        category="actions",
        description="列出仓库 Actions workflows。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={},
        optional_params={"page": "integer，页码，1 起始", "limit": "integer，每页数量"},
        returns={"data": "必须是包含 workflows: list[object] 的 Gitea workflows 响应。", "evidence": "含 page/limit 和 result_count 的调用证据。"},
        example={"operation": "actions.list_workflows", "repo": "owner/repo", "params": {"limit": 20}},
        risk_level="low",
    ),
    "actions.get_workflow": operation_spec(
        category="actions",
        description="读取单个 workflow。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={"workflow_id": "string/integer，workflow id 或 workflow 文件名"},
        optional_params={},
        returns={"data": "Gitea workflow JSON object。", "evidence": "GET workflow 调用证据。"},
        example={"operation": "actions.get_workflow", "repo": "owner/repo", "params": {"workflow_id": "ci.yml"}},
        risk_level="low",
    ),
    "actions.list_runs": operation_spec(
        category="ci",
        description="列出 workflow runs。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={},
        optional_params={
            "event": "string，workflow event name",
            "branch": "string，workflow branch",
            "status": "string，pending/queued/in_progress/failure/success/skipped",
            "actor": "string，触发用户",
            "head_sha": "string，触发 commit sha",
            "page": "integer，页码，1 起始",
            "limit": "integer，每页数量",
        },
        returns={"data": "必须是包含 workflow_runs: list[object] 的 Gitea runs 响应。", "evidence": "含过滤参数和 result_count 的调用证据。"},
        example={"operation": "actions.list_runs", "repo": "owner/repo", "params": {"status": "failure", "limit": 10}},
        risk_level="low",
    ),
    "actions.get_run": operation_spec(
        category="ci",
        description="读取单个 workflow run。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={"run_id": "integer/string，workflow run id"},
        optional_params={},
        returns={"data": "Gitea workflow run JSON object。", "evidence": "GET run 调用证据。"},
        example={"operation": "actions.get_run", "repo": "owner/repo", "params": {"run_id": 123}},
        risk_level="low",
    ),
    "ci.get_run_summary": operation_spec(
        category="ci",
        description="查询单个 run 和 jobs，返回紧凑摘要与 job 状态统计，不下载日志。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={"run_id": "integer/string，workflow run id"},
        optional_params={"attempt": "integer/string，指定 run attempt jobs", "page": "integer，jobs 页码，1 起始", "limit": "integer，jobs 每页数量"},
        returns={"data": "run compact summary、jobs compact summary、job_count、failed_cancelled_timed_out_job_count、queued_in_progress_job_count、status_counts、conclusion_counts、content_returned=false。", "evidence": "GET run 和 GET jobs 调用证据。"},
        example={"operation": "ci.get_run_summary", "repo": "owner/repo", "params": {"run_id": 123}},
        risk_level="low",
    ),
    "actions.list_run_jobs": operation_spec(
        category="ci",
        description="列出 run 的 jobs。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={"run_id": "integer/string，workflow run id"},
        optional_params={
            "attempt": "integer/string，指定 attempt 时查询该 attempt 的 jobs",
            "page": "integer，页码，1 起始",
            "limit": "integer，每页数量",
        },
        returns={"data": "必须是包含 jobs 或 workflow_jobs: list[object] 的 Gitea run jobs 响应。", "evidence": "含 page/limit 和 result_count 的调用证据。"},
        example={"operation": "actions.list_run_jobs", "repo": "owner/repo", "params": {"run_id": 123}},
        risk_level="low",
    ),
    "actions.get_job": operation_spec(
        category="ci",
        description="读取单个 job。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={"job_id": "integer/string，job id"},
        optional_params={},
        returns={"data": "Gitea job JSON object。", "evidence": "GET job 调用证据。"},
        example={"operation": "actions.get_job", "repo": "owner/repo", "params": {"job_id": 456}},
        risk_level="low",
    ),
    "actions.download_job_log": operation_spec(
        category="ci",
        description="下载单个 job 日志到 cwd/jobs/<job_id>/job.log，只返回文件路径和大小。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=True,
        writes_remote=False,
        requires_cwd=True,
        required_params={"cwd": "string，当前 Codex workspace 目录，作为所有 job 文件落盘根目录", "job_id": "integer/string，job id"},
        optional_params={},
        returns={"data": "job_id、job_dir、log_path、bytes、content_returned=false。", "evidence": "含 download_path 和 bytes 的 GET job logs 调用证据。"},
        example={"operation": "actions.download_job_log", "repo": "owner/repo", "params": {"cwd": "D:/work/project", "job_id": 456}},
        risk_level="medium",
    ),
    "actions.list_artifacts": operation_spec(
        category="artifact",
        description="列出仓库或 run 的 artifacts。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={},
        optional_params={"run_id": "integer/string，传入时只列出该 run 的 artifacts", "page": "integer，页码，1 起始", "limit": "integer，每页数量"},
        returns={"data": "必须是包含 artifacts: list[object] 的 Gitea artifacts 响应。", "evidence": "含 page/limit 和 result_count 的调用证据。"},
        example={"operation": "actions.list_artifacts", "repo": "owner/repo", "params": {"run_id": 123}},
        risk_level="low",
    ),
    "actions.download_artifact": operation_spec(
        category="artifact",
        description="下载 artifact 到 cwd/jobs/<job_id>/artifact/，只返回目录路径和文件信息。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=True,
        writes_remote=False,
        requires_cwd=True,
        required_params={"cwd": "string，当前 Codex workspace 目录，作为所有 job 文件落盘根目录", "job_id": "integer/string，job id，用于目录 cwd/jobs/<job_id>/artifact/", "artifact_id": "integer/string，artifact id"},
        optional_params={"artifact_name": "string，用于解压子目录名；缺省为 artifact-<artifact_id>"},
        returns={"data": "artifact_id、artifact_dir、manifest_path、extracted_files、content_returned=false。", "evidence": "含临时 zip 下载路径、删除状态和 bytes 的 artifact 下载证据。"},
        example={"operation": "actions.download_artifact", "repo": "owner/repo", "params": {"cwd": "D:/work/project", "job_id": 456, "artifact_id": 789, "artifact_name": "test-results"}},
        risk_level="medium",
    ),
    "actions.list_runners": operation_spec(
        category="runner",
        description="列出仓库级 runners。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={},
        optional_params={"disabled": "boolean，按禁用状态过滤"},
        returns={"data": "必须是包含 runners: list[object] 的 Gitea runners 响应。", "evidence": "GET runners 调用证据。"},
        example={"operation": "actions.list_runners", "repo": "owner/repo", "params": {"disabled": False}},
        risk_level="low",
    ),
    "ci.prepare_failure_context": operation_spec(
        category="ci",
        description="定位失败 run，列出失败 jobs，并把失败 job 日志下载到 cwd/jobs/<job_id>/job.log。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=True,
        writes_remote=False,
        requires_cwd=True,
        required_params={"cwd": "string，当前 Codex workspace 目录"},
        optional_params={
            "run_id": "integer/string，指定 workflow run",
            "branch": "string，按分支定位 run",
            "head_sha": "string，按 commit sha 定位 run",
            "status": "string，按 run 状态定位；缺省 failure",
            "attempt": "integer/string，指定 run attempt jobs",
            "include_artifacts": "boolean，是否列出 run artifacts；默认 true",
            "max_failed_jobs": "integer，最多下载多少个失败 job 日志；默认 20",
            "page": "integer，页码",
            "limit": "integer，每页数量；定位 run 缺省 10",
        },
        returns={"data": "run summary、failed_jobs、log_paths、artifact_candidates、content_returned=false。", "evidence": "内部每次 Gitea API 调用证据列表。"},
        example={"operation": "ci.prepare_failure_context", "repo": "owner/repo", "params": {"cwd": "D:/work/project", "head_sha": "abc123", "status": "failure"}},
        risk_level="medium",
    ),
    "artifact.sync_for_run": operation_spec(
        category="artifact",
        description="列出并下载某个 run 的 artifacts，解压到 cwd/jobs/run-<run_id>/artifact/ 并写 manifest.json。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=True,
        writes_remote=False,
        requires_cwd=True,
        required_params={"cwd": "string，当前 Codex workspace 目录", "run_id": "integer/string，workflow run id"},
        optional_params={"artifact_name_pattern": "string，fnmatch 风格 artifact 名称过滤", "job_id": "integer/string，可显式指定落盘 job 目录；缺省 run-<run_id>", "page": "integer，页码", "limit": "integer，每页数量"},
        returns={"data": "manifest_path、artifact_dir、artifact_dirs、file_count、content_returned=false。", "evidence": "list artifacts 和每个 artifact 下载证据。"},
        example={"operation": "artifact.sync_for_run", "repo": "owner/repo", "params": {"cwd": "D:/work/project", "run_id": 123, "artifact_name_pattern": "test-*"}},
        risk_level="medium",
    ),
    "pr.preflight": operation_spec(
        category="pr",
        description="读取 PR metadata、changed files summary，并查询 head_sha 相关 CI runs。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={"pr_number": "integer/string，PR 编号"},
        optional_params={"page": "integer，changed files 页码", "limit": "integer，changed files 每页数量；默认 100", "ci_limit": "integer，head_sha CI runs 数量；默认 10", "file_limit": "integer，返回文件摘要最大数量；默认 100"},
        returns={"data": "PR state、base/head/head_sha、changed_files summary、ci summary。", "evidence": "PR、files、CI runs 查询证据。"},
        example={"operation": "pr.preflight", "repo": "owner/repo", "params": {"pr_number": 42, "ci_limit": 10}},
        risk_level="low",
    ),
}


def describe_operations(*, category: str | None = None, operation: str | None = None, detail: str | None = None) -> dict[str, Any]:
    operation_name = operation.strip() if operation else None
    detail_value = (detail or ("full" if operation_name else "brief")).strip().lower()
    categories = sorted({spec["category"] for spec in OPERATION_SPECS.values()})
    base: dict[str, Any] = {
        "provider": "gitea",
        "write_operations_enabled": False,
        "detail": detail_value,
        "categories": categories,
        "repo_format": "owner/repo",
        "pagination": "支持 page 和 limit 参数时透传给 Gitea API。",
        "job_output_root": "需要由调用方传入 params.cwd；job log 和 artifact 都写入 cwd/jobs/<job_id>/。",
        "artifact_default_dir": "<cwd>/jobs/<job_id>/artifact/",
        "job_log_path": "<cwd>/jobs/<job_id>/job.log",
    }
    if detail_value not in {"brief", "full"}:
        return {**base, "ok": False, "error": {"code": "invalid_detail", "message": "detail 必须是 brief 或 full", "details": {"detail": detail}}}

    category_filter = category.strip().lower() if category else None
    if category_filter and category_filter not in categories:
        return {
            **base,
            "ok": False,
            "error": {
                "code": "invalid_category",
                "message": "未知 operation category",
                "details": {"category": category_filter, "available_categories": categories},
            },
        }

    if operation_name:
        spec = OPERATION_SPECS.get(operation_name)
        if spec is None:
            return {
                **base,
                "ok": False,
                "error": {"code": "unknown_operation", "message": "未知 operation", "details": {"operation": operation_name, "available": sorted(OPERATION_SPECS)}},
            }
        if category_filter and spec["category"] != category_filter:
            return {
                **base,
                "ok": False,
                "error": {
                    "code": "operation_category_mismatch",
                    "message": "operation 不属于指定 category",
                    "details": {"operation": operation_name, "operation_category": spec["category"], "category": category_filter},
                },
            }
        return {**base, "ok": True, "operation": operation_for_output(operation_name, spec, detail_value)}

    operations = []
    for name, spec in sorted(OPERATION_SPECS.items()):
        if category_filter and spec["category"] != category_filter:
            continue
        operations.append(operation_for_output(name, spec, detail_value))
    return {**base, "ok": True, "category": category_filter, "operations": operations}


def operation_for_output(name: str, spec: dict[str, Any], detail: str) -> dict[str, Any]:
    full = {"name": name, **spec}
    if detail == "full":
        return full
    return {field: full[field] for field in _BRIEF_FIELDS}


async def check_status() -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    warnings: list[Any] = []
    try:
        config = load_gitea_config(require_token=False)
        client = GiteaClient(config)
        version_path = "/version"
        version, version_evidence = await client.request_json("GET", version_path, require_token=False, step="server.version")
        evidence.append(version_evidence)
        expect_object(version, step="server.version", path=version_path)
        data: dict[str, Any] = {"reachable": True, "version": version, "authenticated": False}
        if config.token:
            user_path = "/user"
            try:
                user, user_evidence = await client.request_json("GET", user_path, step="auth.whoami")
            except PlatformError as exc:
                return error_result(operation="gitea_status", error=exc, evidence=evidence, warnings=warnings)
            evidence.append(user_evidence)
            expect_object(user, step="auth.whoami", path=user_path)
            data["authenticated"] = True
            data["user"] = compact_user(user)
        else:
            warnings.append({"code": "missing_token", "message": "未设置 GITEA_TOKEN，仅检查服务器版本。"})
        return ok_result(operation="gitea_status", data=data, evidence=evidence, warnings=warnings)
    except PlatformError as exc:
        return error_result(operation="gitea_status", error=exc, evidence=evidence, warnings=warnings)


async def execute_operation(operation: str, *, repo: str | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    operation = (operation or "").strip()
    if operation not in HANDLERS:
        return error_result(operation=operation or "<missing>", error=PlatformError("unknown_operation", "未知或未启用的 operation", {"operation": operation, "available": sorted(HANDLERS)}))
    validation_error = validate_request(operation, repo, params)
    if validation_error:
        return error_result(operation=operation, error=validation_error)

    try:
        config = load_gitea_config(require_token=operation != "server.version")
        client = GiteaClient(config)
        return await HANDLERS[operation](client, repo, params)
    except PlatformError as exc:
        return error_result(operation=operation, error=exc)


async def server_version(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    path = "/version"
    data, evidence = await client.request_json("GET", path, require_token=False, step="server.version")
    expect_object(data, step="server.version", path=path)
    return ok_result(operation="server.version", data=data, evidence=evidence)


async def auth_whoami(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    path = "/user"
    data, evidence = await client.request_json("GET", path, step="auth.whoami")
    expect_object(data, step="auth.whoami", path=path)
    return ok_result(operation="auth.whoami", data=data, evidence=evidence)


async def get_repo(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    path = repo_path(repo)
    data, evidence = await client.request_json("GET", path, step="repo.get")
    expect_object(data, step="repo.get", path=path)
    return ok_result(operation="repo.get", data=data, evidence=evidence, meta={"repo": repo})


async def list_workflows(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    path = repo_path(repo, "/actions/workflows")
    data, evidence = await client.request_json("GET", path, params=page_params(params), step="actions.list_workflows")
    workflows = expect_keyed_object_list(data, step="actions.list_workflows", path=path, keys=("workflows",))
    evidence["result_count"] = len(workflows)
    return ok_result(operation="actions.list_workflows", data=data, evidence=evidence, meta={"repo": repo})


async def get_workflow(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    workflow_id = required_param(params, "workflow_id")
    path = repo_path(repo, f"/actions/workflows/{path_segment(workflow_id)}")
    data, evidence = await client.request_json("GET", path, step="actions.get_workflow")
    expect_object(data, step="actions.get_workflow", path=path)
    return ok_result(operation="actions.get_workflow", data=data, evidence=evidence, meta={"repo": repo})


async def list_runs(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    path = repo_path(repo, "/actions/runs")
    allowed = {"event", "branch", "status", "actor", "head_sha", "page", "limit"}
    data, evidence = await client.request_json("GET", path, params=filter_params(params, allowed), step="actions.list_runs")
    runs = expect_keyed_object_list(data, step="actions.list_runs", path=path, keys=("workflow_runs",))
    evidence["result_count"] = len(runs)
    return ok_result(operation="actions.list_runs", data=data, evidence=evidence, meta={"repo": repo})


async def get_run(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    run_id = required_param(params, "run_id")
    path = repo_path(repo, f"/actions/runs/{path_segment(run_id)}")
    data, evidence = await client.request_json("GET", path, step="actions.get_run")
    expect_object(data, step="actions.get_run", path=path)
    return ok_result(operation="actions.get_run", data=data, evidence=evidence, meta={"repo": repo})


async def ci_get_run_summary(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    run_id = required_param(params, "run_id")
    evidence: list[dict[str, Any]] = []

    run_path = repo_path(repo, f"/actions/runs/{path_segment(run_id)}")
    run_data, run_evidence = await client.request_json("GET", run_path, step="ci.get_run_summary.get_run")
    run_obj = expect_object(run_data, step="ci.get_run_summary.get_run", path=run_path)
    evidence.append(run_evidence)

    attempt = params.get("attempt")
    suffix = f"/actions/runs/{path_segment(run_id)}/attempts/{path_segment(str(attempt))}/jobs" if attempt else f"/actions/runs/{path_segment(run_id)}/jobs"
    jobs_path = repo_path(repo, suffix)
    jobs_data, jobs_evidence = await client.request_json("GET", jobs_path, params=page_params(params), step="ci.get_run_summary.list_jobs")
    jobs = expect_keyed_object_list(jobs_data, step="ci.get_run_summary.list_jobs", path=jobs_path, keys=("jobs", "workflow_jobs"))
    jobs_evidence["result_count"] = len(jobs)
    evidence.append(jobs_evidence)

    failed_count = sum(1 for job in jobs if is_failed_job(job))
    queued_in_progress_count = sum(1 for job in jobs if is_queued_or_in_progress_job(job))
    data = {
        "run": compact_run(run_obj),
        "jobs": [compact_job(job) for job in jobs],
        "job_count": len(jobs),
        "failed_cancelled_timed_out_job_count": failed_count,
        "queued_in_progress_job_count": queued_in_progress_count,
        "status_counts": count_field_values(jobs, "status"),
        "conclusion_counts": count_field_values(jobs, "conclusion"),
        "content_returned": False,
    }
    return ok_result(
        operation="ci.get_run_summary",
        data=data,
        evidence=evidence,
        meta={"repo": repo, "run_id": run_id, "attempt": str(attempt) if attempt else None},
        next_suggested_operations=["ci.prepare_failure_context"] if failed_count else [],
    )


async def list_run_jobs(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    run_id = required_param(params, "run_id")
    attempt = params.get("attempt")
    suffix = f"/actions/runs/{path_segment(run_id)}/attempts/{path_segment(str(attempt))}/jobs" if attempt else f"/actions/runs/{path_segment(run_id)}/jobs"
    path = repo_path(repo, suffix)
    data, evidence = await client.request_json("GET", path, params=page_params(params), step="actions.list_run_jobs")
    jobs = expect_keyed_object_list(data, step="actions.list_run_jobs", path=path, keys=("jobs", "workflow_jobs"))
    evidence["result_count"] = len(jobs)
    return ok_result(operation="actions.list_run_jobs", data=data, evidence=evidence, meta={"repo": repo})


async def get_job(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    job_id = required_param(params, "job_id")
    path = repo_path(repo, f"/actions/jobs/{path_segment(job_id)}")
    data, evidence = await client.request_json("GET", path, step="actions.get_job")
    expect_object(data, step="actions.get_job", path=path)
    return ok_result(operation="actions.get_job", data=data, evidence=evidence, meta={"repo": repo})


async def download_job_log(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    cwd = workspace_root(params)
    job_id = required_param(params, "job_id")
    data, evidence = await download_job_log_to_path(client, repo, cwd, job_id, step="actions.download_job_log")
    return ok_result(operation="actions.download_job_log", data=data, evidence=evidence, meta={"repo": repo})


async def list_artifacts(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    run_id = params.get("run_id")
    suffix = f"/actions/runs/{path_segment(str(run_id))}/artifacts" if run_id else "/actions/artifacts"
    path = repo_path(repo, suffix)
    data, evidence = await client.request_json("GET", path, params=page_params(params), step="actions.list_artifacts")
    artifacts = expect_keyed_object_list(data, step="actions.list_artifacts", path=path, keys=("artifacts",))
    evidence["result_count"] = len(artifacts)
    return ok_result(operation="actions.list_artifacts", data=data, evidence=evidence, meta={"repo": repo})


async def download_artifact(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    if "target_dir" in params:
        raise PlatformError("forbidden_param", "actions.download_artifact 不允许传 target_dir；请传 cwd，文件固定写入 cwd/jobs/<job_id>/artifact/", {"param": "target_dir"})
    cwd = workspace_root(params)
    job_id = required_param(params, "job_id")
    artifact_id = required_param(params, "artifact_id")
    artifact_name = safe_name(str(params.get("artifact_name") or f"artifact-{artifact_id}"))
    data, evidence = await download_artifact_to_path(client, repo, cwd, job_id, artifact_id, artifact_name, step="actions.download_artifact")
    manifest_path = write_manifest(
        Path(data["artifact_dir"]),
        cwd,
        {
            "operation": "actions.download_artifact",
            "repo": repo,
            "generated_at": utc_now(),
            "job_id": job_id,
            "artifacts": [data],
            "evidence": [evidence],
        },
    )
    data["manifest_path"] = str(manifest_path)
    return ok_result(operation="actions.download_artifact", data=data, evidence=evidence, meta={"repo": repo})


async def list_runners(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    path = repo_path(repo, "/actions/runners")
    data, evidence = await client.request_json("GET", path, params=filter_params(params, {"disabled"}), step="actions.list_runners")
    runners = expect_keyed_object_list(data, step="actions.list_runners", path=path, keys=("runners",))
    evidence["result_count"] = len(runners)
    return ok_result(operation="actions.list_runners", data=data, evidence=evidence, meta={"repo": repo})


async def ci_prepare_failure_context(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    cwd = workspace_root(params)
    evidence: list[dict[str, Any]] = []
    warnings: list[Any] = []
    run_id = params.get("run_id")

    if run_id:
        run_path = repo_path(repo, f"/actions/runs/{path_segment(str(run_id))}")
        run_data, run_evidence = await client.request_json("GET", run_path, step="ci.get_run")
        evidence.append(run_evidence)
        expect_object(run_data, step="ci.get_run", path=run_path)
    else:
        runs_path = repo_path(repo, "/actions/runs")
        run_params = filter_params(params, {"branch", "head_sha", "event", "actor", "page"})
        run_params["status"] = str(params.get("status") or "failure")
        run_params["limit"] = int_param(params, "limit", 10, minimum=1)
        runs_data, runs_evidence = await client.request_json("GET", runs_path, params=run_params, step="ci.list_runs")
        runs = expect_keyed_object_list(runs_data, step="ci.list_runs", path=runs_path, keys=("workflow_runs",))
        runs_evidence["result_count"] = len(runs)
        evidence.append(runs_evidence)
        if not runs:
            raise PlatformError("run_not_found", "未找到匹配的 workflow run", {"params": run_params})
        run_data = runs[0]
        run_id = require_response_field(run_data, "id", step="ci.list_runs", path=runs_path)

    run_id_str = str(run_id)
    job_params = page_params(params)
    attempt = params.get("attempt")
    suffix = f"/actions/runs/{path_segment(run_id_str)}/attempts/{path_segment(str(attempt))}/jobs" if attempt else f"/actions/runs/{path_segment(run_id_str)}/jobs"
    jobs_path = repo_path(repo, suffix)
    jobs_data, jobs_evidence = await client.request_json("GET", jobs_path, params=job_params, step="ci.list_run_jobs")
    jobs = expect_keyed_object_list(jobs_data, step="ci.list_run_jobs", path=jobs_path, keys=("jobs", "workflow_jobs"))
    jobs_evidence["result_count"] = len(jobs)
    evidence.append(jobs_evidence)

    failed_jobs = [job for job in jobs if is_failed_job(job)]
    max_failed_jobs = int_param(params, "max_failed_jobs", 20, minimum=1)
    log_paths: list[str] = []
    failed_summaries: list[dict[str, Any]] = []

    for job in failed_jobs[:max_failed_jobs]:
        summary = compact_job(job)
        job_id = require_response_field(job, "id", step="ci.list_run_jobs", path=jobs_path)
        log_data, log_evidence = await download_job_log_to_path(client, repo, cwd, str(job_id), step="ci.download_failed_job_log")
        evidence.append(log_evidence)
        summary.update({"log_path": log_data["log_path"], "log_bytes": log_data["bytes"], "content_returned": False})
        log_paths.append(log_data["log_path"])
        failed_summaries.append(summary)

    if len(failed_jobs) > max_failed_jobs:
        warnings.append({"code": "failed_job_limit", "message": "只下载了部分失败 job 日志。", "downloaded": max_failed_jobs, "total_failed_jobs": len(failed_jobs)})

    artifact_candidates: list[dict[str, Any]] = []
    if bool_param(params, "include_artifacts", True):
        artifacts_path = repo_path(repo, f"/actions/runs/{path_segment(run_id_str)}/artifacts")
        artifacts_data, artifacts_evidence = await client.request_json("GET", artifacts_path, params=page_params(params), step="ci.list_artifacts")
        artifacts = expect_keyed_object_list(artifacts_data, step="ci.list_artifacts", path=artifacts_path, keys=("artifacts",))
        artifacts_evidence["result_count"] = len(artifacts)
        evidence.append(artifacts_evidence)
        artifact_candidates = [compact_artifact(artifact) for artifact in artifacts]

    next_ops = ["actions.download_job_log"] if failed_summaries and not log_paths else []
    if artifact_candidates:
        next_ops.append("artifact.sync_for_run")

    return ok_result(
        operation="ci.prepare_failure_context",
        data={"run": compact_run(run_data), "failed_jobs": failed_summaries, "failed_job_count": len(failed_jobs), "log_paths": log_paths, "artifact_candidates": artifact_candidates, "content_returned": False},
        evidence=evidence,
        meta={"repo": repo, "cwd": str(cwd), "run_id": run_id_str},
        warnings=warnings,
        next_suggested_operations=next_ops,
    )


async def artifact_sync_for_run(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    if "target_dir" in params:
        raise PlatformError("forbidden_param", "artifact.sync_for_run 不允许传 target_dir；请传 cwd，文件固定写入 cwd/jobs/run-<run_id>/artifact/", {"param": "target_dir"})
    cwd = workspace_root(params)
    run_id = required_param(params, "run_id")
    job_id = str(params.get("job_id") or f"run-{run_id}")
    pattern = str(params.get("artifact_name_pattern") or "").strip()
    evidence: list[dict[str, Any]] = []
    warnings: list[Any] = []

    artifacts_path = repo_path(repo, f"/actions/runs/{path_segment(run_id)}/artifacts")
    artifacts_data, artifacts_evidence = await client.request_json("GET", artifacts_path, params=page_params(params), step="artifact.list_artifacts")
    artifacts = expect_keyed_object_list(artifacts_data, step="artifact.list_artifacts", path=artifacts_path, keys=("artifacts",))
    artifacts_evidence["result_count"] = len(artifacts)
    evidence.append(artifacts_evidence)

    selected = []
    for artifact in artifacts:
        name = str(require_response_field(artifact, "name", step="artifact.list_artifacts", path=artifacts_path))
        if pattern and not fnmatch.fnmatch(name, pattern):
            continue
        selected.append(artifact)

    downloaded: list[dict[str, Any]] = []
    for artifact in selected:
        artifact_id = str(require_response_field(artifact, "id", step="artifact.list_artifacts", path=artifacts_path))
        artifact_name = safe_name(str(require_response_field(artifact, "name", step="artifact.list_artifacts", path=artifacts_path)))
        data, download_evidence = await download_artifact_to_path(client, repo, cwd, job_id, artifact_id, artifact_name, step="artifact.download_artifact", extract_dir_name=artifact_name)
        data["source"] = compact_artifact(artifact)
        evidence.append(download_evidence)
        downloaded.append(data)

    artifact_root = job_output_dir(cwd, job_id) / "artifact"
    assert_relative_to_root(artifact_root, cwd)
    manifest = {"operation": "artifact.sync_for_run", "repo": repo, "run_id": run_id, "job_id": job_id, "artifact_name_pattern": pattern or None, "generated_at": utc_now(), "artifacts": downloaded, "evidence": evidence}
    manifest_path = write_manifest(artifact_root, cwd, manifest)
    file_count = sum(int(item.get("extracted_file_count", 0)) for item in downloaded)

    if not selected:
        warnings.append({"code": "no_artifacts_selected", "message": "没有 artifact 匹配当前条件。", "artifact_name_pattern": pattern or None})

    return ok_result(
        operation="artifact.sync_for_run",
        data={"run_id": run_id, "job_id": job_id, "manifest_path": str(manifest_path), "artifact_dir": str(artifact_root), "artifact_dirs": [item["extract_dir"] for item in downloaded if item.get("extract_dir")], "file_count": file_count, "artifacts": downloaded, "content_returned": False},
        evidence=evidence,
        meta={"repo": repo, "cwd": str(cwd), "run_id": run_id},
        warnings=warnings,
        next_suggested_operations=[],
    )


async def pr_preflight(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    pr_number = required_param(params, "pr_number")
    evidence: list[dict[str, Any]] = []

    pr_path = repo_path(repo, f"/pulls/{path_segment(pr_number)}")
    pr_data, pr_evidence = await client.request_json("GET", pr_path, step="pr.get")
    pr_obj = expect_object(pr_data, step="pr.get", path=pr_path)
    evidence.append(pr_evidence)

    files_path = repo_path(repo, f"/pulls/{path_segment(pr_number)}/files")
    files_params = {"page": params.get("page", 1), "limit": int_param(params, "limit", 100, minimum=1)}
    files_data, files_evidence = await client.request_json("GET", files_path, params=files_params, step="pr.list_files")
    files = expect_top_level_object_list(files_data, step="pr.list_files", path=files_path)
    files_evidence["result_count"] = len(files)
    evidence.append(files_evidence)

    file_limit = int_param(params, "file_limit", 100, minimum=1)
    head = expect_nested_object(pr_obj, "head", step="pr.get", path=pr_path)
    base = expect_nested_object(pr_obj, "base", step="pr.get", path=pr_path)
    head_sha = str(require_response_field(head, "sha", step="pr.get", path=pr_path))

    ci_path = repo_path(repo, "/actions/runs")
    ci_params = {"head_sha": head_sha, "limit": int_param(params, "ci_limit", 10, minimum=1)}
    runs_data, runs_evidence = await client.request_json("GET", ci_path, params=ci_params, step="pr.list_head_ci_runs")
    runs = expect_keyed_object_list(runs_data, step="pr.list_head_ci_runs", path=ci_path, keys=("workflow_runs",))
    runs_evidence["result_count"] = len(runs)
    evidence.append(runs_evidence)
    ci_summary = {"head_sha": head_sha, "run_count": len(runs), "runs": [compact_run(run) for run in runs]}

    changed_files = [compact_file(file) for file in files[:file_limit]]
    data = {
        "pr": compact_pr(pr_obj),
        "state": require_response_field(pr_obj, "state", step="pr.get", path=pr_path),
        "base": compact_ref(base),
        "head": compact_ref(head),
        "head_sha": head_sha,
        "changed_files": {"count": len(files), "returned": len(changed_files), "files": changed_files},
        "ci": ci_summary,
    }
    return ok_result(operation="pr.preflight", data=data, evidence=evidence, meta={"repo": repo, "pr_number": pr_number}, next_suggested_operations=["ci.prepare_failure_context"] if any(is_failed_run(run) for run in runs) else [])


def require_repo(repo: str | None) -> None:
    if not repo:
        raise PlatformError("missing_repo", "该 operation 需要 repo 参数", {"repo_format": "owner/repo"})


def validate_request(operation: str, repo: str | None, params: dict[str, Any]) -> PlatformError | None:
    spec = OPERATION_SPECS[operation]
    if spec["repo_required"] and not repo:
        return PlatformError("missing_repo", "该 operation 需要 repo 参数", {"repo_format": "owner/repo"})

    allowed_params = set(spec["required_params"]) | set(spec["optional_params"])
    unknown_params = sorted(set(params) - allowed_params)
    if spec["writes_local_files"] and "target_dir" in unknown_params:
        return PlatformError("forbidden_param", "本地落盘 operation 不允许传 target_dir；请传 cwd，文件固定写入 cwd/jobs/<job_id>/。", {"param": "target_dir"})
    if unknown_params:
        return PlatformError(
            "unknown_param",
            "operation 收到了未声明的 params 字段",
            {"operation": operation, "unknown_params": unknown_params, "allowed_params": sorted(allowed_params)},
        )

    if spec["writes_local_files"] and "target_dir" in params:
        return PlatformError("forbidden_param", "本地落盘 operation 不允许传 target_dir；请传 cwd，文件固定写入 cwd/jobs/<job_id>/。", {"param": "target_dir"})
    for name in spec["required_params"]:
        value = params.get(name)
        if value is None or str(value).strip() == "":
            return PlatformError("missing_param", f"缺少 params.{name}", {"param": name})
    return None


def required_param(params: dict[str, Any], name: str) -> str:
    value = params.get(name)
    if value is None or str(value).strip() == "":
        raise PlatformError("missing_param", f"缺少 params.{name}", {"param": name})
    return str(value).strip()


def filter_params(params: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if key in allowed and value is not None and value != ""}


def page_params(params: dict[str, Any]) -> dict[str, Any]:
    return filter_params(params, {"page", "limit"})


def bool_param(params: dict[str, Any], name: str, default: bool) -> bool:
    value = params.get(name)
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise PlatformError("invalid_param", f"params.{name} 必须是 boolean", {"param": name, "value": value})


def int_param(params: dict[str, Any], name: str, default: int, *, minimum: int | None = None) -> int:
    value = params.get(name, default)
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise PlatformError("invalid_param", f"params.{name} 必须是 integer", {"param": name, "value": value}) from exc
    if minimum is not None and number < minimum:
        raise PlatformError("invalid_param", f"params.{name} 必须大于等于 {minimum}", {"param": name, "value": value, "minimum": minimum})
    return number


def safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value.strip())
    return cleaned.strip(".-") or "unnamed"


def path_segment(value: str) -> str:
    return quote(value, safe="")


def workspace_root(params: dict[str, Any]) -> Path:
    raw = required_param(params, "cwd")
    root = Path(raw).resolve()
    if not root.is_dir():
        raise PlatformError("invalid_cwd", "params.cwd 必须是已存在的目录", {"cwd": raw, "resolved": str(root)})
    return root


def job_output_dir(cwd: Path, job_id: str) -> Path:
    return cwd / "jobs" / safe_name(job_id)


def assert_relative_to_root(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PlatformError("artifact_path_outside_root", "artifact 目标路径不在 params.cwd 内", {"path": str(path), "cwd": str(root)}) from exc


def extract_zip(zip_path: Path, target_dir: Path) -> list[str]:
    extracted: list[str] = []
    target_root = target_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            member_path = (target_dir / member.filename).resolve()
            try:
                member_path.relative_to(target_root)
            except ValueError as exc:
                raise PlatformError("unsafe_artifact_zip", "artifact zip 包含越界路径", {"member": member.filename}) from exc
            member_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, member_path.open("wb") as target:
                target.write(source.read())
            extracted.append(str(member_path))
    return extracted


async def download_job_log_to_path(client: GiteaClient, repo: str, cwd: Path, job_id: str, *, step: str) -> tuple[dict[str, Any], dict[str, Any]]:
    job_dir = job_output_dir(cwd, job_id)
    log_path = job_dir / "job.log"
    assert_relative_to_root(log_path, cwd)
    path = repo_path(repo, f"/actions/jobs/{path_segment(job_id)}/logs")
    log_text, evidence = await client.request_text("GET", path, step=step)
    job_dir.mkdir(parents=True, exist_ok=True)
    log_path.write_text(log_text, encoding="utf-8")
    evidence["download_path"] = str(log_path)
    evidence["bytes"] = log_path.stat().st_size
    return {"job_id": job_id, "cwd": str(cwd), "job_dir": str(job_dir), "log_path": str(log_path), "bytes": log_path.stat().st_size, "content_returned": False}, evidence


async def download_artifact_to_path(client: GiteaClient, repo: str, cwd: Path, job_id: str, artifact_id: str, artifact_name: str, *, step: str, extract_dir_name: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    job_dir = job_output_dir(cwd, job_id)
    artifact_dir = job_dir / "artifact"
    zip_path = artifact_dir / f".{safe_name(artifact_name)}.download.zip"
    assert_relative_to_root(artifact_dir, cwd)
    assert_relative_to_root(zip_path, cwd)
    evidence = await client.download(repo_path(repo, f"/actions/artifacts/{path_segment(artifact_id)}/zip"), zip_path, step=step)

    extract_dir = artifact_dir / safe_name(extract_dir_name) if extract_dir_name else artifact_dir
    assert_relative_to_root(extract_dir, cwd)
    extracted_files = extract_zip(zip_path, extract_dir)
    try:
        zip_path.unlink()
    except OSError as exc:
        raise PlatformError(
            "artifact_zip_cleanup_failed",
            "artifact 已解压但临时 zip 删除失败",
            {"artifact_dir": str(artifact_dir)},
        ) from exc
    evidence["temporary_zip_deleted"] = True

    return {
        "artifact_id": artifact_id,
        "job_id": job_id,
        "artifact_name": safe_name(artifact_name),
        "cwd": str(cwd),
        "job_dir": str(job_dir),
        "artifact_dir": str(artifact_dir),
        "extract_dir": str(extract_dir),
        "extracted": True,
        "extracted_file_count": len(extracted_files),
        "extracted_files": extracted_files[:200],
        "extracted_files_truncated": len(extracted_files) > 200,
        "content_returned": False,
    }, evidence


def write_manifest(artifact_dir: Path, cwd: Path, manifest: dict[str, Any]) -> Path:
    assert_relative_to_root(artifact_dir, cwd)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = artifact_dir / "manifest.json"
    assert_relative_to_root(manifest_path, cwd)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def expect_object(data: Any, *, step: str, path: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise unexpected_response_shape(step=step, path=path, expected=["object"], data=data)
    return data


def expect_nested_object(data: dict[str, Any], key: str, *, step: str, path: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise unexpected_response_shape(step=step, path=path, expected=[f"{key}: object"], data=data, extra={"field": key})
    return value


def expect_top_level_object_list(data: Any, *, step: str, path: str) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise unexpected_response_shape(step=step, path=path, expected=["list[object]"], data=data)
    return expect_object_list(data, step=step, path=path, expected="list[object]")


def expect_keyed_object_list(data: Any, *, step: str, path: str, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    obj = expect_object(data, step=step, path=path)
    for key in keys:
        if key not in obj:
            continue
        value = obj[key]
        if not isinstance(value, list):
            raise unexpected_response_shape(step=step, path=path, expected=[f"{key}: list[object]"], data=obj, extra={"field": key, "actual_field_type": type(value).__name__})
        return expect_object_list(value, step=step, path=path, expected=f"{key}: list[object]")
    raise unexpected_response_shape(step=step, path=path, expected=[f"{key}: list[object]" for key in keys], data=obj)


def expect_object_list(items: list[Any], *, step: str, path: str, expected: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise unexpected_response_shape(step=step, path=path, expected=[expected], data=item, extra={"index": index})
        result.append(item)
    return result


def require_response_field(data: dict[str, Any], field: str, *, step: str, path: str) -> Any:
    if field not in data or data[field] is None or (isinstance(data[field], str) and not data[field].strip()):
        details = {"step": step, "path": path, "field": field, "actual_keys": sorted(str(key) for key in data.keys())}
        raise PlatformError("missing_response_field", "Gitea API 响应缺少必需字段", details)
    return data[field]


def unexpected_response_shape(*, step: str, path: str, expected: list[str], data: Any, extra: dict[str, Any] | None = None) -> PlatformError:
    details: dict[str, Any] = {"step": step, "path": path, "expected": expected, "actual_type": type(data).__name__}
    if isinstance(data, dict):
        details["actual_keys"] = sorted(str(key) for key in data.keys())
    elif isinstance(data, list):
        details["actual_length"] = len(data)
    if extra:
        details.update(extra)
    return PlatformError("unexpected_response_shape", "Gitea API 响应结构与当前 strict parser 不匹配", details)


def ensure_compact_object(value: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlatformError("unexpected_response_shape", f"{name} 只能处理 object", {"step": name, "expected": ["object"], "actual_type": type(value).__name__})
    return value


def compact_user(user: Any) -> dict[str, Any]:
    obj = ensure_compact_object(user, name="compact_user")
    return {key: obj.get(key) for key in ("id", "login", "username", "full_name", "email") if obj.get(key) is not None}


def compact_run(run: Any) -> dict[str, Any]:
    obj = ensure_compact_object(run, name="compact_run")
    return {key: obj.get(key) for key in ("id", "name", "display_title", "status", "conclusion", "event", "head_branch", "head_sha", "run_number", "run_attempt", "created_at", "updated_at", "html_url") if obj.get(key) is not None}


def compact_job(job: Any) -> dict[str, Any]:
    obj = ensure_compact_object(job, name="compact_job")
    return {key: obj.get(key) for key in ("id", "name", "status", "conclusion", "started_at", "completed_at", "runner_name", "html_url") if obj.get(key) is not None}


def compact_artifact(artifact: Any) -> dict[str, Any]:
    obj = ensure_compact_object(artifact, name="compact_artifact")
    return {key: obj.get(key) for key in ("id", "name", "size_in_bytes", "expired", "created_at", "updated_at", "expires_at", "workflow_run") if obj.get(key) is not None}


def compact_file(file: Any) -> dict[str, Any]:
    obj = ensure_compact_object(file, name="compact_file")
    return {key: obj.get(key) for key in ("filename", "status", "additions", "deletions", "changes", "previous_filename") if obj.get(key) is not None}


def compact_ref(ref: Any) -> dict[str, Any]:
    obj = ensure_compact_object(ref, name="compact_ref")
    result = {key: obj.get(key) for key in ("ref", "label", "sha") if obj.get(key) is not None}
    repo = obj.get("repo")
    if isinstance(repo, dict):
        result["repo"] = repo.get("full_name") or repo.get("name")
    user = obj.get("user")
    if isinstance(user, dict):
        result["user"] = user.get("login") or user.get("username")
    return result


def compact_pr(pr: Any) -> dict[str, Any]:
    obj = ensure_compact_object(pr, name="compact_pr")
    return {key: obj.get(key) for key in ("id", "number", "index", "title", "state", "draft", "mergeable", "merged", "created_at", "updated_at", "html_url") if obj.get(key) is not None}


def is_failed_job(job: dict[str, Any]) -> bool:
    conclusion = str(job.get("conclusion") or "").lower()
    status = str(job.get("status") or "").lower()
    return conclusion in _FAILED_CONCLUSIONS or status in _FAILED_STATUSES


def is_queued_or_in_progress_job(job: dict[str, Any]) -> bool:
    status = str(job.get("status") or "").lower()
    return status in {"queued", "in_progress"}


def count_field_values(items: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = item.get(field)
        if value is None or str(value).strip() == "":
            key = "<missing>"
        else:
            key = str(value).lower()
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def is_failed_run(run: dict[str, Any]) -> bool:
    conclusion = str(run.get("conclusion") or "").lower()
    status = str(run.get("status") or "").lower()
    return conclusion in _FAILED_CONCLUSIONS or status in _FAILED_STATUSES or status == "failure"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_operation_specs() -> None:
    for name, spec in OPERATION_SPECS.items():
        fields = set(spec)
        if fields != _REQUIRED_SPEC_FIELDS:
            missing = sorted(_REQUIRED_SPEC_FIELDS - fields)
            extra = sorted(fields - _REQUIRED_SPEC_FIELDS)
            raise RuntimeError(f"operation spec {name} has invalid metadata fields; missing={missing}; extra={extra}")
        if not isinstance(spec["required_params"], dict) or not isinstance(spec["optional_params"], dict):
            raise RuntimeError(f"operation spec {name} params metadata must be explicit dicts")
        if not isinstance(spec["returns"], dict) or not spec["returns"]:
            raise RuntimeError(f"operation spec {name} must declare returns metadata")
        if not isinstance(spec["risk_level"], str) or not spec["risk_level"]:
            raise RuntimeError(f"operation spec {name} must declare risk_level")
        if spec["writes_local_files"] and not spec["requires_cwd"]:
            raise RuntimeError(f"local write operation must require cwd: {name}")
        if spec["requires_cwd"] and "cwd" not in spec["required_params"]:
            raise RuntimeError(f"cwd operation must declare required params.cwd: {name}")
        if spec["writes_remote"] and not any(word in name for word in ("publish", "dispatch", "rerun", "delete", "merge")):
            raise RuntimeError(f"remote write operation name must disclose side effect: {name}")
    spec_names = set(OPERATION_SPECS)
    handler_names = set(HANDLERS)
    if spec_names != handler_names:
        raise RuntimeError(f"operation registry and handlers diverged; missing_handlers={sorted(spec_names - handler_names)}; missing_specs={sorted(handler_names - spec_names)}")


def result_to_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


HANDLERS: dict[str, OperationHandler] = {
    "server.version": server_version,
    "auth.whoami": auth_whoami,
    "repo.get": get_repo,
    "actions.list_workflows": list_workflows,
    "actions.get_workflow": get_workflow,
    "actions.list_runs": list_runs,
    "actions.get_run": get_run,
    "ci.get_run_summary": ci_get_run_summary,
    "actions.list_run_jobs": list_run_jobs,
    "actions.get_job": get_job,
    "actions.download_job_log": download_job_log,
    "actions.list_artifacts": list_artifacts,
    "actions.download_artifact": download_artifact,
    "actions.list_runners": list_runners,
    "ci.prepare_failure_context": ci_prepare_failure_context,
    "artifact.sync_for_run": artifact_sync_for_run,
    "pr.preflight": pr_preflight,
}


validate_operation_specs()
