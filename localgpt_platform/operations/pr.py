from __future__ import annotations

import hashlib
from typing import Any

from localgpt_platform.gitea import GiteaClient, repo_path
from localgpt_platform.result import PlatformError, ok_result

from .schemas import (
    bool_param,
    compact_comment,
    compact_file,
    compact_pr,
    compact_ref,
    compact_run,
    ensure_ci_success_for_merge,
    expect_keyed_object_list,
    expect_nested_object,
    expect_object,
    expect_object_or_none,
    expect_top_level_object_list,
    int_param,
    is_failed_run,
    parse_expected_id_set,
    path_segment,
    pr_head_sha,
    require_confirm,
    require_expected_match,
    require_repo,
    require_response_field,
    required_param,
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

async def pr_publish(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    require_confirm(params)
    mode = required_param(params, "mode").lower()
    expected_head_sha = required_param(params, "expected_head_sha")
    if mode not in {"create", "update"}:
        raise PlatformError("invalid_param", "params.mode 只支持 create 或 update；开发阶段不做 upsert", {"param": "mode", "value": mode})
    evidence: list[dict[str, Any]] = []
    if mode == "create":
        body = {"head": required_param(params, "head"), "base": required_param(params, "base"), "title": required_param(params, "title")}
        if params.get("body") is not None:
            body["body"] = str(params["body"])
        path = repo_path(repo, "/pulls")
        pr_data, pr_evidence = await client.request_json("POST", path, json_body=body, step="pr.publish.create")
        pr_obj = expect_object(pr_data, step="pr.publish.create", path=path)
        evidence.append(pr_evidence)
        created_or_updated = "created"
    else:
        pr_number = required_param(params, "existing_pr_number")
        get_path = repo_path(repo, f"/pulls/{path_segment(pr_number)}")
        current_data, current_evidence = await client.request_json("GET", get_path, step="pr.publish.get_existing")
        current_pr = expect_object(current_data, step="pr.publish.get_existing", path=get_path)
        evidence.append(current_evidence)
        require_expected_match(pr_head_sha(current_pr), expected_head_sha, field="head.sha", step="pr.publish.get_existing")
        body = {key: params[key] for key in ("title", "body", "base") if key in params and params[key] is not None}
        if not body:
            raise PlatformError("missing_param", "update 模式需要至少一个可更新字段：title/body/base", {"params": ["title", "body", "base"]})
        pr_data, pr_evidence = await client.request_json("PATCH", get_path, json_body=body, step="pr.publish.update")
        pr_obj = expect_object(pr_data, step="pr.publish.update", path=get_path)
        evidence.append(pr_evidence)
        created_or_updated = "updated"
    require_expected_match(pr_head_sha(pr_obj), expected_head_sha, field="head.sha", step="pr.publish.verify_head")
    return ok_result(
        operation="pr.publish",
        data={"pr": compact_pr(pr_obj), "head": compact_ref(expect_nested_object(pr_obj, "head", step="pr.publish.verify_head", path="response")), "created_or_updated": created_or_updated, "content_returned": False},
        evidence=evidence,
        meta={"repo": repo, "mode": mode},
    )

async def pr_comment(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    require_confirm(params)
    pr_number = required_param(params, "pr_number")
    body = required_param(params, "body")
    max_body_chars = int_param(params, "max_body_chars", 60000, minimum=1)
    if len(body) > max_body_chars:
        raise PlatformError("body_too_large", "PR comment body 超过上限", {"body_length": len(body), "max_body_chars": max_body_chars})
    path = repo_path(repo, f"/issues/{path_segment(pr_number)}/comments")
    data, evidence = await client.request_json("POST", path, json_body={"body": body}, step="pr.comment.create")
    comment = expect_object(data, step="pr.comment.create", path=path)
    return ok_result(
        operation="pr.comment",
        data={"comment": compact_comment(comment), "body_length": len(body), "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(), "content_returned": False},
        evidence=evidence,
        meta={"repo": repo, "pr_number": pr_number},
    )

async def pr_merge(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    require_confirm(params)
    pr_number = required_param(params, "pr_number")
    expected_head_sha = required_param(params, "expected_head_sha")
    base_branch = required_param(params, "base_branch")
    merge_method = required_param(params, "merge_method")
    if merge_method not in {"merge", "rebase", "rebase-merge", "squash"}:
        raise PlatformError("invalid_param", "params.merge_method 必须是 merge/rebase/rebase-merge/squash", {"param": "merge_method", "value": merge_method})
    evidence: list[dict[str, Any]] = []
    pr_path = repo_path(repo, f"/pulls/{path_segment(pr_number)}")
    pr_data, pr_evidence = await client.request_json("GET", pr_path, step="pr.merge.get_pr")
    pr_obj = expect_object(pr_data, step="pr.merge.get_pr", path=pr_path)
    evidence.append(pr_evidence)
    head = expect_nested_object(pr_obj, "head", step="pr.merge.get_pr", path=pr_path)
    base = expect_nested_object(pr_obj, "base", step="pr.merge.get_pr", path=pr_path)
    require_expected_match(require_response_field(head, "sha", step="pr.merge.get_pr", path=pr_path), expected_head_sha, field="head.sha", step="pr.merge.get_pr")
    require_expected_match(require_response_field(base, "ref", step="pr.merge.get_pr", path=pr_path), base_branch, field="base.ref", step="pr.merge.get_pr")
    if bool_param(params, "require_ci_success", True):
        ci_path = repo_path(repo, "/actions/runs")
        ci_params = {"head_sha": expected_head_sha, "limit": int_param(params, "ci_limit", 100, minimum=1)}
        runs_data, runs_evidence = await client.request_json("GET", ci_path, params=ci_params, step="pr.merge.list_head_ci_runs")
        runs = expect_keyed_object_list(runs_data, step="pr.merge.list_head_ci_runs", path=ci_path, keys=("workflow_runs",))
        runs_evidence["result_count"] = len(runs)
        evidence.append(runs_evidence)
        ensure_ci_success_for_merge(runs, expected_run_ids=parse_expected_id_set(params.get("expected_run_ids")))
    merge_body: dict[str, Any] = {"do": merge_method}
    if params.get("merge_title") is not None:
        merge_body["merge_title_field"] = str(params["merge_title"])
    if params.get("merge_message") is not None:
        merge_body["merge_message_field"] = str(params["merge_message"])
    if params.get("delete_branch_after_merge") is not None:
        merge_body["delete_branch_after_merge"] = bool_param(params, "delete_branch_after_merge", False)
    merge_path = repo_path(repo, f"/pulls/{path_segment(pr_number)}/merge")
    merge_data, merge_evidence = await client.request_json("POST", merge_path, json_body=merge_body, step="pr.merge.post_merge")
    merge_response = expect_object_or_none(merge_data, step="pr.merge.post_merge", path=merge_path)
    evidence.append(merge_evidence)
    return ok_result(
        operation="pr.merge",
        data={"pr": compact_pr(pr_obj), "merge_response": merge_response, "content_returned": False},
        evidence=evidence,
        meta={"repo": repo, "pr_number": pr_number, "merge_method": merge_method},
    )
