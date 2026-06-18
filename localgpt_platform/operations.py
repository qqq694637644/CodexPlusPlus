from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote

from .config import load_gitea_config
from .gitea import GiteaClient, repo_path
from .result import PlatformError, error_result, ok_result

OperationHandler = Callable[[GiteaClient, str | None, dict[str, Any]], Awaitable[dict[str, Any]]]


OPERATION_SPECS: dict[str, dict[str, Any]] = {
    "server.version": {
        "description": "读取 Gitea 服务器版本。",
        "repo_required": False,
        "required_params": {},
        "optional_params": {},
        "example": {"operation": "server.version"},
    },
    "auth.whoami": {
        "description": "读取当前 token 对应用户。",
        "repo_required": False,
        "required_params": {},
        "optional_params": {},
        "example": {"operation": "auth.whoami"},
    },
    "repo.get": {
        "description": "读取仓库元数据。",
        "repo_required": True,
        "required_params": {},
        "optional_params": {},
        "example": {"operation": "repo.get", "repo": "owner/repo"},
    },
    "actions.list_workflows": {
        "description": "列出仓库 Actions workflows。",
        "repo_required": True,
        "required_params": {},
        "optional_params": {
            "page": "integer，页码，1 起始",
            "limit": "integer，每页数量",
        },
        "example": {"operation": "actions.list_workflows", "repo": "owner/repo", "params": {"limit": 20}},
    },
    "actions.get_workflow": {
        "description": "读取单个 workflow。",
        "repo_required": True,
        "required_params": {"workflow_id": "string/integer，workflow id 或 workflow 文件名"},
        "optional_params": {},
        "example": {"operation": "actions.get_workflow", "repo": "owner/repo", "params": {"workflow_id": "ci.yml"}},
    },
    "actions.list_runs": {
        "description": "列出 workflow runs。",
        "repo_required": True,
        "required_params": {},
        "optional_params": {
            "event": "string，workflow event name",
            "branch": "string，workflow branch",
            "status": "string，pending/queued/in_progress/failure/success/skipped",
            "actor": "string，触发用户",
            "head_sha": "string，触发 commit sha",
            "page": "integer，页码，1 起始",
            "limit": "integer，每页数量",
        },
        "example": {"operation": "actions.list_runs", "repo": "owner/repo", "params": {"status": "failure", "limit": 10}},
    },
    "actions.get_run": {
        "description": "读取单个 workflow run。",
        "repo_required": True,
        "required_params": {"run_id": "integer/string，workflow run id"},
        "optional_params": {},
        "example": {"operation": "actions.get_run", "repo": "owner/repo", "params": {"run_id": 123}},
    },
    "actions.list_run_jobs": {
        "description": "列出 run 的 jobs。",
        "repo_required": True,
        "required_params": {"run_id": "integer/string，workflow run id"},
        "optional_params": {
            "attempt": "integer/string，指定 attempt 时查询该 attempt 的 jobs",
            "page": "integer，页码，1 起始",
            "limit": "integer，每页数量",
        },
        "example": {"operation": "actions.list_run_jobs", "repo": "owner/repo", "params": {"run_id": 123}},
    },
    "actions.get_job": {
        "description": "读取单个 job。",
        "repo_required": True,
        "required_params": {"job_id": "integer/string，job id"},
        "optional_params": {},
        "example": {"operation": "actions.get_job", "repo": "owner/repo", "params": {"job_id": 456}},
    },
    "actions.get_job_log": {
        "description": "下载单个 job 日志到 cwd/jobs/<job_id>/job.log，只返回文件路径和大小。",
        "repo_required": True,
        "required_params": {
            "cwd": "string，当前 Codex workspace 目录，作为所有 job 文件落盘根目录",
            "job_id": "integer/string，job id",
        },
        "optional_params": {},
        "example": {"operation": "actions.get_job_log", "repo": "owner/repo", "params": {"cwd": "D:/work/project", "job_id": 456}},
    },
    "actions.list_artifacts": {
        "description": "列出仓库或 run 的 artifacts。",
        "repo_required": True,
        "required_params": {},
        "optional_params": {
            "run_id": "integer/string，传入时只列出该 run 的 artifacts",
            "page": "integer，页码，1 起始",
            "limit": "integer，每页数量",
        },
        "example": {"operation": "actions.list_artifacts", "repo": "owner/repo", "params": {"run_id": 123}},
    },
    "actions.download_artifact": {
        "description": "下载 artifact 到 cwd/jobs/<job_id>/artifact/，只返回目录路径和文件信息。",
        "repo_required": True,
        "required_params": {
            "cwd": "string，当前 Codex workspace 目录，作为所有 job 文件落盘根目录",
            "job_id": "integer/string，job id，用于目录 cwd/jobs/<job_id>/artifact/",
            "artifact_id": "integer/string，artifact id",
        },
        "optional_params": {
            "artifact_name": "string，用于 zip 文件名；缺省为 artifact-<artifact_id>",
            "extract": "boolean，是否解压；默认 true",
        },
        "example": {
            "operation": "actions.download_artifact",
            "repo": "owner/repo",
            "params": {"cwd": "D:/work/project", "job_id": 456, "artifact_id": 789, "artifact_name": "test-results", "extract": True},
        },
    },
    "actions.list_runners": {
        "description": "列出仓库级 runners。",
        "repo_required": True,
        "required_params": {},
        "optional_params": {"disabled": "boolean，按禁用状态过滤"},
        "example": {"operation": "actions.list_runners", "repo": "owner/repo", "params": {"disabled": False}},
    },
}


