from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from localgpt_platform.gitea import repo_path
from localgpt_platform.result import PlatformError

_FAILED_CONCLUSIONS = {"failure", "cancelled", "timed_out", "startup_failure", "action_required"}
_FAILED_STATUSES = {"failure", "cancelled", "timed_out"}
_NONTERMINAL_RUN_STATES = {"queued", "in_progress", "pending", "waiting", "running", "requested", "created"}


def require_repo(repo: str | None) -> None:
    if not repo:
        raise PlatformError("missing_repo", "该 operation 需要 repo 参数", {"repo_format": "owner/repo"})

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

def string_map_param(params: dict[str, Any], name: str) -> dict[str, str] | None:
    value = params.get(name)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise PlatformError(
            "invalid_param",
            f"params.{name} 必须是 object[string,string]",
            {"param": name, "actual_type": type(value).__name__},
        )
    result: dict[str, str] = {}
    invalid: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            invalid[str(key)] = f"invalid_key:{type(key).__name__}"
            continue
        if not isinstance(item, str):
            invalid[key] = type(item).__name__
            continue
        result[key] = item
    if invalid:
        raise PlatformError(
            "invalid_param",
            f"params.{name} 必须是 object[string,string]",
            {"param": name, "invalid_entries": invalid},
        )
    return result

def safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value.strip())
    return cleaned.strip(".-") or "unnamed"

def path_segment(value: str) -> str:
    return quote(value, safe="")

def workflow_runs_path(repo: str, workflow_id: Any | None = None) -> str:
    if workflow_id is None or str(workflow_id).strip() == "":
        return repo_path(repo, "/actions/runs")
    return repo_path(repo, f"/actions/workflows/{path_segment(str(workflow_id).strip())}/runs")

def branch_query_from_dispatch_ref(ref: str) -> str | None:
    if ref.startswith("refs/heads/"):
        branch = ref.removeprefix("refs/heads/")
        return branch or None
    if ref.startswith("refs/tags/"):
        return None
    if ref.startswith("refs/"):
        return None
    return ref or None

def require_confirm(params: dict[str, Any]) -> None:
    if params.get("confirm") is not True:
        raise PlatformError("confirmation_required", "远端写 operation 需要 params.confirm=true", {"param": "confirm"})

def require_expected_match(actual: Any, expected: Any, *, field: str, step: str) -> None:
    if expected is None or str(expected).strip() == "":
        return
    if actual is None or str(actual) != str(expected):
        raise PlatformError(
            "expected_mismatch",
            "远端状态与 expected_* 参数不匹配，拒绝继续执行写操作",
            {"step": step, "field": field, "expected": str(expected), "actual": None if actual is None else str(actual)},
        )

def expect_object_or_none(data: Any, *, step: str, path: str) -> dict[str, Any] | None:
    if data is None:
        return None
    return expect_object(data, step=step, path=path)

def require_dispatch_run_details(data: Any, *, step: str, path: str) -> dict[str, Any]:
    obj = expect_object(data, step=step, path=path)
    workflow_run_id = require_response_field(obj, "workflow_run_id", step=step, path=path)
    return {
        "workflow_run_id": str(workflow_run_id),
        "run_url": obj.get("run_url"),
        "html_url": obj.get("html_url"),
    }

def run_matches_created_after(run: dict[str, Any], created_after: Any | None) -> bool:
    if created_after is None or str(created_after).strip() == "":
        return True
    created = run.get("created_at")
    if created is None:
        return False
    return str(created) >= str(created_after).strip()

def sort_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(runs, key=lambda run: (str(run.get("created_at") or ""), int(run.get("id") or 0)), reverse=True)

def job_run_id(job: dict[str, Any]) -> Any:
    for key in ("run_id", "workflow_run_id"):
        if job.get(key) is not None:
            return job.get(key)
    workflow_run = job.get("workflow_run")
    if isinstance(workflow_run, dict):
        return workflow_run.get("id") or workflow_run.get("run_id")
    return None

def require_job_run_id(job: dict[str, Any], *, step: str) -> Any:
    value = job_run_id(job)
    if value is None or str(value).strip() == "":
        raise PlatformError("missing_response_field", "Gitea API 响应缺少 job 所属 run_id，拒绝执行 job rerun", {"step": step, "field": "run_id", "actual_keys": sorted(str(key) for key in job.keys())})
    return value

def pr_head_sha(pr: dict[str, Any]) -> str | None:
    head = pr.get("head")
    if isinstance(head, dict) and head.get("sha"):
        return str(head["sha"])
    if pr.get("head_sha"):
        return str(pr["head_sha"])
    return None

