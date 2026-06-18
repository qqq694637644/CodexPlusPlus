---
name: localgpt-platform
description: 当任务需要查询 Gitea CI/CD、Actions run/job/log、artifact、runner 或 PR 前置状态时使用；不要用于本地 git、测试、构建或 shell 操作。
---

# LocalGPT Platform Skill

## 目标

使用 `localgpt-gitea` MCP 查询真实 Gitea 平台状态，辅助 Codex 修复 CI/CD、artifact 和 PR 前置检查问题。

## 使用边界

- 普通 `git status`、`git fetch`、`git diff`、`git commit`、`git push` 直接在当前工作目录执行。
- 本地测试、构建、脚本运行直接使用 shell。
- 查询 Gitea Actions、run、job、log、artifact、runner 或 PR 前置状态时使用 MCP。
- MCP 顶层工具只有 `gitea_status`、`gitea_describe_operations`、`gitea_execute`。
- 读取 job log 必须传当前 workspace 的 `cwd`，MCP 固定写入 `{cwd}/jobs/<job_id>/job.log`，不返回原始日志正文。
- 下载 artifact 必须传当前 workspace 的 `cwd`；文件固定写入 `{cwd}/jobs/<job_id>/artifact/` 或 `{cwd}/jobs/run-<run_id>/artifact/`。
- 不要传任意下载目录；`target_dir` 是非法参数。
- MCP 返回 `ok=false` 时，先处理 `error`；不要把空结果猜成真实状态。
- 远端写 operation 只在用户明确要求时调用，并必须传 `confirm=true` 和 operation schema 要求的 `expected_*` 参数。

## 首选流程

1. 调用 `gitea_describe_operations` 查看白名单。默认用 `detail=brief`；需要单个 schema 时传 `operation` 和 `detail=full`。
2. CI 失败诊断优先用 `ci.prepare_failure_context`，它只定位 run、列失败 jobs、下载失败 job 日志，不 rerun、不评论 PR。
3. artifact 同步优先用 `artifact.sync_for_run`，它只落盘 zip、解压文件和 manifest，不返回正文。
4. PR 合并前或修复前检查用 `pr.preflight`，它只读取 PR metadata、changed files 和 head_sha 相关 CI，不 checkout、不 merge、不评论。
5. 只按需读取本地日志或 artifact 文件片段；不要把完整大日志塞进上下文。

## References

- CI 失败诊断：`references/ci-failure.md`
- Artifact 同步与分析：`references/artifact-analysis.md`
- PR 前置检查：`references/pr-workflow.md`
- Workflow 写操作：`references/workflow-write-ops.md`
- Runner / cache 诊断：`references/runner-cache.md`

## 常用最小调用

准备失败上下文：

```json
{
  "operation": "ci.prepare_failure_context",
  "repo": "owner/repo",
  "params": {
    "cwd": "D:\\work\\repo",
    "head_sha": "abc123",
    "status": "failure"
  }
}
```

同步 run artifacts：

```json
{
  "operation": "artifact.sync_for_run",
  "repo": "owner/repo",
  "params": {
    "cwd": "D:\\work\\repo",
    "run_id": 123,
    "artifact_name_pattern": "test-*"
  }
}
```

PR preflight：

```json
{
  "operation": "pr.preflight",
  "repo": "owner/repo",
  "params": {
    "pr_number": 42
  }
}
```

## 停止条件

- 缺少 `GITEA_BASE_URL`。
- 需要认证的 operation 缺少 `GITEA_TOKEN`。
- 设置了 `GITEA_TOKEN` 但认证失败。
- Gitea API 返回 401、403、404 或权限不足。
- 返回 `unexpected_response_shape`，说明当前 strict parser 与真实 Gitea API shape 不一致，需要先修 parser 或 provider 适配。
- 远端写 operation 缺少用户明确意图、`confirm=true` 或必要 `expected_*` 参数。