def describe_operations() -> dict[str, Any]:
    return {
        "provider": "gitea",
        "write_operations_enabled": False,
        "operations": [
            {"name": name, **spec}
            for name, spec in sorted(OPERATION_SPECS.items())
        ],
        "repo_format": "owner/repo",
        "pagination": "支持 page 和 limit 参数时透传给 Gitea API。",
        "job_output_root": "需要由调用方传入 params.cwd；job log 和 artifact 都写入 cwd/jobs/<job_id>/。",
        "artifact_default_dir": "<cwd>/jobs/<job_id>/artifact/",
        "job_log_path": "<cwd>/jobs/<job_id>/job.log",
    }


async def execute_operation(
    operation: str,
    *,
    repo: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = params or {}
    operation = (operation or "").strip()
    if operation not in HANDLERS:
        return error_result(
            operation=operation or "<missing>",
            error=PlatformError(
                "unknown_operation",
                "未知或未启用的 operation",
                {"operation": operation, "available": sorted(HANDLERS)},
            ),
        )

    try:
        config = load_gitea_config(require_token=operation != "server.version")
        client = GiteaClient(config)
        return await HANDLERS[operation](client, repo, params)
    except PlatformError as exc:
        return error_result(operation=operation, error=exc)


async def server_version(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    data, evidence = await client.request_json("GET", "/version", require_token=False)
    return ok_result(operation="server.version", data=data, evidence=evidence)


async def auth_whoami(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    data, evidence = await client.request_json("GET", "/user")
    return ok_result(operation="auth.whoami", data=data, evidence=evidence)


async def get_repo(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    data, evidence = await client.request_json("GET", repo_path(repo))
    return ok_result(operation="repo.get", data=data, evidence=evidence, meta={"repo": repo})


async def list_workflows(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    data, evidence = await client.request_json(
        "GET",
        repo_path(repo, "/actions/workflows"),
        params=page_params(params),
    )
    return ok_result(operation="actions.list_workflows", data=data, evidence=evidence, meta={"repo": repo})


async def get_workflow(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    workflow_id = required_param(params, "workflow_id")
    data, evidence = await client.request_json(
        "GET",
        repo_path(repo, f"/actions/workflows/{path_segment(workflow_id)}"),
    )
    return ok_result(operation="actions.get_workflow", data=data, evidence=evidence, meta={"repo": repo})


async def list_runs(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    allowed = {"event", "branch", "status", "actor", "head_sha", "page", "limit"}
    data, evidence = await client.request_json(
        "GET",
        repo_path(repo, "/actions/runs"),
        params=filter_params(params, allowed),
    )
    return ok_result(operation="actions.list_runs", data=data, evidence=evidence, meta={"repo": repo})


async def get_run(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    run_id = required_param(params, "run_id")
    data, evidence = await client.request_json(
        "GET",
        repo_path(repo, f"/actions/runs/{path_segment(run_id)}"),
    )
    return ok_result(operation="actions.get_run", data=data, evidence=evidence, meta={"repo": repo})


async def list_run_jobs(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    run_id = required_param(params, "run_id")
    attempt = params.get("attempt")
    suffix = (
        f"/actions/runs/{path_segment(run_id)}/attempts/{path_segment(str(attempt))}/jobs"
        if attempt
        else f"/actions/runs/{path_segment(run_id)}/jobs"
    )
    data, evidence = await client.request_json(
        "GET",
        repo_path(repo, suffix),
        params=page_params(params),
    )
    return ok_result(operation="actions.list_run_jobs", data=data, evidence=evidence, meta={"repo": repo})


async def get_job(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    job_id = required_param(params, "job_id")
    data, evidence = await client.request_json(
        "GET",
        repo_path(repo, f"/actions/jobs/{path_segment(job_id)}"),
    )
    return ok_result(operation="actions.get_job", data=data, evidence=evidence, meta={"repo": repo})


async def get_job_log(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    job_id = required_param(params, "job_id")
    cwd = workspace_root(params)
    job_dir = job_output_dir(cwd, job_id)
    log_path = job_dir / "job.log"
    assert_relative_to_root(log_path, cwd)
    log_text, evidence = await client.request_text(
        "GET",
        repo_path(repo, f"/actions/jobs/{path_segment(job_id)}/logs"),
    )
    job_dir.mkdir(parents=True, exist_ok=True)
    log_path.write_text(log_text, encoding="utf-8")
    evidence["download_path"] = str(log_path)
    evidence["bytes"] = log_path.stat().st_size
    return ok_result(
        operation="actions.get_job_log",
        data={
            "job_id": job_id,
            "cwd": str(cwd),
            "job_dir": str(job_dir),
            "log_path": str(log_path),
            "bytes": log_path.stat().st_size,
            "content_returned": False,
        },
        evidence=evidence,
        meta={"repo": repo},
    )


async def list_artifacts(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    run_id = params.get("run_id")
    suffix = f"/actions/runs/{path_segment(str(run_id))}/artifacts" if run_id else "/actions/artifacts"
    data, evidence = await client.request_json(
        "GET",
        repo_path(repo, suffix),
        params=page_params(params),
    )
    return ok_result(operation="actions.list_artifacts", data=data, evidence=evidence, meta={"repo": repo})


async def download_artifact(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    if "target_dir" in params:
        raise PlatformError(
            "forbidden_param",
            "actions.download_artifact 不允许传 target_dir；请传 cwd，文件固定写入 cwd/jobs/<job_id>/artifact/",
            {"param": "target_dir"},
        )
    cwd = workspace_root(params)
    job_id = required_param(params, "job_id")
    artifact_id = required_param(params, "artifact_id")
    artifact_name = safe_name(str(params.get("artifact_name") or f"artifact-{artifact_id}"))
    extract = bool(params.get("extract", True))
    job_dir = job_output_dir(cwd, job_id)
    artifact_dir = job_dir / "artifact"
    zip_path = artifact_dir / f"{artifact_name}.zip"
    assert_relative_to_root(artifact_dir, cwd)
    assert_relative_to_root(zip_path, cwd)
    evidence = await client.download(
        repo_path(repo, f"/actions/artifacts/{path_segment(artifact_id)}/zip"),
        zip_path,
    )

    extracted_files: list[str] = []
    if extract:
        extracted_files = extract_zip(zip_path, artifact_dir)

    return ok_result(
        operation="actions.download_artifact",
        data={
            "artifact_id": artifact_id,
            "job_id": job_id,
            "artifact_name": artifact_name,
            "cwd": str(cwd),
            "job_dir": str(job_dir),
            "zip_path": str(zip_path),
            "artifact_dir": str(artifact_dir),
            "extracted": extract,
            "extracted_files": extracted_files,
        },
        evidence=evidence,
        meta={"repo": repo},
    )


async def list_runners(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    data, evidence = await client.request_json(
        "GET",
        repo_path(repo, "/actions/runners"),
        params=filter_params(params, {"disabled"}),
    )
    return ok_result(operation="actions.list_runners", data=data, evidence=evidence, meta={"repo": repo})


def require_repo(repo: str | None) -> None:
    if not repo:
        raise PlatformError("missing_repo", "该 operation 需要 repo 参数", {"repo_format": "owner/repo"})


def required_param(params: dict[str, Any], name: str) -> str:
    value = params.get(name)
    if value is None or str(value).strip() == "":
        raise PlatformError("missing_param", f"缺少 params.{name}", {"param": name})
    return str(value).strip()


def filter_params(params: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {
        key: value
        for key, value in params.items()
        if key in allowed and value is not None and value != ""
    }


def page_params(params: dict[str, Any]) -> dict[str, Any]:
    return filter_params(params, {"page", "limit"})


def safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value.strip())
    return cleaned.strip(".-") or "unnamed"


def path_segment(value: str) -> str:
    return quote(value, safe="")


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
                raise PlatformError(
                    "unsafe_artifact_zip",
                    "artifact zip 包含越界路径",
                    {"member": member.filename},
                ) from exc
            member_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, member_path.open("wb") as target:
                target.write(source.read())
            extracted.append(str(member_path))
    return extracted


def workspace_root(params: dict[str, Any]) -> Path:
    raw = required_param(params, "cwd")
    root = Path(raw).resolve()
    if not root.is_dir():
        raise PlatformError(
            "invalid_cwd",
            "params.cwd 必须是已存在的目录",
            {"cwd": raw, "resolved": str(root)},
        )
    return root


def job_output_dir(cwd: Path, job_id: str) -> Path:
    return cwd / "jobs" / safe_name(job_id)


def assert_relative_to_root(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PlatformError(
            "artifact_path_outside_root",
            "artifact 目标路径不在 params.cwd 内",
            {"path": str(path), "cwd": str(root)},
        ) from exc


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
    "actions.list_run_jobs": list_run_jobs,
    "actions.get_job": get_job,
    "actions.get_job_log": get_job_log,
    "actions.list_artifacts": list_artifacts,
    "actions.download_artifact": download_artifact,
    "actions.list_runners": list_runners,
}
