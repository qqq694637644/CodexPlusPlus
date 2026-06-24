from __future__ import annotations

from typing import Any

from localgpt_platform.gitea import GiteaClient, repo_path
from localgpt_platform.result import PlatformError, ok_result

from .schemas import (
    branch_query_from_dispatch_ref,
    compact_job,
    compact_run,
    expect_object,
    expect_object_or_none,
    expect_keyed_object_list,
    int_param,
    path_segment,
    require_confirm,
    require_expected_match,
    require_job_run_id,
    require_repo,
    required_param,
    run_matches_created_after,
    sort_runs,
    string_map_param,
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


def optional_dispatch_run_details(data: Any, *, step: str, path: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    if data is None:
        warnings.append(
            {
                "code": "missing_dispatch_run_details",
                "message": "workflow_dispatch 已成功，但响应未返回 run 详情；将改用候选 run 查询跟踪。",
                "step": step,
                "path": path,
            }
        )
        return None, warnings
    if not isinstance(data, dict):
        warnings.append(
            {
                "code": "unexpected_dispatch_response_shape",
                "message": "workflow_dispatch 已成功，但响应不是对象；将改用候选 run 查询跟踪。",
                "step": step,
                "path": path,
                "actual_type": type(data).__name__,
            }
        )
        return None, warnings

    workflow_run_id = data.get("workflow_run_id")
    if workflow_run_id is None or str(workflow_run_id).strip() == "":
        warnings.append(
            {
                "code": "missing_dispatch_workflow_run_id",
                "message": "workflow_dispatch 响应缺少 workflow_run_id；将改用候选 run 查询跟踪。",
                "step": step,
                "path": path,
                "actual_keys": sorted(str(key) for key in data.keys()),
            }
        )
        workflow_run_id_text = None
    else:
        workflow_run_id_text = str(workflow_run_id)

    return {
        "workflow_run_id": workflow_run_id_text,
        "run_url": data.get("run_url"),
        "html_url": data.get("html_url"),
    }, warnings


def _known_text_values(*values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            result.append(text)
    return result


def workflow_identity_parts(value: Any) -> tuple[str, str] | None:
    if value is None:
        return None
    text = str(value).strip().replace("\\", "/")
    if not text:
        return None
    workflow_part = text.split("@", 1)[0]
    return workflow_part, workflow_part.rsplit("/", 1)[-1]


def run_matches_dispatch_workflow(run: dict[str, Any], workflow_id: str) -> bool:
    workflow = run.get("workflow")
    workflow_values = _known_text_values(
        run.get("workflow_id"),
        run.get("workflow_name"),
        run.get("workflow_path"),
        run.get("path"),
        *(workflow.get(key) for key in ("id", "name", "path", "workflow_id") if isinstance(workflow, dict)),
    )
    if not workflow_values:
        return True

    expected_parts = workflow_identity_parts(workflow_id)
    if expected_parts is None:
        return True
    expected, expected_basename = expected_parts
    for value in workflow_values:
        value_parts = workflow_identity_parts(value)
        if value_parts is None:
            continue
        normalized, basename = value_parts
        if normalized == expected or basename == expected_basename or normalized.endswith(f"/{expected}"):
            return True
    return False


def run_matches_dispatch_branch(run: dict[str, Any], branch: str | None) -> bool:
    if not branch:
        return True
    values = _known_text_values(run.get("head_branch"), run.get("branch"), run.get("ref"))
    return not values or branch in values or f"refs/heads/{branch}" in values


def run_matches_dispatch_actor(run: dict[str, Any], actor: Any | None) -> bool:
    if actor is None or str(actor).strip() == "":
        return True
    expected = str(actor).strip()
    actor_obj = run.get("actor")
    trigger_actor = run.get("trigger_actor") or run.get("triggering_actor")
    values = _known_text_values(
        actor_obj,
        trigger_actor,
        *(actor_obj.get(key) for key in ("login", "username", "name", "id") if isinstance(actor_obj, dict)),
        *(trigger_actor.get(key) for key in ("login", "username", "name", "id") if isinstance(trigger_actor, dict)),
    )
    return not values or expected in values


def run_matches_workflow_dispatch(run: dict[str, Any], *, workflow_id: str, ref: str, actor: Any | None, created_after: Any | None) -> bool:
    event_values = _known_text_values(run.get("event"))
    return (
        (not event_values or "workflow_dispatch" in event_values)
        and run_matches_dispatch_workflow(run, workflow_id)
        and run_matches_dispatch_branch(run, branch_query_from_dispatch_ref(ref))
        and run_matches_dispatch_actor(run, actor)
        and run_matches_created_after(run, created_after)
    )


async def workflow_dispatch_and_track(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    require_confirm(params)
    workflow_id = required_param(params, "workflow_id")
    ref = required_param(params, "ref")
    inputs = string_map_param(params, "inputs")
    evidence: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
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
    dispatch_run_details, dispatch_warnings = optional_dispatch_run_details(dispatch_data, step="workflow.dispatch_and_track.dispatch", path=dispatch_path)
    warnings.extend(dispatch_warnings)
    evidence.append(dispatch_evidence)

    workflow_run_id = dispatch_run_details.get("workflow_run_id") if dispatch_run_details else None
    if workflow_run_id:
        return ok_result(
            operation="workflow.dispatch_and_track",
            data={
                "dispatch_run_details": dispatch_run_details,
                "workflow_run_id": workflow_run_id,
                "candidate_count": 0,
                "candidate_runs": [],
                "matched": True,
                "match_status": "dispatch_run_details",
                "content_returned": False,
            },
            evidence=evidence,
            warnings=warnings,
            meta={"repo": repo, "workflow_id": workflow_id, "ref": ref},
            next_suggested_operations=["ci.get_run_summary"],
        )

    runs_path = repo_path(repo, "/actions/runs")
    candidate_limit = int_param(params, "candidate_limit", 10, minimum=1)
    run_params: dict[str, Any] = {"event": "workflow_dispatch", "limit": candidate_limit}
    branch = branch_query_from_dispatch_ref(ref)
    if branch:
        run_params["branch"] = branch
    if params.get("actor"):
        run_params["actor"] = params["actor"]
    tracking_failed = False
    candidates: list[dict[str, Any]] = []
    try:
        runs_data, runs_evidence = await client.request_json("GET", runs_path, params=run_params, step="workflow.dispatch_and_track.list_candidate_runs")
        runs = expect_keyed_object_list(runs_data, step="workflow.dispatch_and_track.list_candidate_runs", path=runs_path, keys=("workflow_runs",))
        candidates = [
            run
            for run in sort_runs(runs)
            if run_matches_workflow_dispatch(run, workflow_id=workflow_id, ref=ref, actor=params.get("actor"), created_after=params.get("created_after"))
        ]
        runs_evidence["result_count"] = len(candidates)
        evidence.append(runs_evidence)
    except PlatformError as exc:
        tracking_failed = True
        warnings.append(
            {
                "code": "candidate_run_tracking_failed",
                "message": "workflow_dispatch 已成功，但候选 run 查询失败；按 dispatch 成功返回，请用 workflow_run_id 或 actions.list_runs 继续确认。",
                "error": exc.to_dict(),
            }
        )

    if candidates:
        candidate_id = candidates[0].get("id") or candidates[0].get("run_id")
        workflow_run_id = str(candidate_id) if candidate_id is not None and str(candidate_id).strip() else None

    if tracking_failed:
        match_status = "tracking_failed"
    elif candidates:
        match_status = "candidate_runs"
    else:
        match_status = "no_candidate_runs"

    return ok_result(
        operation="workflow.dispatch_and_track",
        data={
            "dispatch_run_details": dispatch_run_details,
            "workflow_run_id": workflow_run_id,
            "candidate_count": len(candidates),
            "candidate_runs": [compact_run(run) for run in candidates],
            "matched": bool(workflow_run_id or candidates),
            "match_status": match_status,
            "content_returned": False,
        },
        evidence=evidence,
        warnings=warnings,
        meta={"repo": repo, "workflow_id": workflow_id, "ref": ref},
        next_suggested_operations=["ci.get_run_summary"] if workflow_run_id or candidates else ["actions.list_runs"],
    )
