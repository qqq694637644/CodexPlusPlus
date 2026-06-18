from __future__ import annotations

import json
import fnmatch
import zipfile
from pathlib import Path
from typing import Any

from localgpt_platform.gitea import GiteaClient, repo_path
from localgpt_platform.result import PlatformError, ok_result

from .schemas import (
    assert_relative_to_root,
    compact_artifact,
    expect_keyed_object_list,
    job_output_dir,
    page_params,
    path_segment,
    require_repo,
    require_response_field,
    required_param,
    safe_name,
    utc_now,
    workspace_root,
)


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
                raise PlatformError("unsafe_artifact_zip", "artifact zip 包含越界路径", {"member": member.filename}) from exc
            member_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, member_path.open("wb") as target:
                target.write(source.read())
            extracted.append(str(member_path))
    return extracted

async def download_job_log_to_path(client: GiteaClient, repo: str, cwd: Path, job_id: str, *, step: str) -> tuple[dict[str, Any], dict[str, Any]]:
    job_dir = job_output_dir(cwd, job_id)
    log_path = job_dir / "job.log"
    assert_relative_to_root(log_path, cwd)
    path = repo_path(repo, f"/actions/jobs/{path_segment(job_id)}/logs")
    log_text, evidence = await client.request_text("GET", path, step=step)
    job_dir.mkdir(parents=True, exist_ok=True)
    log_path.write_text(log_text, encoding="utf-8")
    evidence["download_path"] = str(log_path)
    evidence["bytes"] = log_path.stat().st_size
    return {"job_id": job_id, "cwd": str(cwd), "job_dir": str(job_dir), "log_path": str(log_path), "bytes": log_path.stat().st_size, "content_returned": False}, evidence

