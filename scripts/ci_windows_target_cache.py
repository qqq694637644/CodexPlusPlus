from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CARGO_LOCK = REPO_ROOT / "build" / "CodexPlusPlus-localgpt" / "Cargo.lock"
TARGET_PATH = "build/CodexPlusPlus-localgpt/target"
CACHE_VERSION = "v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_github_output(outputs: dict[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8", newline="\n") as file:
        for key, value in outputs.items():
            file.write(f"{key}={value}\n")


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def main() -> int:
    if not CARGO_LOCK.is_file():
        raise RuntimeError(f"Cargo.lock not found: {CARGO_LOCK}")

    runner_os = required_env("RUNNER_OS")
    github_sha = required_env("GITHUB_SHA")
    lock_hash = sha256_file(CARGO_LOCK)[:16]
    restore_key = f"{runner_os}-cargo-target-release-{CACHE_VERSION}-{lock_hash}-"
    primary_key = f"{restore_key}{github_sha}"

    outputs = {
        "target_path": TARGET_PATH,
        "primary_key": primary_key,
        "restore_key": restore_key,
    }
    append_github_output(outputs)
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ci_windows_target_cache.py failed: {error}", file=sys.stderr)
        raise SystemExit(1)
