---
name: localgpt-platform
description: "用于当前 Gitea 仓库的远端事实和受控远端写操作：repo、PR、Actions workflow/run/job/log/artifact、runner/cache、workflow dispatch/rerun、PR 发布/评论/合并；不要用于本地代码搜索、修改、测试、构建、git 操作或外部代码搜索。"
---

# LocalGPT 平台 Skill

## 目标

使用 `localgpt-gitea` MCP 作为当前项目的 Gitea 平台网关。

本 skill 只负责 Gitea 远端事实和用户明确授权的有限远端写操作，不负责本地代码修改，不替代本地 git，不通过外部网站搜索当前项目代码。

## 何时使用

当前仓库任务涉及以下内容时使用本 skill：

- Gitea repository metadata；
- PR metadata；
- PR changed files；
- 修复、审查或合并 PR 前的 preflight；
- Actions workflows；
- workflow runs；
- run jobs；
- job logs；
- run artifacts；
- runner 状态；
- CI queue 诊断；
- cache 边界诊断；
- workflow dispatch；
- workflow run rerun；
- workflow job rerun；
- PR publish、comment 或 merge。

## 何时不用

不要把本 skill 用于：

- 本地文件读取；
- 本地代码搜索；
- 本地代码修改；
- 本地测试；
- 本地构建；
- `git status`；
- `git diff`；
- `git add`；
- `git commit`；
- `git push`；
- 依赖文档查询；
- 语言文档查询；
- 通用网页研究；
- 搜索 GitHub、公开镜像或旧 fork 来判断当前项目代码状态。

本地仓库工作使用 shell 和本地 git。公开文档查询走环境允许的普通外部文档路径，但不得替代 Gitea 对当前项目的事实。

## 工作区模型

本环境有两个目录概念：

```text
THREAD_CWD = LocalGPT 线程工作根目录
REPO_ROOT  = Git 仓库根目录
```

MCP operation 如果需要 `cwd`，必须传 `THREAD_CWD`，不是 `REPO_ROOT`。

正确示例：

```json
{
  "cwd": "<THREAD_CWD>"
}
```

不要把 `REPO_ROOT` 传给 `cwd`。

规则：

- job log 必须落到 `THREAD_CWD/jobs/...`；
- artifact 必须落到 `THREAD_CWD/jobs/...`；
- manifest、解压产物和临时分析产物必须留在 `THREAD_CWD`；
- 禁止把这些产物写入 Git 仓库目录；
- 禁止传任意下载目录；
- `target_dir` 是非法参数，除非未来 schema 明确新增。

如果不能确认某个路径是 `THREAD_CWD` 还是 `REPO_ROOT`，先停止并用本地 shell 检查，不要调用会落盘的 MCP operation。

## MCP 顶层工具

MCP 顶层工具只有：

```text
gitea_status
gitea_describe_operations
gitea_execute
```

默认顺序：

1. MCP / Gitea 配置或认证状态未知时，先调用 `gitea_status`。
2. 调用 `gitea_describe_operations(detail=brief)` 查看 operation 白名单。
3. 不熟悉参数或准备执行远端写操作时，调用 `gitea_describe_operations(operation=..., detail=full)` 查看完整 schema。
4. 调用 `gitea_execute` 执行具体 operation。

不要发明 operation。不要传 schema 未声明的参数。

## 操作风险分级

### 只读远端、不落盘

任务需要时通常可以直接使用：

```text
server.version
auth.whoami
repo.get
actions.list_workflows
actions.get_workflow
actions.list_runs
ci.find_run_candidates
actions.get_run
ci.get_run_summary
actions.list_run_jobs
actions.get_job
actions.list_artifacts
actions.list_runners
runner.diagnose_queue
cache.diagnose
pr.preflight
```

这些 operation 不修改 Gitea 远端状态。

### 只读远端、本地落盘

这些 operation 读取 Gitea，并在本地 `THREAD_CWD/jobs/...` 写入诊断文件：

```text
actions.download_job_log
actions.download_artifact
ci.prepare_failure_context
artifact.sync_for_run
```

规则：

- `cwd` 必须是 `<THREAD_CWD>`；
- 禁止传 repo root；
- 禁止写入 Git 仓库；
- 下载后只用 shell 读取相关片段；
- 不要把完整大日志塞进上下文。

### 远端写操作

这些 operation 会改变 Gitea 远端状态：

```text
workflow.rerun_job
workflow.rerun_run
workflow.dispatch_and_track
pr.publish
pr.comment
pr.merge
```

规则：

