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
    ensure_submodule_ready()
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


def ensure_submodule_ready() -> None:
    marker = UPSTREAM_ROOT / ".git"
    cargo_toml = UPSTREAM_ROOT / "Cargo.toml"
    if marker.exists() and cargo_toml.is_file():
        return
    raise RuntimeError(
        "upstream/CodexPlusPlus submodule 未初始化。"
        "请先执行：git submodule update --init --recursive upstream/CodexPlusPlus"
    )


def reset_build_copy() -> None:
    if not UPSTREAM_ROOT.is_dir():
        raise RuntimeError(f"上游目录不存在：{UPSTREAM_ROOT}")
    if BUILD_ROOT.exists():
        shutil.rmtree(BUILD_ROOT)
    BUILD_ROOT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(UPSTREAM_ROOT, BUILD_ROOT)
    remove_embedded_git_metadata()


def remove_embedded_git_metadata() -> None:
    git_metadata = BUILD_ROOT / ".git"
    if git_metadata.is_file() or git_metadata.is_symlink():
        git_metadata.unlink()
    elif git_metadata.is_dir():
        shutil.rmtree(git_metadata)


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


def patch_cargo_lock() -> None:
    path = BUILD_ROOT / "Cargo.lock"
    dependency_old = (
        ' "futures-util",\n'
        ' "reqwest 0.12.28",\n'
    )
    dependency_new = (
        ' "futures-util",\n'
        ' "localgpt",\n'
        ' "reqwest 0.12.28",\n'
    )
    replace_exact_once(path, dependency_old, dependency_new)

    package_old = (
        "[[package]]\n"
        "name = \"codex-plus-data\"\n"
    )
    package_new = (
        "[[package]]\n"
        "name = \"localgpt\"\n"
        "version = \"0.1.0\"\n"
        "dependencies = [\n"
        " \"anyhow\",\n"
        " \"serde\",\n"
        " \"serde_json\",\n"
        "]\n"
        "\n"
        "[[package]]\n"
        "name = \"codex-plus-data\"\n"
    )
    replace_exact_once(path, package_old, package_new)


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


