from __future__ import annotations

from typing import Any

from localgpt_platform.gitea import GiteaClient, repo_path
from localgpt_platform.result import ok_result

from .schemas import (
    compact_run,
    compact_runner,
    expect_keyed_object_list,
    filter_params,
    int_param,
    require_repo,
    sort_runs,
    summarize_runners,
    workflow_runs_path,
)


async def runner_diagnose_queue(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    evidence: list[dict[str, Any]] = []
    run_limit = int_param(params, "limit", 10, minimum=1)
    run_filters = filter_params(params, {"branch", "head_sha", "event", "actor", "page"})
    path = workflow_runs_path(repo, params.get("workflow_id"))

    queued_params = {**run_filters, "status": "queued", "limit": run_limit}
    queued_data, queued_evidence = await client.request_json("GET", path, params=queued_params, step="runner.diagnose_queue.list_queued_runs")
    queued_runs = expect_keyed_object_list(queued_data, step="runner.diagnose_queue.list_queued_runs", path=path, keys=("workflow_runs",))
    queued_evidence["result_count"] = len(queued_runs)
    evidence.append(queued_evidence)

    progress_params = {**run_filters, "status": "in_progress", "limit": run_limit}
    progress_data, progress_evidence = await client.request_json("GET", path, params=progress_params, step="runner.diagnose_queue.list_in_progress_runs")
    in_progress_runs = expect_keyed_object_list(progress_data, step="runner.diagnose_queue.list_in_progress_runs", path=path, keys=("workflow_runs",))
    progress_evidence["result_count"] = len(in_progress_runs)
    evidence.append(progress_evidence)

    runners_path = repo_path(repo, "/actions/runners")
    runners_data, runners_evidence = await client.request_json("GET", runners_path, params=filter_params(params, {"disabled"}), step="runner.diagnose_queue.list_runners")
    runners = expect_keyed_object_list(runners_data, step="runner.diagnose_queue.list_runners", path=runners_path, keys=("runners",))
    runners_evidence["result_count"] = len(runners)
    evidence.append(runners_evidence)

    return ok_result(
        operation="runner.diagnose_queue",
        data={
            "queued_run_count": len(queued_runs),
            "in_progress_run_count": len(in_progress_runs),
            "queued_runs": [compact_run(run) for run in sort_runs(queued_runs)],
            "in_progress_runs": [compact_run(run) for run in sort_runs(in_progress_runs)],
            "runner_summary": summarize_runners(runners),
            "runners": [compact_runner(runner) for runner in runners],
            "label_mismatch_hints": [],
            "content_returned": False,
        },
        evidence=evidence,
        meta={"repo": repo},
        next_suggested_operations=["ci.get_run_summary"] if queued_runs or in_progress_runs else [],
    )
