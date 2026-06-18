from __future__ import annotations

from typing import Any

from localgpt_platform.gitea import GiteaClient, repo_path
from localgpt_platform.result import PlatformError, ok_result

from .artifact import download_job_log_to_path
from .schemas import (
    bool_param,
    compact_artifact,
    compact_job,
    compact_run,
    count_field_values,
    expect_keyed_object_list,
    expect_object,
    filter_params,
    int_param,
    is_failed_job,
    is_queued_or_in_progress_job,
    page_params,
    path_segment,
    require_repo,
    require_response_field,
    required_param,
    sort_runs,
    workflow_runs_path,
    workspace_root,
)


async def ci_find_run_candidates(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    path = workflow_runs_path(repo, params.get("workflow_id"))
    run_params = filter_params(params, {"event", "branch", "status", "actor", "head_sha", "page"})
    run_params["limit"] = int_param(params, "limit", 10, minimum=1)
    data, evidence = await client.request_json("GET", path, params=run_params, step="ci.find_run_candidates.list_runs")
    runs = expect_keyed_object_list(data, step="ci.find_run_candidates.list_runs", path=path, keys=("workflow_runs",))
    candidates = sort_runs(runs)
    evidence["result_count"] = len(candidates)
    return ok_result(
        operation="ci.find_run_candidates",
        data={
            "query": run_params,
            "candidate_count": len(candidates),
            "candidate_runs": [compact_run(run) for run in candidates],
            "content_returned": False,
        },
        evidence=evidence,
        meta={"repo": repo, "workflow_id": str(params.get("workflow_id")) if params.get("workflow_id") else None},
        next_suggested_operations=["ci.get_run_summary"] if candidates else [],
    )

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
    jobs = expect_keyed_object_list(jobs_data, step="ci.get_run_summary.list_jobs", path=jobs_path, keys=("jobs",))
    jobs_evidence["result_count"] = len(jobs)
    evidence.append(jobs_evidence)

    failed_count = sum(1 for job in jobs if is_failed_job(job))
    queued_in_progress_count = sum(1 for job in jobs if is_queued_or_in_progress_job(job))
    data = {
        "run": compact_run(run_obj),
        "jobs": [compact_job(job) for job in jobs],
        "job_count": len(jobs),
        "failed_like_job_count": failed_count,
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
    jobs = expect_keyed_object_list(jobs_data, step="ci.list_run_jobs", path=jobs_path, keys=("jobs",))
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
