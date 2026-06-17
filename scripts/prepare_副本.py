from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BASELINE_PATH = SCRIPT_DIR / "prepare_副本.baseline.json"
UPSTREAM_ROOT = REPO_ROOT / "upstream" / "CodexPlusPlus"
BUILD_ROOT = REPO_ROOT / "build" / "CodexPlusPlus-localgpt"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_baseline() -> list[dict[str, str]]:
    raw = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    files = raw.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError(f"基线文件无效：{BASELINE_PATH}")
    return files


def check_upstream_files(baseline_files: list[dict[str, str]]) -> None:
    changed: list[tuple[str, str, str, Path]] = []
    for item in baseline_files:
        relative_path = item["path"]
        expected_sha = item["sha256"]
        file_path = REPO_ROOT / relative_path
        if not file_path.is_file():
            raise RuntimeError(f"上游文件不存在：{file_path}")
        actual_sha = sha256_file(file_path)
        if actual_sha != expected_sha:
            changed.append((item["key"], expected_sha, actual_sha, file_path))
    if changed:
        print("检测到上游关键文件已变动，已停止生成副本：", file=sys.stderr)
        for key, expected_sha, actual_sha, file_path in changed:
            print(f"- {key}: {file_path}", file=sys.stderr)
            print(f"  baseline: {expected_sha}", file=sys.stderr)
            print(f"  current : {actual_sha}", file=sys.stderr)
        raise SystemExit(1)


def reset_build_copy() -> None:
    if not UPSTREAM_ROOT.is_dir():
        raise RuntimeError(f"上游目录不存在：{UPSTREAM_ROOT}")
    if BUILD_ROOT.exists():
        shutil.rmtree(BUILD_ROOT)
    BUILD_ROOT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(UPSTREAM_ROOT, BUILD_ROOT)


def replace_exact_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        raise RuntimeError(f"目标内容疑似已存在，拒绝重复替换：{path}")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"替换锚点不唯一或不存在：{path}，期望 1 次，实际 {count} 次"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")


def patch_cargo_toml() -> None:
    path = BUILD_ROOT / "crates" / "codex-plus-core" / "Cargo.toml"
    old = 'toml_edit.workspace = true\n'
    new = (
        'toml_edit.workspace = true\n'
        'localgpt = { path = "../../../../localgpt" }\n'
    )
    replace_exact_once(path, old, new)


def patch_routes_rs() -> None:
    path = BUILD_ROOT / "crates" / "codex-plus-core" / "src" / "routes.rs"
    old = (
        '        "/upstream-worktree/create" => ctx.runtime.upstream_worktree_create(payload.clone()).await,\n'
        '        "/delete" => result_value(ctx.data.delete(session_from_payload(&payload)).await),\n'
    )
    new = (
        '        "/upstream-worktree/create" => ctx.runtime.upstream_worktree_create(payload.clone()).await,\n'
        '        "/localgpt/prepare-turn-start" => localgpt::handle_bridge(payload.clone()).await,\n'
        '        "/delete" => result_value(ctx.data.delete(session_from_payload(&payload)).await),\n'
    )
    replace_exact_once(path, old, new)


def patch_assets_rs() -> None:
    path = BUILD_ROOT / "crates" / "codex-plus-core" / "src" / "assets.rs"
    old = (
        '        "window.__CODEX_SESSION_DELETE_HELPER__ = {};\\nwindow.__CODEX_PLUS_SPONSOR_IMAGES__ = {};\\nwindow.__CODEX_PLUS_VERSION__ = {};\\nwindow.__CODEX_PLUS_BUILD__ = {};\\nwindow.__CODEX_PLUS_IMAGE_OVERLAY__ = {};\\n{}",\n'
        '        serde_json::to_string(&helper_url).expect("helper URL should serialize"),\n'
        '        serde_json::to_string(&sponsor_images).expect("sponsor images should serialize"),\n'
        '        serde_json::to_string(crate::version::VERSION).expect("version should serialize"),\n'
        '        serde_json::to_string(DIAGNOSTIC_BUILD_ID).expect("build id should serialize"),\n'
        '        serde_json::to_string(&image_overlay).expect("image overlay config should serialize"),\n'
        '        renderer_script(),\n'
        '    )\n'
    )
    new = (
        '        "window.__CODEX_SESSION_DELETE_HELPER__ = {};\\nwindow.__CODEX_PLUS_SPONSOR_IMAGES__ = {};\\nwindow.__CODEX_PLUS_VERSION__ = {};\\nwindow.__CODEX_PLUS_BUILD__ = {};\\nwindow.__CODEX_PLUS_IMAGE_OVERLAY__ = {};\\n{}\\n{}",\n'
        '        serde_json::to_string(&helper_url).expect("helper URL should serialize"),\n'
        '        serde_json::to_string(&sponsor_images).expect("sponsor images should serialize"),\n'
        '        serde_json::to_string(crate::version::VERSION).expect("version should serialize"),\n'
        '        serde_json::to_string(DIAGNOSTIC_BUILD_ID).expect("build id should serialize"),\n'
        '        serde_json::to_string(&image_overlay).expect("image overlay config should serialize"),\n'
        '        renderer_script(),\n'
        '        localgpt::hook_script(),\n'
        '    )\n'
    )
    replace_exact_once(path, old, new)


def main() -> None:
    baseline_files = load_baseline()
    check_upstream_files(baseline_files)
    reset_build_copy()
    patch_cargo_toml()
    patch_routes_rs()
    patch_assets_rs()
    print(f"副本已生成：{BUILD_ROOT}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        print(f"prepare_副本.py 失败：{error}", file=sys.stderr)
        raise SystemExit(1)
