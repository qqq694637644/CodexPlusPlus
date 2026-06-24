# LocalGPT Gitea MCP 实现状态

此文档记录当前实现状态。稳定设计契约见 [LOCAL_GPT_GITEA.md](D:/repos/CodexPlusPlus/LOCAL_GPT_GITEA.md)。

## 当前状态

顶层 MCP 工具保持 3 个：

```text
gitea_status
gitea_describe_operations
gitea_execute
```

所有平台能力通过 `gitea_execute(operation, repo, params)` 调用。

当前 registry 已启用：

```text
server.version
auth.whoami
repo.get

actions.list_workflows
actions.get_workflow
actions.list_runs
actions.get_run
actions.list_run_jobs
actions.get_job
actions.download_job_log
actions.list_artifacts
actions.download_artifact
actions.list_runners

ci.find_run_candidates
ci.get_run_summary
ci.prepare_failure_context

artifact.sync_for_run

runner.diagnose_queue

workflow.rerun_job
workflow.rerun_run
workflow.dispatch_and_track

pr.preflight
pr.publish
pr.comment
pr.merge

cache.diagnose
```

## Registry / schema 状态

- 每个 operation 都在 `OPERATION_SPECS` 声明完整 metadata。
- `name` 由 registry key 提供；`gitea_describe_operations` 输出时补出。
- registry 与 handler 双向一致，import-time 校验。
- 未声明 params 返回 `unknown_param`，优先于环境变量检查。
- response shape 不匹配返回 `unexpected_response_shape`。
- 远端写 operation 均为 `writes_remote=true`、`risk_level=high`。
- 远端写 operation 必须显式传 `confirm=true`。

## 代码结构

`localgpt_platform.operations` 已拆成 package，按职责分层：

```text
localgpt_platform/operations/
  __init__.py
  registry.py
  schemas.py
  actions.py
  ci.py
  workflow.py
  pr.py
  artifact.py
  runner.py
  cache.py
```

- `registry.py` 维护 operation metadata、handler registry、describe/execute 入口和 registry 校验。
- `schemas.py` 维护 strict parser、compact serializer、参数校验和远端写 gate。
- 业务模块只维护对应 category 的 handler。
- smoke fake client 使用 route table + call recorder，精确断言 method/path/query/body。

## 已实现 Operation

### 状态与仓库

```text
server.version
auth.whoami
repo.get
```

`gitea_status` 行为：

- 无 `GITEA_TOKEN`：`ok=true`，`authenticated=false`，并返回 warning。
- 有 `GITEA_TOKEN` 但 `/user` 失败：`ok=false`。

### Actions / CI 原子查询

```text
actions.list_workflows
actions.get_workflow
actions.list_runs
actions.get_run
actions.list_run_jobs
actions.get_job
actions.list_artifacts
actions.list_runners
```

备注：

- `actions.list_run_jobs` strict parser 只接受官方 `jobs` 响应字段；其他字段返回 `unexpected_response_shape`。
- 列表 operation 在 evidence 中记录 `result_count`。

### CI 候选 run 查询

```text
ci.find_run_candidates
```

行为：

- 根据 `branch`、`head_sha`、`status`、`workflow_id`、`event`、`actor` 查询候选 runs。
- 返回排序后的 compact run 列表。
- 不下载日志。
- 不写本地文件。
- 有候选时建议 `ci.get_run_summary`。

### CI Run 摘要

```text
ci.get_run_summary
```

行为：

- 查询单个 run。
- 查询该 run 的 jobs。
- 返回 run compact summary。
- 返回 jobs compact summary。
- 返回 `failed_like_job_count`，包括 `failure`、`cancelled`、`timed_out`、`startup_failure`、`action_required`。
- 返回 `queued_in_progress_job_count`。
- 返回 `status_counts` 和 `conclusion_counts`。
- 不下载日志。
- 不写本地文件。
- 存在 failed-like job 时建议 `ci.prepare_failure_context`。

### Job Log 下载

```text
actions.download_job_log
```

行为：

- 下载单个 job log。
- 写入 `{cwd}/jobs/<job_id>/job.log`。
- 返回 `log_path`、`bytes`、`content_returned=false`。
- 不返回日志正文。

### CI 失败上下文组合

```text
ci.prepare_failure_context
```

行为：

- 定位 run。
- 查询 jobs。
- 下载失败 job logs。
- 可选列出 run artifacts。
- 返回 run 摘要、失败 job 摘要、log 路径、artifact 候选和 evidence。

不做：

- 不判断根因。
- 不 rerun。
- 不评论 PR。
- 不修改远端。
- 不返回完整日志正文。

### Artifact 下载与同步

```text
actions.download_artifact
artifact.sync_for_run
```

行为：

