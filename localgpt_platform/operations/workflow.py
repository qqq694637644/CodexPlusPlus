from __future__ import annotations

from typing import Any

from localgpt_platform.gitea import GiteaClient, repo_path
from localgpt_platform.result import PlatformError, ok_result

from .schemas import (
    compact_job,
    compact_run,
    expect_object,
    expect_object_or_none,
    expect_keyed_object_list,
    int_param,
    path_segment,
    require_confirm,
    require_dispatch_run_details,
    require_expected_match,
    require_job_run_id,
    require_repo,
    required_param,
    run_matches_created_after,
    sort_runs,
    string_map_param,
    workflow_runs_path,
)


async def workflow_rerun_job(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    require_confirm(params)
    run_id = required_param(params, "run_id")
    job_id = required_param(params, "job_id")
    evidence: list[dict[str, Any]] = []
    job_path = repo_path(repo, f"/actions/jobs/{path_segment(job_id)}")
    job_data, job_evidence = await client.request_json("GET", job_path, step="workflow.rerun_job.get_job")
    job_obj = expect_object(job_data, step="workflow.rerun_job.get_job", path=job_path)
    evidence.append(job_evidence)
    require_expected_match(require_job_run_id(job_obj, step="workflow.rerun_job.get_job"), run_id, field="run_id", step="workflow.rerun_job.get_job")
    require_expected_match(job_obj.get("status"), params.get("expected_status"), field="status", step="workflow.rerun_job.get_job")
    require_expected_match(job_obj.get("conclusion"), params.get("expected_conclusion"), field="conclusion", step="workflow.rerun_job.get_job")

    rerun_path = repo_path(repo, f"/actions/runs/{path_segment(run_id)}/jobs/{path_segment(job_id)}/rerun")
    rerun_data, rerun_evidence = await client.request_json("POST", rerun_path, json_body={}, step="workflow.rerun_job.post_rerun")
    rerun_response = expect_object_or_none(rerun_data, step="workflow.rerun_job.post_rerun", path=rerun_path)
    evidence.append(rerun_evidence)
    return ok_result(
        operation="workflow.rerun_job",
        data={"job": compact_job(job_obj), "rerun_response": rerun_response, "content_returned": False},
        evidence=evidence,
        meta={"repo": repo, "run_id": run_id, "job_id": job_id},
        next_suggested_operations=["ci.get_run_summary"],
    )

async def workflow_rerun_run(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    require_confirm(params)
    run_id = required_param(params, "run_id")
    expected_head_sha = required_param(params, "expected_head_sha")
    evidence: list[dict[str, Any]] = []
    run_path = repo_path(repo, f"/actions/runs/{path_segment(run_id)}")
    run_data, run_evidence = await client.request_json("GET", run_path, step="workflow.rerun_run.get_run")
    run_obj = expect_object(run_data, step="workflow.rerun_run.get_run", path=run_path)
    evidence.append(run_evidence)
    require_expected_match(run_obj.get("head_sha"), expected_head_sha, field="head_sha", step="workflow.rerun_run.get_run")
    require_expected_match(run_obj.get("status"), params.get("expected_status"), field="status", step="workflow.rerun_run.get_run")
    require_expected_match(run_obj.get("conclusion"), params.get("expected_conclusion"), field="conclusion", step="workflow.rerun_run.get_run")

    rerun_path = repo_path(repo, f"/actions/runs/{path_segment(run_id)}/rerun")
    rerun_data, rerun_evidence = await client.request_json("POST", rerun_path, json_body={}, step="workflow.rerun_run.post_rerun")
    rerun_response = expect_object_or_none(rerun_data, step="workflow.rerun_run.post_rerun", path=rerun_path)
    evidence.append(rerun_evidence)
    return ok_result(
        operation="workflow.rerun_run",
        data={"run": compact_run(run_obj), "rerun_response": rerun_response, "content_returned": False},
        evidence=evidence,
        meta={"repo": repo, "run_id": run_id},
        next_suggested_operations=["ci.get_run_summary"],
    )

async def workflow_dispatch_and_track(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    require_confirm(params)
    workflow_id = required_param(params, "workflow_id")
    ref = required_param(params, "ref")
    inputs = string_map_param(params, "inputs")
    evidence: list[dict[str, Any]] = []
    dispatch_path = repo_path(repo, f"/actions/workflows/{path_segment(workflow_id)}/dispatches")
    body: dict[str, Any] = {"ref": ref}
    if inputs:
        body["inputs"] = inputs
    dispatch_data, dispatch_evidence = await client.request_json(
        "POST",
        dispatch_path,
        params={"return_run_details": True},
        json_body=body,
        step="workflow.dispatch_and_track.dispatch",
    )
    dispatch_run_details = require_dispatch_run_details(dispatch_data, step="workflow.dispatch_and_track.dispatch", path=dispatch_path)
    evidence.append(dispatch_evidence)

    runs_path = workflow_runs_path(repo, workflow_id)
    candidate_limit = int_param(params, "candidate_limit", 10, minimum=1)
    run_params = {"branch": ref, "limit": candidate_limit}
    if params.get("actor"):
        run_params["actor"] = params["actor"]
    runs_data, runs_evidence = await client.request_json("GET", runs_path, params=run_params, step="workflow.dispatch_and_track.list_candidate_runs")
    runs = expect_keyed_object_list(runs_data, step="workflow.dispatch_and_track.list_candidate_runs", path=runs_path, keys=("workflow_runs",))
    candidates = [run for run in sort_runs(runs) if run_matches_created_after(run, params.get("created_after"))]
    runs_evidence["result_count"] = len(candidates)
    evidence.append(runs_evidence)
    workflow_run_id = dispatch_run_details["workflow_run_id"]
    return ok_result(
        operation="workflow.dispatch_and_track",
        data={
            "dispatch_run_details": dispatch_run_details,
            "workflow_run_id": workflow_run_id,
            "candidate_count": len(candidates),
            "candidate_runs": [compact_run(run) for run in candidates],
            "matched": True,
            "match_status": "dispatch_run_details",
            "content_returned": False,
        },
        evidence=evidence,
        meta={"repo": repo, "workflow_id": workflow_id, "ref": ref},
        next_suggested_operations=["ci.get_run_summary"],
    )
