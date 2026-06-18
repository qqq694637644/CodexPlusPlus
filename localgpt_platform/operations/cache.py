from __future__ import annotations

from typing import Any

from localgpt_platform.gitea import GiteaClient, repo_path
from localgpt_platform.result import ok_result

from .schemas import compact_run, expect_keyed_object_list, filter_params, int_param, require_repo, sort_runs


async def cache_diagnose(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    path = repo_path(repo, "/actions/runs")
    run_params = filter_params(params, {"branch", "head_sha", "event", "actor", "page"})
    run_params["status"] = str(params.get("status") or "failure")
    run_params["limit"] = int_param(params, "limit", 10, minimum=1)
    data, evidence = await client.request_json("GET", path, params=run_params, step="cache.diagnose.list_runs")
    runs = expect_keyed_object_list(data, step="cache.diagnose.list_runs", path=path, keys=("workflow_runs",))
    evidence["result_count"] = len(runs)
    return ok_result(
        operation="cache.diagnose",
        data={
            "official_cache_management_api": False,
            "candidate_runs": [compact_run(run) for run in sort_runs(runs)],
            "candidate_count": len(runs),
            "diagnosis_notes": [
                "当前 Gitea 官方 REST API 未提供与 GitHub Actions cache 等价的 repo cache list/delete 管理接口。",
                "请使用本地 shell 检查 workflow cache key、restore-keys、runner tool cache 和 job log。",
            ],
            "content_returned": False,
        },
        evidence=evidence,
        meta={"repo": repo},
        next_suggested_operations=["ci.prepare_failure_context"] if runs else [],
    )
