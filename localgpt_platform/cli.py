from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .operations import check_status, describe_operations, execute_operation, result_to_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LocalGPT Gitea 平台工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    operations_parser = subparsers.add_parser("operations", help="列出可用 operation")
    operations_parser.add_argument("--category")
    operations_parser.add_argument("--operation")
    operations_parser.add_argument("--detail", choices=["brief", "full"])
    subparsers.add_parser("status", help="检查 Gitea 服务器版本")

    execute_parser = subparsers.add_parser("execute", help="执行 operation")
    execute_parser.add_argument("--input-json", help="请求 JSON 文件路径；使用 - 表示 stdin")
    execute_parser.add_argument("--operation")
    execute_parser.add_argument("--repo")
    execute_parser.add_argument("--params-json", default="{}")

    args = parser.parse_args(argv)
    if args.command == "operations":
        print(
            json.dumps(
                describe_operations(category=args.category, operation=args.operation, detail=args.detail),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "status":
        result = asyncio.run(check_status())
        print(result_to_json(result))
        return 0 if result.get("ok") else 1
    if args.command == "execute":
        request = load_request(args)
        result = asyncio.run(
            execute_operation(
                request["operation"],
                repo=request.get("repo"),
                params=request.get("params") or {},
            )
        )
        print(result_to_json(result))
        return 0 if result.get("ok") else 1
    raise AssertionError(args.command)


def load_request(args: argparse.Namespace) -> dict[str, Any]:
    if args.input_json:
        if args.input_json == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(args.input_json).read_text(encoding="utf-8")
        request = json.loads(raw)
    else:
        request = {
            "operation": args.operation,
            "repo": args.repo,
            "params": json.loads(args.params_json),
        }

    if not isinstance(request, dict):
        raise SystemExit("请求 JSON 必须是对象")
    if not request.get("operation"):
        raise SystemExit("缺少 operation")
    if request.get("params") is not None and not isinstance(request["params"], dict):
        raise SystemExit("params 必须是对象")
    return request


if __name__ == "__main__":
    raise SystemExit(main())