- `pr.publish` 只在用户要求修改、修复、提交代码或发 PR 时使用，作为默认 PR 交付路径的一部分；
- workflow dispatch/rerun、job rerun、PR comment 必须等用户明确要求测试、触发、重跑或评论；
- `pr.merge` 必须等用户明确要求合并；
- 调用前必须查看 full schema；
- 必须传 JSON boolean `confirm=true`；
- 必须传 schema 要求的 `expected_*` 字段；
- 不要把 dispatch、rerun、comment、merge 隐藏在只读诊断流程里；
- ambiguous failure 后禁止自动重试；
- `pr.merge` 前必须确认 PR 状态、draft 状态、base 分支、head SHA 和 CI 策略。

## 首选流程

### CI 失败诊断

用户要求分析 CI 失败、PR 红灯或失败 job log 时，优先使用：

```json
{
  "operation": "ci.prepare_failure_context",
  "repo": "owner/repo",
  "params": {
    "cwd": "<THREAD_CWD>",
    "run_id": 123
  }
}
```

未知 `run_id` 时，使用候选条件定位：

```json
{
  "operation": "ci.prepare_failure_context",
  "repo": "owner/repo",
  "params": {
    "cwd": "<THREAD_CWD>",
    "head_sha": "abc123",
    "status": "failure",
    "limit": 10
  }
}
```

行为：读取 run metadata、列出 jobs、下载失败 job log 到 `THREAD_CWD/jobs/<job_id>/job.log`，可选列出 artifacts；不 rerun，不评论 PR，不返回完整日志正文。

详细规则见 `references/ci-failure.md`。

### Artifact 同步与分析

用户要求检查 Gitea Actions artifact 内容时，优先使用：

```json
{
  "operation": "artifact.sync_for_run",
  "repo": "owner/repo",
  "params": {
    "cwd": "<THREAD_CWD>",
    "run_id": 123,
    "artifact_name_pattern": "test-*"
  }
}
```

同步后用 shell 检查本地文件：

```text
<THREAD_CWD>/jobs/run-<run_id>/artifact/
<THREAD_CWD>/jobs/run-<run_id>/artifact/<artifact_name>/...
<THREAD_CWD>/jobs/run-<run_id>/artifact/manifest.json
```

详细规则见 `references/artifact-analysis.md`。

### PR 前置检查

修复、审查或合并 PR 前，优先使用：

```json
{
  "operation": "pr.preflight",
  "repo": "owner/repo",
  "params": {
    "pr_number": 42,
    "ci_limit": 10,
    "file_limit": 100
  }
}
```

行为：读取 PR metadata、base/head refs、changed files summary，并查询 PR head SHA 对应 Actions runs；不 checkout，不 fetch，不 merge，不评论。

详细规则见 `references/pr-workflow.md`。

### Workflow 写操作

用户明确要求 trigger / dispatch / rerun 时才使用：

```text
workflow.dispatch_and_track
workflow.rerun_run
workflow.rerun_job
```

规则：查看 full schema，传 `confirm=true` 和必要 `expected_*`，不要在 ambiguous failure 后自动重复写操作。dispatch 可能已经成功但 tracking 失败时，先用只读 run 查询确认真实 Gitea 状态。

详细规则见 `references/workflow-write-ops.md`。

### Runner 和 cache 诊断

CI queued、stuck、runner 相关或 cache 边界相关时使用：

```text
runner.diagnose_queue
cache.diagnose
```

这些 operation 只收集事实，不修改 runner 或 cache。

详细规则见 `references/runner-cache.md`。

## 严格响应处理

MCP 返回 `ok=false` 时：

1. 读取 `error.code`；
2. 读取 `error.details`；
3. 不要把错误结果当成空数据；
4. 不要编造远端状态。

`unexpected_response_shape` 表示 provider / parser 与真实 Gitea API response shape 不匹配。

遇到该错误时：

- 报告 operation；
- 报告失败 step；
- 报告 expected vs actual shape，如果错误详情提供；
- 停止依赖该 operation 的结果，先修 provider / parser。

## 停止条件

遇到以下情况时停止并报告：

- 缺少 `GITEA_BASE_URL`；
- 需要认证的 operation 缺少 `GITEA_TOKEN`；
- 认证失败；
- Gitea 返回 401 / 403 / 404 且任务无法继续；
- operation 不在白名单；
- params 不符合 schema；
- 远端写 operation 缺少用户明确意图；
- 远端写 operation 缺少 `confirm=true`；
- 缺少必要 `expected_*` 参数；
- 本地输出会写入 `REPO_ROOT`；
- 无法确认 `cwd` 是 `THREAD_CWD`；
- MCP 返回 `unexpected_response_shape`。

## 参考文档

- CI 失败诊断：`references/ci-failure.md`
- Artifact 同步与分析：`references/artifact-analysis.md`
- PR 工作流：`references/pr-workflow.md`
- Workflow 写操作：`references/workflow-write-ops.md`
- Runner / cache 诊断：`references/runner-cache.md`
