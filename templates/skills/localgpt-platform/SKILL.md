---
name: localgpt-platform
description: 当任务需要查询 Gitea CI/CD、Actions run/job/log、artifact、runner 或 PR 前置状态时使用；不要用于本地 git、测试、构建或 shell 操作。
---

# LocalGPT Platform Skill

## 目标

使用 `localgpt-gitea` MCP 查询真实 Gitea 平台状态，辅助 Codex 修复 CI/CD 问题。

## 使用边界

- 普通 `git status`、`git fetch`、`git diff`、`git commit`、`git push` 直接在当前工作目录执行。
- 本地测试、构建、脚本运行直接使用 shell。
- 查询 Gitea Actions、run、job、log、artifact、runner 时使用 MCP。
- 读取 job log 时必须传当前 workspace 的 `cwd`，MCP 会写入 `{cwd}/jobs/<job_id>/job.log`，返回路径，不返回原始日志正文。
- 下载 artifact 时必须传当前 workspace 的 `cwd` 和 `job_id`，MCP 会写入 `{cwd}/jobs/<job_id>/artifact/`。
- 不要传任意下载目录；`target_dir` 是非法参数。
- 不要编造 CI、PR、artifact 或 runner 状态。
- MCP 返回 `ok=false` 时，先处理 `error`；缺少 token、权限或必要参数时直接停止并说明。

## 推荐流程

1. 调用 `gitea_describe_operations` 确认可用 operation 和参数 schema。
2. 使用 `actions.list_runs` 查最近 run，必要时带 `status`、`branch`、`head_sha`。
3. 使用 `actions.get_run` 确认目标 run。
4. 使用 `actions.list_run_jobs` 找失败 job。
5. 使用 `actions.download_job_log` 把失败 job 日志保存到 `{cwd}/jobs/<job_id>/job.log`。
6. 如需 artifact，先 `actions.list_artifacts`，再 `actions.download_artifact`。
7. 只按需读取本地日志文件的相关片段，不要把完整大日志塞进上下文。
8. 只根据真实日志和 artifact 修改代码。

## 常用调用

参数约定：

| operation | repo | 必填 params | 可选 params |
| --- | --- | --- | --- |
| `server.version` | 不需要 | 无 | 无 |
| `auth.whoami` | 不需要 | 无 | 无 |
| `repo.get` | 需要 | 无 | 无 |
| `actions.list_workflows` | 需要 | 无 | `page`、`limit` |
| `actions.get_workflow` | 需要 | `workflow_id` | 无 |
| `actions.list_runs` | 需要 | 无 | `event`、`branch`、`status`、`actor`、`head_sha`、`page`、`limit` |
| `actions.get_run` | 需要 | `run_id` | 无 |
| `actions.list_run_jobs` | 需要 | `run_id` | `attempt`、`page`、`limit` |
| `actions.get_job` | 需要 | `job_id` | 无 |
| `actions.download_job_log` | 需要 | `cwd`、`job_id` | 无 |
| `actions.list_artifacts` | 需要 | 无 | `run_id`、`page`、`limit` |
| `actions.download_artifact` | 需要 | `cwd`、`job_id`、`artifact_id` | `artifact_name`、`extract` |
| `actions.list_runners` | 需要 | 无 | `disabled` |

类型约定：

- `run_id`、`job_id`、`artifact_id` 可以传数字或数字字符串。
- `status` 常用值：`pending`、`queued`、`in_progress`、`failure`、`success`、`skipped`。
- `page`、`limit` 使用整数。
- `extract`、`disabled` 使用 boolean。
- `actions.download_artifact` 没有 `target_dir` 参数。
- `cwd` 必须是当前 Codex workspace 目录。
- job 相关文件固定写入 `{cwd}/jobs/<job_id>/`。

查询最近失败 run：

```json
{
  "operation": "actions.list_runs",
  "repo": "owner/repo",
  "params": {
    "status": "failure",
    "limit": 10
  }
}
```

读取 job 日志：

```json
{
  "operation": "actions.download_job_log",
  "repo": "owner/repo",
  "params": {
    "cwd": "D:\\work\\repo",
    "job_id": 123
  }
}
```

返回后读取 `data.log_path` 指向的文件。不要期待 MCP 返回原始日志正文。

下载 artifact：

```json
{
  "operation": "actions.download_artifact",
  "repo": "owner/repo",
  "params": {
    "cwd": "D:\\work\\repo",
    "job_id": 123,
    "artifact_id": 789,
    "artifact_name": "test-results",
    "extract": true
  }
}
```

## 返回值阅读规则

- `ok=true`：读取 `data`，用 `evidence` 里的真实 API 路径、状态码、落盘路径作为证据。
- `ok=false`：读取 `error.code` 和 `error.message`，不要继续猜测结果。
- `data` 尽量接近 Gitea 原始 JSON，字段含义以 Gitea API 为准。

## 停止条件

- 缺少 `GITEA_BASE_URL` 或 `GITEA_TOKEN`。
- Gitea API 返回 401、403、404 或权限不足。
- 用户没有提供 repo，且无法从任务上下文可靠确定 `owner/repo`。
- 需要执行写操作，但当前 MCP 第一版只启用只读诊断能力。
