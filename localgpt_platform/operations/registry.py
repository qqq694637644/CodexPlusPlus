from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from localgpt_platform.config import load_gitea_config
from localgpt_platform.gitea import GiteaClient
from localgpt_platform.result import PlatformError, error_result, ok_result

from .actions import (
    auth_whoami,
    download_job_log,
    get_job,
    get_repo,
    get_run,
    get_workflow,
    list_run_jobs,
    list_runners,
    list_runs,
    list_workflows,
    server_version,
)
from .artifact import artifact_sync_for_run, download_artifact, list_artifacts
from .cache import cache_diagnose
from .ci import ci_find_run_candidates, ci_get_run_summary, ci_prepare_failure_context
from .pr import pr_comment, pr_merge, pr_preflight, pr_publish
from .runner import runner_diagnose_queue
from .schemas import bool_param, compact_user, expect_object, string_map_param
from .workflow import workflow_dispatch_and_track, workflow_rerun_job, workflow_rerun_run

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
            "workflow_id": "string/integer，传入时查询指定 workflow 的 runs",
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
    "ci.find_run_candidates": operation_spec(
        category="ci",
        description="按 branch/head_sha/status/workflow_id/event 查询候选 runs，返回紧凑排序摘要，不下载日志。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={},
        optional_params={
            "workflow_id": "string/integer，传入时查询指定 workflow 的 runs",
            "branch": "string，workflow branch",
            "head_sha": "string，触发 commit sha",
            "status": "string，pending/queued/in_progress/failure/success/skipped",
            "event": "string，workflow event name",
            "actor": "string，触发用户",
            "page": "integer，页码，1 起始",
            "limit": "integer，每页数量；默认 10",
        },
        returns={"data": "candidate_runs、candidate_count、query、content_returned=false。", "evidence": "list runs 调用证据。"},
        example={"operation": "ci.find_run_candidates", "repo": "owner/repo", "params": {"head_sha": "abc123", "status": "failure", "limit": 10}},
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
        returns={"data": "run compact summary、jobs compact summary、job_count、failed_like_job_count、queued_in_progress_job_count、status_counts、conclusion_counts、content_returned=false。", "evidence": "GET run 和 GET jobs 调用证据。"},
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
        returns={"data": "必须是包含 jobs: list[object] 的 Gitea run jobs 响应。", "evidence": "含 page/limit 和 result_count 的调用证据。"},
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
    "runner.diagnose_queue": operation_spec(
        category="runner",
        description="查询 queued/in_progress runs 和 repo runners，返回 runner 队列诊断事实摘要。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={},
        optional_params={"branch": "string，过滤 queued/in_progress runs", "head_sha": "string，过滤 queued/in_progress runs", "workflow_id": "string/integer，限制 workflow", "page": "integer，页码", "limit": "integer，每类 run 数量；默认 10", "disabled": "boolean，runner disabled 过滤"},
        returns={"data": "queued_runs、in_progress_runs、runner_summary、runners、content_returned=false。", "evidence": "queued/in_progress runs 和 runners 查询证据。"},
        example={"operation": "runner.diagnose_queue", "repo": "owner/repo", "params": {"limit": 10}},
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
    "workflow.rerun_job": operation_spec(
        category="workflow",
        description="显式重跑单个 job。远端写操作，先读取 job 并校验 run_id/expected_*。",
        repo_required=True,
        read_only_remote=False,
        writes_local_files=False,
        writes_remote=True,
        requires_cwd=False,
        required_params={"run_id": "integer/string，job 所属 workflow run id", "job_id": "integer/string，job id", "confirm": "boolean，必须是 JSON true"},
        optional_params={"expected_status": "string，校验当前 job status", "expected_conclusion": "string，校验当前 job conclusion"},
        returns={"data": "job summary、rerun_response、content_returned=false。", "evidence": "GET job 和 run-scoped POST rerun 证据。"},
        example={"operation": "workflow.rerun_job", "repo": "owner/repo", "params": {"run_id": 123, "job_id": 456, "expected_status": "failure", "confirm": True}},
        risk_level="high",
    ),
    "workflow.rerun_run": operation_spec(
        category="workflow",
        description="显式重跑整个 workflow run。远端写操作，先读取 run 并校验 expected_head_sha。",
        repo_required=True,
        read_only_remote=False,
        writes_local_files=False,
        writes_remote=True,
        requires_cwd=False,
        required_params={"run_id": "integer/string，workflow run id", "expected_head_sha": "string，当前 run head_sha", "confirm": "boolean，必须是 JSON true"},
        optional_params={"expected_status": "string，校验当前 run status", "expected_conclusion": "string，校验当前 run conclusion"},
        returns={"data": "run summary、rerun_response、content_returned=false。", "evidence": "GET run 和 POST rerun 证据。"},
        example={"operation": "workflow.rerun_run", "repo": "owner/repo", "params": {"run_id": 123, "expected_head_sha": "abc123", "confirm": True}},
        risk_level="high",
    ),
    "workflow.dispatch_and_track": operation_spec(
        category="workflow",
        description="触发 workflow_dispatch，并用 repo-scoped runs 接口按 workflow/ref/created_after/actor 本地筛选候选 runs。远端写操作。",
        repo_required=True,
        read_only_remote=False,
        writes_local_files=False,
        writes_remote=True,
        requires_cwd=False,
        required_params={"workflow_id": "string/integer，workflow id 或文件名", "ref": "string，dispatch ref", "confirm": "boolean，必须是 JSON true"},
        optional_params={"inputs": "object[string,string]，workflow_dispatch inputs", "created_after": "string，ISO 时间，本地过滤候选 runs", "actor": "string，触发用户过滤", "candidate_limit": "integer，候选 run 数量；默认 10"},
        returns={"data": "dispatch_run_details、workflow_run_id、candidate_runs、candidate_count、matched、match_status、content_returned=false。dispatch 成功但候选查询失败时 ok=true 并返回 warning。", "evidence": "dispatch 和候选 runs 查询证据。"},
        example={"operation": "workflow.dispatch_and_track", "repo": "owner/repo", "params": {"workflow_id": "ci.yml", "ref": "main", "confirm": True}},
        risk_level="high",
    ),
    "pr.publish": operation_spec(
        category="pr",
        description="创建或更新 PR。远端写操作；开发阶段只支持 mode=create/update，不做宽泛 upsert。",
        repo_required=True,
        read_only_remote=False,
        writes_local_files=False,
        writes_remote=True,
        requires_cwd=False,
        required_params={"mode": "create 或 update", "expected_head_sha": "string，创建/更新后 PR head sha 必须匹配", "confirm": "boolean，必须是 JSON true"},
        optional_params={"head": "string，create 必填", "base": "string，create 可用", "title": "string，create 必填；update 可选", "body": "string，create/update 可选", "existing_pr_number": "integer/string，update 必填"},
        returns={"data": "pr summary、created_or_updated、content_returned=false。", "evidence": "create/update 和必要 preflight 证据。"},
        example={"operation": "pr.publish", "repo": "owner/repo", "params": {"mode": "create", "head": "ai/fix", "base": "main", "title": "Fix CI", "body": "...", "expected_head_sha": "abc123", "confirm": True}},
        risk_level="high",
    ),
    "pr.comment": operation_spec(
        category="pr",
        description="给 PR 追加评论。远端写操作；evidence 不记录完整 body。",
        repo_required=True,
        read_only_remote=False,
        writes_local_files=False,
        writes_remote=True,
        requires_cwd=False,
        required_params={"pr_number": "integer/string，PR 编号", "body": "string，评论正文", "confirm": "boolean，必须是 JSON true"},
        optional_params={"max_body_chars": "integer，正文长度上限；默认 60000"},
        returns={"data": "comment summary、body_length、content_returned=false。", "evidence": "POST issue comments 调用证据。"},
        example={"operation": "pr.comment", "repo": "owner/repo", "params": {"pr_number": 42, "body": "CI failure summary", "confirm": True}},
        risk_level="high",
    ),
    "pr.merge": operation_spec(
        category="pr",
        description="合并 PR。远端写操作；强制 expected_head_sha、base_branch、confirm；默认要求 head_sha CI 全部完成且 success。",
        repo_required=True,
        read_only_remote=False,
        writes_local_files=False,
        writes_remote=True,
        requires_cwd=False,
        required_params={"pr_number": "integer/string，PR 编号", "expected_head_sha": "string，当前 PR head sha", "base_branch": "string，目标 base branch", "merge_method": "merge/rebase/rebase-merge/squash", "confirm": "boolean，必须是 JSON true"},
        optional_params={"require_ci_success": "boolean，默认 true", "expected_run_ids": "array/string，期望纳入 gate 的 run ids", "ci_limit": "integer，head_sha CI runs 查询数量；默认 100", "merge_title": "string", "merge_message": "string", "delete_branch_after_merge": "boolean"},
        returns={"data": "pr summary、merge_response、content_returned=false。", "evidence": "PR preflight、CI check 和 merge 调用证据。"},
        example={"operation": "pr.merge", "repo": "owner/repo", "params": {"pr_number": 42, "expected_head_sha": "abc123", "base_branch": "main", "merge_method": "merge", "confirm": True}},
        risk_level="high",
    ),
    "cache.diagnose": operation_spec(
        category="cache",
        description="提供 Gitea Actions cache 相关诊断边界和近期 runs 事实；不伪造官方 cache 管理 API。",
        repo_required=True,
        read_only_remote=True,
        writes_local_files=False,
        writes_remote=False,
        requires_cwd=False,
        required_params={},
        optional_params={"branch": "string，过滤近期 runs", "head_sha": "string，过滤近期 runs", "status": "string，默认 failure", "page": "integer，页码", "limit": "integer，run 数量；默认 10"},
        returns={"data": "official_cache_management_api=false、candidate_runs、diagnosis_notes、content_returned=false。", "evidence": "list runs 调用证据。"},
        example={"operation": "cache.diagnose", "repo": "owner/repo", "params": {"status": "failure", "limit": 10}},
        risk_level="low",
    ),
}

def describe_operations(*, category: str | None = None, operation: str | None = None, detail: str | None = None) -> dict[str, Any]:
    operation_name = operation.strip() if operation else None
    detail_value = (detail or ("full" if operation_name else "brief")).strip().lower()
    categories = sorted({spec["category"] for spec in OPERATION_SPECS.values()})
    base: dict[str, Any] = {
        "provider": "gitea",
        "write_operations_enabled": any(spec["writes_remote"] for spec in OPERATION_SPECS.values()),
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
    if spec["writes_remote"] and "confirm" in spec["required_params"]:
        if params.get("confirm") is not True:
            return PlatformError("confirmation_required", "远端写 operation 需要 params.confirm=true", {"param": "confirm"})
    if operation == "workflow.dispatch_and_track":
        try:
            string_map_param(params, "inputs")
        except PlatformError as exc:
            return exc
    return None

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
        if spec["writes_remote"] and not any(word in name for word in ("publish", "dispatch", "rerun", "delete", "merge", "comment")):
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
    "ci.find_run_candidates": ci_find_run_candidates,
    "actions.get_run": get_run,
    "ci.get_run_summary": ci_get_run_summary,
    "actions.list_run_jobs": list_run_jobs,
    "actions.get_job": get_job,
    "actions.download_job_log": download_job_log,
    "actions.list_artifacts": list_artifacts,
    "actions.download_artifact": download_artifact,
    "actions.list_runners": list_runners,
    "runner.diagnose_queue": runner_diagnose_queue,
    "ci.prepare_failure_context": ci_prepare_failure_context,
    "artifact.sync_for_run": artifact_sync_for_run,
    "pr.preflight": pr_preflight,
    "workflow.rerun_job": workflow_rerun_job,
    "workflow.rerun_run": workflow_rerun_run,
    "workflow.dispatch_and_track": workflow_dispatch_and_track,
    "pr.publish": pr_publish,
    "pr.comment": pr_comment,
    "pr.merge": pr_merge,
    "cache.diagnose": cache_diagnose,
}


validate_operation_specs()
