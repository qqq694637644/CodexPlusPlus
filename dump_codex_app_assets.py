#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


INVALID_SEGMENT_CHARS = re.compile(r'[^A-Za-z0-9._-]+')


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def safe_segment(value: str) -> str:
    value = INVALID_SEGMENT_CHARS.sub("_", value.strip())
    return value or "_"


def extension_from_metadata(mime_type: str, resource_type: str) -> str:
    mime_type = (mime_type or "").split(";")[0].strip().lower()
    resource_type = (resource_type or "").strip().lower()

    if mime_type:
        guessed = mimetypes.guess_extension(mime_type) or ""
        if guessed == ".jpe":
            guessed = ".jpg"
        if guessed:
            return guessed

    fallback = {
        "document": ".html",
        "stylesheet": ".css",
        "script": ".js",
        "xhr": ".json",
        "fetch": ".json",
        "manifest": ".json",
    }
    return fallback.get(resource_type, "")


def output_path_for_url(
    out_dir: Path,
    url: str,
    resource_type: str,
    mime_type: str,
) -> Path:
    parsed = urlsplit(url)
    scheme = safe_segment(parsed.scheme or "unknown")
    host = safe_segment(parsed.netloc or "_")
    raw_path = unquote(parsed.path or "")

    if not raw_path or raw_path.endswith("/"):
        raw_path = f"{raw_path}index"

    parts = [safe_segment(part) for part in raw_path.split("/") if part]
    if not parts:
        parts = ["index"]

    filename = parts[-1]
    if "." not in Path(filename).name:
        suffix = extension_from_metadata(mime_type, resource_type)
        if suffix:
            filename += suffix
            parts[-1] = filename

    path = out_dir / scheme / host
    for part in parts[:-1]:
        path /= part
    path /= parts[-1]

    if parsed.query:
        stem = path.stem
        suffix = path.suffix
        path = path.with_name(f"{stem}__q_{short_hash(parsed.query)}{suffix}")

    return path


def write_content(path: Path, content: str, base64_encoded: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if base64_encoded:
        path.write_bytes(base64.b64decode(content))
    else:
        path.write_text(content, encoding="utf-8", newline="")


def iter_frame_resources(frame_tree: Dict) -> Iterable[Dict]:
    frame = frame_tree.get("frame", {})
    frame_id = frame.get("id", "")
    frame_url = frame.get("url", "")
    if frame_url:
        yield {
            "frameId": frame_id,
            "url": frame_url,
            "type": "Document",
            "mimeType": "text/html",
        }

    for resource in frame_tree.get("resources", []) or []:
        resource = dict(resource)
        resource["frameId"] = frame_id
        yield resource

    for child in frame_tree.get("childFrames", []) or []:
        yield from iter_frame_resources(child)


def unique_resources(resources: Iterable[Dict]) -> List[Dict]:
    seen: set[Tuple[str, str]] = set()
    output: List[Dict] = []
    for resource in resources:
        key = (str(resource.get("frameId", "")), str(resource.get("url", "")))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        output.append(resource)
    return output


def pick_codex_page(browser) -> object:
    candidates = []
    for context in browser.contexts:
        for page in context.pages:
            candidates.append(page)

    if not candidates:
        raise RuntimeError("CDP 已连接，但没有可用页面")

    for page in candidates:
        if page.url.startswith("app://"):
            return page

    for page in candidates:
        try:
            if "codex" in (page.title() or "").lower():
                return page
        except Exception:
            pass

    return candidates[0]


def dump_assets(cdp_url: str, out_dir: Path) -> Dict:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(cdp_url)
        page = pick_codex_page(browser)
        page.wait_for_load_state("domcontentloaded", timeout=15000)

        cdp = page.context.new_cdp_session(page)
        cdp.send("Page.enable")
        tree = cdp.send("Page.getResourceTree")
        frame_tree = tree["frameTree"]
        resources = list(iter_frame_resources(frame_tree))

        main_frame_id = frame_tree.get("frame", {}).get("id", "")
        performance_urls = page.evaluate(
            """
            () => performance.getEntriesByType('resource')
                .map(entry => entry.name)
                .filter(Boolean)
            """
        )
        for url in performance_urls:
            resources.append(
                {
                    "frameId": main_frame_id,
                    "url": url,
                    "type": "Other",
                    "mimeType": "",
                }
            )

        unique = unique_resources(resources)
        manifest = {
            "cdp_url": cdp_url,
            "page_url": page.url,
            "page_title": page.title(),
            "resource_count": len(unique),
            "resources": [],
        }

        for resource in unique:
            frame_id = str(resource.get("frameId", ""))
            url = str(resource.get("url", ""))
            resource_type = str(resource.get("type", "Other"))
            mime_type = str(resource.get("mimeType", ""))
            item = {
                "frameId": frame_id,
                "url": url,
                "type": resource_type,
                "mimeType": mime_type,
                "saved": False,
            }

            try:
                content_result = cdp.send(
                    "Page.getResourceContent",
                    {"frameId": frame_id, "url": url},
                )
                path = output_path_for_url(out_dir, url, resource_type, mime_type)
                write_content(
                    path,
                    content_result.get("content", ""),
                    bool(content_result.get("base64Encoded")),
                )
                item["saved"] = True
                item["path"] = str(path.relative_to(out_dir))
                item["base64Encoded"] = bool(content_result.get("base64Encoded"))
            except PlaywrightError as error:
                item["error"] = str(error)
            except Exception as error:
                item["error"] = f"{type(error).__name__}: {error}"

            manifest["resources"].append(item)

        runtime_html = out_dir / "runtime-page-content.html"
        runtime_html.write_text(page.content(), encoding="utf-8", newline="")
        manifest["runtime_html"] = str(runtime_html.relative_to(out_dir))

        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="",
        )

        return {
            "manifest_path": manifest_path,
            "saved_count": sum(1 for item in manifest["resources"] if item["saved"]),
            "resource_count": manifest["resource_count"],
            "runtime_html": runtime_html,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="通过 Playwright + CDP 导出当前 Codex App 已加载资源"
    )
    parser.add_argument(
        "--cdp",
        default="http://127.0.0.1:9222",
        help="CDP 地址，默认 http://127.0.0.1:9222",
    )
    parser.add_argument(
        "--out",
        default="_dump/codex-app-assets",
        help="导出目录，默认 _dump/codex-app-assets",
    )
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = dump_assets(args.cdp, out_dir)
    except Exception as error:
        print(f"[失败] {type(error).__name__}: {error}", file=sys.stderr)
        return 1

    print(f"[完成] 已保存 {result['saved_count']} / {result['resource_count']} 个资源")
    print(f"[清单] {result['manifest_path']}")
    print(f"[页面HTML] {result['runtime_html']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