- 下载 artifact 临时 zip。
- 解压到 `{cwd}/jobs/<job_id>/artifact/` 或 `{cwd}/jobs/run-<run_id>/artifact/`。
- 解压成功后删除临时 zip。
- 写 `manifest.json`。
- 返回解压目录、文件数量和 evidence。
- 返回值不包含 `zip_path`、`transport_zip_path`、`retained_zip_paths`。

### Runner 队列诊断

```text
runner.diagnose_queue
```

行为：

- 查询 queued runs。
- 查询 in_progress runs。
- 查询 repo runners。
- 返回 runner 数量、online/offline、busy、disabled、labels 事实摘要。
- 不修改 runner。

### Workflow 远端写操作

```text
workflow.rerun_job
workflow.rerun_run
workflow.dispatch_and_track
```

行为：

- `workflow.rerun_job`：读取 job，校验 job 所属 `run_id`、`expected_status`、`expected_conclusion`，再调用 run-scoped job rerun endpoint。
- `workflow.rerun_run`：读取 run，校验 `expected_head_sha`、可选 status/conclusion，再重跑 run。
- `workflow.dispatch_and_track`：触发 workflow dispatch；若响应含 `workflow_run_id` 则直接返回确定匹配；否则通过 repo-scoped `/actions/runs` 查询候选 runs 并本地筛 workflow/ref/created_after/actor；`inputs` 必须是 `object[string,string]`，非 string value 会在 MCP schema 层失败；候选 run 查询会把 `refs/heads/<branch>` 规范化为 `branch=<branch>`，tag/full ref 不传 branch，避免 Gitea branch query 被二次加前缀；本地筛选兼容 Gitea run `path=workflow.yml@ref`、`started_at` 和 `trigger_actor`；dispatch 成功但候选查询失败时返回 `ok=true` 加 warning，不把已触发误报为失败。

共同要求：

- `confirm=true`。
- `confirm` 必须是 JSON boolean `true`，不接受字符串、数字或其他 truthy 值。
- 远端写 evidence 不记录 secret、token 或完整大 body。
- 不自动重试。
- 不隐藏在读组合 operation 中。

### PR 查询与远端写操作

```text
pr.preflight
pr.publish
pr.comment
pr.merge
```

行为：

- `pr.preflight`：读取 PR metadata、base/head/head_sha、changed files、head_sha CI runs。
- `pr.publish`：创建或更新 PR；开发阶段只支持 `mode=create|update`，不做宽泛 upsert。
- `pr.comment`：给 PR 对应 issue 追加评论；返回 body 长度和 hash，不返回完整正文。
- `pr.merge`：合并 PR；强制 `expected_head_sha`、`base_branch`、`merge_method`、`confirm=true`，默认 `require_ci_success=true`，且要求 head_sha 相关 CI 全部完成并为 success；POST merge 时把 `expected_head_sha` 作为官方 `head_commit_id` 发送给 Gitea，避免 GET 校验后 head 变化的竞态。

不做：

- 不执行本地 git。
- 不 checkout。
- 不 fetch。
- 不把 merge 隐藏在 publish 或 preflight 中。

### Cache 诊断边界

```text
cache.diagnose
```

行为：

- 查询近期 runs，返回 cache 相关诊断边界和候选 runs。
- 明确返回 `official_cache_management_api=false`。
- 不伪造 Gitea 官方 cache list/delete API。

## 明确不实现为 MCP

### `cache.list` / `cache.plan_delete` / `cache.delete`

当前未实现为 operation。

原因：

- 当前设计只使用 Gitea 官方 `/api/v1` REST API。
- 目前未确认 Gitea 官方 REST API 提供与 GitHub Actions cache 等价的 repository cache list/delete 管理接口。
- 不使用 Gitea 内部 `/api/actions_pipeline` 或非官方缓存协议。

后续只有在目标 Gitea 官方 API 明确支持时再实现。

### `artifact.index_local`

不实现为 Gitea MCP operation。

原因：

- 它不是 Gitea 远端平台能力。
- Codex 已经能用 shell 查看 artifact 文件树和读取本地报告。
- 如需便利能力，应放到 skill 本地脚本，不作为远端平台 MCP。

## 后续计划

当前 `LOCAL_GPT_GITEA.md` 中要求的 operation 计划已处理：

- 可通过官方 REST API 和当前设计安全实现的 operation 已实现。
- 不应进入 MCP 或官方 API 不明确的能力已在本文件中明确不实现。

后续仅保留维护项：

```text
1. 接入真实 Gitea 实例做端到端验证。
2. 根据真实 Gitea 响应调整 strict parser。
3. 如 Gitea 官方 API 新增 cache 管理能力，再评估 cache.list / cache.plan_delete / cache.delete。
4. 将日志和 artifact 下载改为 streaming，避免大响应一次性进内存。
```
