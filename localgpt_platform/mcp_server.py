from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .operations import check_status, describe_operations, execute_operation

INSTRUCTIONS = """
LocalGPT Gitea MCP 只调用 Gitea 官方 /api/v1 REST API，用于 Codex 查询 CI/CD、PR 前置状态和 artifact。不要用它执行本地 git、测试、构建或 shell。所有工具返回结构化 JSON：ok 为 true 时读取 data/evidence；ok 为 false 时先处理 error，不要编造结果。不要输出 token、secret 或 runner registration token。

优先使用 gitea_describe_operations 查看 operation 白名单和参数 schema，再调用 gitea_execute。第一版只启用只读 CI 诊断能力；重跑 workflow、修改 secret、删除 runner 等写操作尚未启用。job log 和 artifact 必须传 params.cwd，并固定写入 cwd/jobs/<job_id>/ 下；不要把原始日志直接返回给模型。
""".strip()

mcp = FastMCP("localgpt-gitea", instructions=INSTRUCTIONS)


@mcp.tool()
async def gitea_status() -> dict[str, Any]:
    """检查 Gitea MCP 配置和服务器版本。"""
    return await check_status()


@mcp.tool()
def gitea_describe_operations(
    category: str | None = None,
    operation: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    """返回 Gitea operation 白名单；支持 category 过滤、operation inspect 和 brief/full detail。"""
    return describe_operations(category=category, operation=operation, detail=detail)


@mcp.tool()
async def gitea_execute(
    operation: str,
    repo: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行一个白名单内的 Gitea operation。repo 使用 owner/repo，params 按 operation 传入。"""
    return await execute_operation(operation, repo=repo, params=params or {})


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