def patch_renderer_inject_js() -> None:
    path = BUILD_ROOT / "assets" / "inject" / "renderer-inject.js"
    install_anchor = "  function installCodexServiceTierDispatcherPatch() {\n"
    middleware_code = (
        "  function registerCodexPlusDispatchMiddleware(name, handler) {\n"
        "    if (!name || typeof handler !== \"function\") throw new Error(\"Invalid dispatch middleware\");\n"
        "    const middlewares = Array.isArray(window.__codexPlusDispatchMiddlewares) ? window.__codexPlusDispatchMiddlewares : [];\n"
        "    if (middlewares.some((middleware) => middleware.name === name)) throw new Error(`Dispatch middleware already registered: ${name}`);\n"
        "    middlewares.push({ name, handler });\n"
        "    window.__codexPlusDispatchMiddlewares = middlewares;\n"
        "  }\n"
        "\n"
        "  function runCodexPlusDispatchMiddlewares(message, finalDispatch) {\n"
        "    const middlewares = Array.isArray(window.__codexPlusDispatchMiddlewares) ? window.__codexPlusDispatchMiddlewares : [];\n"
        "    const runAt = (index, currentMessage) => {\n"
        "      if (!currentMessage || typeof currentMessage !== \"object\") throw new Error(\"Dispatch middleware returned invalid message\");\n"
        "      if (index >= middlewares.length) return finalDispatch(currentMessage);\n"
        "      const nextMessage = middlewares[index].handler(currentMessage);\n"
        "      if (nextMessage && typeof nextMessage.then === \"function\") {\n"
        "        return nextMessage.then((resolvedMessage) => runAt(index + 1, resolvedMessage));\n"
        "      }\n"
        "      return runAt(index + 1, nextMessage);\n"
        "    };\n"
        "    return runAt(0, message);\n"
        "  }\n"
        "\n"
        "  window.__codexPlusRegisterDispatchMiddleware = registerCodexPlusDispatchMiddleware;\n"
        "\n"
    )
    replace_exact_once(path, install_anchor, middleware_code + install_anchor)

    old_dispatch = (
        "        dispatcher.__codexServiceTierOriginalDispatchMessage = dispatcher.dispatchMessage.bind(dispatcher);\n"
        "        dispatcher.dispatchMessage = (type, payload) => {\n"
        "          const message = codexServiceTierRequestOverride({ ...(payload || {}), type });\n"
        "          const nextType = message?.type || type;\n"
        "          const { type: _type, ...nextPayload } = message || {};\n"
        "          return dispatcher.__codexServiceTierOriginalDispatchMessage(nextType, nextPayload);\n"
        "        };\n"
    )
    new_dispatch = (
        "        dispatcher.__codexServiceTierOriginalDispatchMessage = dispatcher.dispatchMessage.bind(dispatcher);\n"
        "        dispatcher.dispatchMessage = (type, payload) => {\n"
        "          const message = codexServiceTierRequestOverride({ ...(payload || {}), type });\n"
        "          return runCodexPlusDispatchMiddlewares(message, (finalMessage) => {\n"
        "            const nextType = finalMessage?.type || type;\n"
        "            const { type: _type, ...nextPayload } = finalMessage || {};\n"
        "            return dispatcher.__codexServiceTierOriginalDispatchMessage(nextType, nextPayload);\n"
        "          });\n"
        "        };\n"
    )
    replace_exact_once(path, old_dispatch, new_dispatch)

    old_upstream_worktree_patch = (
        "  function installUpstreamPendingWorktreeDispatcherPatch() {\n"
        "    const patchVersion = \"1\";\n"
        "    if (window.__codexUpstreamPendingWorktreeDispatcherPatch === patchVersion) return;\n"
        "    const patch = async () => {\n"
        "      try {\n"
        "        const module = await loadCodexAppModule(\"setting-storage-\");\n"
        "        const dispatcherClass = typeof module.v === \"function\" && String(module.v).includes(\"dispatchMessage\") ? module.v : null;\n"
        "        const dispatcher = dispatcherClass?.getInstance?.();\n"
        "        if (!dispatcher || typeof dispatcher.dispatchMessage !== \"function\") throw new Error(\"Codex dispatcher unavailable\");\n"
        "        if (!dispatcher.__codexUpstreamWorktreeOriginalDispatchMessage) {\n"
        "          dispatcher.__codexUpstreamWorktreeOriginalDispatchMessage = dispatcher.dispatchMessage.bind(dispatcher);\n"
        "          dispatcher.dispatchMessage = (type, payload) => {\n"
        "            const nextPayload = type === \"pending-worktree-create\"\n"
        "              ? applyUpstreamPendingWorktreeOverride(payload)\n"
        "              : payload;\n"
        "            return dispatcher.__codexUpstreamWorktreeOriginalDispatchMessage(type, nextPayload);\n"
        "          };\n"
        "        }\n"
        "        window.__codexUpstreamPendingWorktreeDispatcherPatch = patchVersion;\n"
        "      } catch (error) {\n"
        "        sendCodexPlusDiagnostic(\"upstream_pending_worktree_patch_failed\", {\n"
        "          errorName: error?.name || \"\",\n"
        "          errorMessage: error?.message || String(error),\n"
        "        });\n"
        "      }\n"
        "    };\n"
        "    void patch();\n"
        "  }\n"
    )
    new_upstream_worktree_patch = (
        "  function installUpstreamPendingWorktreeDispatcherPatch() {\n"
        "    const patchVersion = \"2\";\n"
        "    if (window.__codexUpstreamPendingWorktreeDispatcherPatch === patchVersion) return;\n"
        "    try {\n"
        "      registerCodexPlusDispatchMiddleware(\"upstream-pending-worktree\", (message) => {\n"
        "        if (message?.type !== \"pending-worktree-create\") return message;\n"
        "        const { type: _type, ...payload } = message;\n"
        "        const nextPayload = applyUpstreamPendingWorktreeOverride(payload);\n"
        "        return { ...(nextPayload || {}), type: \"pending-worktree-create\" };\n"
        "      });\n"
        "      window.__codexUpstreamPendingWorktreeDispatcherPatch = patchVersion;\n"
        "    } catch (error) {\n"
        "      sendCodexPlusDiagnostic(\"upstream_pending_worktree_patch_failed\", {\n"
        "        errorName: error?.name || \"\",\n"
        "        errorMessage: error?.message || String(error),\n"
        "      });\n"
        "      throw error;\n"
        "    }\n"
        "  }\n"
    )
    replace_exact_once(path, old_upstream_worktree_patch, new_upstream_worktree_patch)


def patch_model_catalog_rs() -> None:
    # 当前 pinned upstream 的这个测试里重复设置 relay_mode，
    # 会导致 `cargo check --all-targets` 编译失败。
    # 这不是 LocalGPT 功能接线；只是让运行副本在 upstream 修复前保持可编译。
    # 如果后续 upstream 修复该问题，基线 hash 会变化，脚本会 fail fast 提醒更新本替换规则。
    path = BUILD_ROOT / "crates" / "codex-plus-core" / "tests" / "model_catalog.rs"
    old = (
        '                    relay_mode: RelayMode::PureApi,\n'
        '                    model_list: "deepseek-coder\\nqwen3-coder\\nclaude-compatible".to_string(),\n'
        '                    config_contents: "model = \\"qwen3-coder\\"\\n".to_string(),\n'
        '                    relay_mode: codex_plus_core::settings::RelayMode::MixedApi,\n'
    )
    new = (
        '                    relay_mode: RelayMode::MixedApi,\n'
        '                    model_list: "deepseek-coder\\nqwen3-coder\\nclaude-compatible".to_string(),\n'
        '                    config_contents: "model = \\"qwen3-coder\\"\\n".to_string(),\n'
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
    patch_cargo_lock()
    patch_routes_rs()
    patch_renderer_inject_js()
    patch_model_catalog_rs()
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