def parse_expected_id_set(value: Any) -> set[str]:
    if value is None or value == "":
        return set()
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    return {part.strip() for part in str(value).split(",") if part.strip()}

def run_identity(run: dict[str, Any]) -> str | None:
    value = run.get("id") or run.get("run_id")
    return str(value) if value is not None and str(value).strip() else None

def run_state_for_merge(run: dict[str, Any]) -> str:
    conclusion = str(run.get("conclusion") or "").lower()
    status = str(run.get("status") or "").lower()
    if conclusion in _NONTERMINAL_RUN_STATES or status in _NONTERMINAL_RUN_STATES:
        return "nonterminal"
    if conclusion:
        return "success" if conclusion == "success" else "not_success"
    if status == "success":
        return "success"
    if status in _FAILED_STATUSES or status in {"failure", "cancelled", "timed_out"}:
        return "not_success"
    return "unknown"

def ensure_ci_success_for_merge(runs: list[dict[str, Any]], *, expected_run_ids: set[str] | None = None) -> None:
    if not runs:
        raise PlatformError("ci_required", "require_ci_success=true 但未找到 head_sha 对应 CI runs", {})
    if expected_run_ids:
        found = {identity for run in runs if (identity := run_identity(run))}
        missing = sorted(expected_run_ids - found)
        if missing:
            raise PlatformError("ci_expected_runs_missing", "require_ci_success=true 但缺少 expected_run_ids 对应 CI runs", {"missing_run_ids": missing, "found_run_ids": sorted(found)})
        checked_runs = [run for run in runs if run_identity(run) in expected_run_ids]
    else:
        checked_runs = runs
    nonterminal = [compact_run(run) for run in checked_runs if run_state_for_merge(run) == "nonterminal"]
    if nonterminal:
        raise PlatformError("ci_not_complete", "head_sha 存在 queued/in_progress/pending CI run，拒绝合并", {"nonterminal_runs": nonterminal})
    not_success = [compact_run(run) for run in checked_runs if run_state_for_merge(run) == "not_success"]
    if not_success:
        raise PlatformError("ci_not_success", "head_sha 存在非 success CI run，拒绝合并", {"runs": not_success})
    unknown = [compact_run(run) for run in checked_runs if run_state_for_merge(run) == "unknown"]
    if unknown:
        raise PlatformError("ci_state_unknown", "head_sha 存在未知状态 CI run，拒绝合并", {"unknown_runs": unknown})
    if not checked_runs:
        raise PlatformError("ci_required", "require_ci_success=true 但没有可校验 CI runs", {})

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

def compact_runner(runner: Any) -> dict[str, Any]:
    obj = ensure_compact_object(runner, name="compact_runner")
    return {
        key: obj.get(key)
        for key in ("id", "uuid", "name", "status", "online", "busy", "disabled", "labels", "version", "os", "architecture", "last_online")
        if obj.get(key) is not None
    }

def compact_comment(comment: Any) -> dict[str, Any]:
    obj = ensure_compact_object(comment, name="compact_comment")
    return {key: obj.get(key) for key in ("id", "html_url", "created_at", "updated_at") if obj.get(key) is not None}

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

def summarize_runners(runners: list[dict[str, Any]]) -> dict[str, Any]:
    disabled_count = sum(1 for runner in runners if bool(runner.get("disabled")))
    busy_count = sum(1 for runner in runners if bool(runner.get("busy")))
    online_count = 0
    offline_count = 0
    for runner in runners:
        status = str(runner.get("status") or "").lower()
        online = runner.get("online")
        if online is True or status == "online":
            online_count += 1
        elif online is False or status == "offline":
            offline_count += 1
    labels: dict[str, int] = {}
    for runner in runners:
        raw_labels = runner.get("labels")
        if isinstance(raw_labels, list):
            for label in raw_labels:
                text = str(label.get("name") if isinstance(label, dict) else label).strip()
                if text:
                    labels[text] = labels.get(text, 0) + 1
    return {
        "runner_count": len(runners),
        "disabled_count": disabled_count,
        "busy_count": busy_count,
        "online_count": online_count,
        "offline_count": offline_count,
        "labels": dict(sorted(labels.items())),
    }

def is_failed_run(run: dict[str, Any]) -> bool:
    conclusion = str(run.get("conclusion") or "").lower()
    status = str(run.get("status") or "").lower()
    return conclusion in _FAILED_CONCLUSIONS or status in _FAILED_STATUSES or status == "failure"

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
