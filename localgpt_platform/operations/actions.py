from __future__ import annotations

from typing import Any

from localgpt_platform.gitea import GiteaClient, repo_path
from localgpt_platform.result import ok_result

from .artifact import download_job_log_to_path
from .schemas import (
    expect_keyed_object_list,
    expect_object,
    filter_params,
    page_params,
    path_segment,
    require_repo,
    required_param,
    workflow_runs_path,
    workspace_root,
)


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
    path = workflow_runs_path(repo, params.get("workflow_id"))
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

async def list_run_jobs(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    run_id = required_param(params, "run_id")
    attempt = params.get("attempt")
    suffix = f"/actions/runs/{path_segment(run_id)}/attempts/{path_segment(str(attempt))}/jobs" if attempt else f"/actions/runs/{path_segment(run_id)}/jobs"
    path = repo_path(repo, suffix)
    data, evidence = await client.request_json("GET", path, params=page_params(params), step="actions.list_run_jobs")
    jobs = expect_keyed_object_list(data, step="actions.list_run_jobs", path=path, keys=("jobs",))
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

async def list_runners(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    path = repo_path(repo, "/actions/runners")
    data, evidence = await client.request_json("GET", path, params=filter_params(params, {"disabled"}), step="actions.list_runners")
    runners = expect_keyed_object_list(data, step="actions.list_runners", path=path, keys=("runners",))
    evidence["result_count"] = len(runners)
    return ok_result(operation="actions.list_runners", data=data, evidence=evidence, meta={"repo": repo})