async def download_artifact_to_path(client: GiteaClient, repo: str, cwd: Path, job_id: str, artifact_id: str, artifact_name: str, *, step: str, extract_dir_name: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    job_dir = job_output_dir(cwd, job_id)
    artifact_dir = job_dir / "artifact"
    zip_path = artifact_dir / f".{safe_name(artifact_name)}.download.zip"
    assert_relative_to_root(artifact_dir, cwd)
    assert_relative_to_root(zip_path, cwd)
    evidence = await client.download(repo_path(repo, f"/actions/artifacts/{path_segment(artifact_id)}/zip"), zip_path, step=step)

    extract_dir = artifact_dir / safe_name(extract_dir_name) if extract_dir_name else artifact_dir
    assert_relative_to_root(extract_dir, cwd)
    extracted_files = extract_zip(zip_path, extract_dir)
    try:
        zip_path.unlink()
    except OSError as exc:
        raise PlatformError(
            "artifact_zip_cleanup_failed",
            "artifact 已解压但临时 zip 删除失败",
            {"artifact_dir": str(artifact_dir)},
        ) from exc
    evidence["temporary_zip_deleted"] = True

    return {
        "artifact_id": artifact_id,
        "job_id": job_id,
        "artifact_name": safe_name(artifact_name),
        "cwd": str(cwd),
        "job_dir": str(job_dir),
        "artifact_dir": str(artifact_dir),
        "extract_dir": str(extract_dir),
        "extracted": True,
        "extracted_file_count": len(extracted_files),
        "extracted_files": extracted_files[:200],
        "extracted_files_truncated": len(extracted_files) > 200,
        "content_returned": False,
    }, evidence

def write_manifest(artifact_dir: Path, cwd: Path, manifest: dict[str, Any]) -> Path:
    assert_relative_to_root(artifact_dir, cwd)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = artifact_dir / "manifest.json"
    assert_relative_to_root(manifest_path, cwd)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path

async def list_artifacts(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    run_id = params.get("run_id")
    suffix = f"/actions/runs/{path_segment(str(run_id))}/artifacts" if run_id else "/actions/artifacts"
    path = repo_path(repo, suffix)
    data, evidence = await client.request_json("GET", path, params=page_params(params), step="actions.list_artifacts")
    artifacts = expect_keyed_object_list(data, step="actions.list_artifacts", path=path, keys=("artifacts",))
    evidence["result_count"] = len(artifacts)
    return ok_result(operation="actions.list_artifacts", data=data, evidence=evidence, meta={"repo": repo})

async def download_artifact(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    if "target_dir" in params:
        raise PlatformError("forbidden_param", "actions.download_artifact 不允许传 target_dir；请传 cwd，文件固定写入 cwd/jobs/<job_id>/artifact/", {"param": "target_dir"})
    cwd = workspace_root(params)
    job_id = required_param(params, "job_id")
    artifact_id = required_param(params, "artifact_id")
    artifact_name = safe_name(str(params.get("artifact_name") or f"artifact-{artifact_id}"))
    data, evidence = await download_artifact_to_path(client, repo, cwd, job_id, artifact_id, artifact_name, step="actions.download_artifact")
    manifest_path = write_manifest(
        Path(data["artifact_dir"]),
        cwd,
        {
            "operation": "actions.download_artifact",
            "repo": repo,
            "generated_at": utc_now(),
            "job_id": job_id,
            "artifacts": [data],
            "evidence": [evidence],
        },
    )
    data["manifest_path"] = str(manifest_path)
    return ok_result(operation="actions.download_artifact", data=data, evidence=evidence, meta={"repo": repo})

async def artifact_sync_for_run(client: GiteaClient, repo: str | None, params: dict[str, Any]) -> dict[str, Any]:
    require_repo(repo)
    if "target_dir" in params:
        raise PlatformError("forbidden_param", "artifact.sync_for_run 不允许传 target_dir；请传 cwd，文件固定写入 cwd/jobs/run-<run_id>/artifact/", {"param": "target_dir"})
    cwd = workspace_root(params)
    run_id = required_param(params, "run_id")
    job_id = str(params.get("job_id") or f"run-{run_id}")
    pattern = str(params.get("artifact_name_pattern") or "").strip()
    evidence: list[dict[str, Any]] = []
    warnings: list[Any] = []

    artifacts_path = repo_path(repo, f"/actions/runs/{path_segment(run_id)}/artifacts")
    artifacts_data, artifacts_evidence = await client.request_json("GET", artifacts_path, params=page_params(params), step="artifact.list_artifacts")
    artifacts = expect_keyed_object_list(artifacts_data, step="artifact.list_artifacts", path=artifacts_path, keys=("artifacts",))
    artifacts_evidence["result_count"] = len(artifacts)
    evidence.append(artifacts_evidence)

    selected = []
    for artifact in artifacts:
        name = str(require_response_field(artifact, "name", step="artifact.list_artifacts", path=artifacts_path))
        if pattern and not fnmatch.fnmatch(name, pattern):
            continue
        selected.append(artifact)

    downloaded: list[dict[str, Any]] = []
    for artifact in selected:
        artifact_id = str(require_response_field(artifact, "id", step="artifact.list_artifacts", path=artifacts_path))
        artifact_name = safe_name(str(require_response_field(artifact, "name", step="artifact.list_artifacts", path=artifacts_path)))
        data, download_evidence = await download_artifact_to_path(client, repo, cwd, job_id, artifact_id, artifact_name, step="artifact.download_artifact", extract_dir_name=artifact_name)
        data["source"] = compact_artifact(artifact)
        evidence.append(download_evidence)
        downloaded.append(data)

    artifact_root = job_output_dir(cwd, job_id) / "artifact"
    assert_relative_to_root(artifact_root, cwd)
    manifest = {"operation": "artifact.sync_for_run", "repo": repo, "run_id": run_id, "job_id": job_id, "artifact_name_pattern": pattern or None, "generated_at": utc_now(), "artifacts": downloaded, "evidence": evidence}
    manifest_path = write_manifest(artifact_root, cwd, manifest)
    file_count = sum(int(item.get("extracted_file_count", 0)) for item in downloaded)

    if not selected:
        warnings.append({"code": "no_artifacts_selected", "message": "没有 artifact 匹配当前条件。", "artifact_name_pattern": pattern or None})

    return ok_result(
        operation="artifact.sync_for_run",
        data={"run_id": run_id, "job_id": job_id, "manifest_path": str(manifest_path), "artifact_dir": str(artifact_root), "artifact_dirs": [item["extract_dir"] for item in downloaded if item.get("extract_dir")], "file_count": file_count, "artifacts": downloaded, "content_returned": False},
        evidence=evidence,
        meta={"repo": repo, "cwd": str(cwd), "run_id": run_id},
        warnings=warnings,
        next_suggested_operations=[],
    )
