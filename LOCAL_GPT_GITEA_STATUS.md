# LocalGPT Gitea MCP 实现状态

此文档记录当前实现状态和后续计划。稳定设计契约见 [LOCAL_GPT_GITEA.md](D:/repos/CodexPlusPlus/LOCAL_GPT_GITEA.md)。

## 当前状态

顶层 MCP 工具：

```text
gitea_status
gitea_describe_operations
gitea_execute
```

当前 operation 通过 `gitea_execute` 调用。

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

- `actions.list_run_jobs` 当前兼容 `jobs` 和 `workflow_jobs` 两种已确认响应 shape。
- 列表 operation 应在 evidence 中记录 `result_count`。

### Job Log 下载

```text
actions.download_job_log
```

当前行为：

- 下载单个 job log。
- 写入 `{cwd}/jobs/<job_id>/job.log`。
- 返回 `log_path`、`bytes`、`content_returned=false`。
- 不返回日志正文。

### Artifact 下载

```text
actions.download_artifact
```

当前目标行为：

- 下载 artifact。
- 直接解压到 `{cwd}/jobs/<job_id>/artifact/`。
- 成功解压后不保留 zip。
- 写 manifest。
- 返回解压目录、文件数量和 evidence。

注意：

- schema 不暴露 `extract` 参数。
- 成功解压后必须删除临时 zip。
- 返回值不包含 `zip_path`、`transport_zip_path`、`retained_zip_paths`。

### CI Run 摘要

```text
ci.get_run_summary
```

当前行为：

- 查询单个 run。
- 查询 run jobs。
- 返回 run + jobs 的紧凑摘要。
- 返回 `job_count`、`failed_job_count`、`queued_in_progress_job_count`。
- 如果存在失败 job，返回 `next_suggested_operations=["ci.prepare_failure_context"]`。

不做：

- 不下载日志。
- 不列 artifacts。
- 不写本地文件。
- 不修改远端。

### CI 失败上下文组合

```text
ci.prepare_failure_context
```

当前行为：

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

### Artifact 批量同步

```text
artifact.sync_for_run
```

当前行为：

- 列出 run artifacts。
- 按 `artifact_name_pattern` 筛选。
- 下载并解压选中 artifacts。
- 写 manifest。

默认目录：

```text
{cwd}/jobs/run-<run_id>/artifact/
```

如果传入 `job_id`：

```text
{cwd}/jobs/<job_id>/artifact/
```

### PR 前置检查

```text
pr.preflight
```

当前行为：

- 读取 PR metadata。
- 读取 base/head/head_sha。
- 读取 changed files summary。
- 查询 head_sha 相关 CI runs。

不做：

- 不 checkout。
- 不 fetch。
- 不 merge。
- 不评论。
- 不改 PR。

## 待实现 Operation

### 1. `ci.find_run_candidates`

目标：

- 只查 run，不下载日志。
- 根据 branch、head_sha、status、workflow、event 查询候选 runs。
- 返回紧凑且排序后的候选列表。
- 返回 `next_suggested_operations`。

不实现条件：

- 如果只是 `actions.list_runs` 的薄 wrapper，不实现。
- 如果没有候选排序、紧凑摘要或下一步建议价值，不实现。

### 2. `runner.diagnose_queue`

目标：

- 查询 queued/in_progress runs。
- 查询 repo runners。
- 返回 runner 在线、禁用、busy、label mismatch 的事实摘要。

不实现条件：

- 如果无法从 Gitea 官方 API 获取 runner 状态，不实现。
- 如果只是 `actions.list_runners` 的薄 wrapper，不实现。

### 3. `workflow.rerun_job`

目标：

- 显式重跑单个 job。
- 远端写 operation。

要求：

- `writes_remote=true`
- `risk_level=high`
- 参数包含 job/run 相关 `expected_*`，避免陈旧上下文。

不实现条件：

- 如果目标 Gitea 官方 API 不支持，不实现。
- 不通过内部 API 实现。

### 4. `workflow.rerun_run`

目标：

- 显式重跑整个 workflow run。
- 远端写 operation。

不实现条件：

- 如果目标 Gitea 官方 API 不支持，不实现。
- 不藏进 `ci.prepare_failure_context`。

### 5. `workflow.dispatch_and_track`

目标：

- 触发 workflow dispatch。
- 根据 workflow_id、ref、created_after、actor 查候选 runs。
- 返回 candidate runs，不硬说一定匹配。

参数建议：

- `workflow_id`
- `ref`
- `inputs`
- `created_after`
- `candidate_match_strategy`

不实现条件：

- 如果 dispatch API 不稳定或不属于官方 API，不实现。
- 如果无法给出候选匹配证据，不实现。

### 6. `pr.publish`

目标：

- 创建或更新 PR。
- 返回 PR number、URL、created_or_updated、evidence。

参数建议：

- `mode=create|update|upsert`
- `head`
- `base`
- `title`
- `body`
- `expected_head_sha`
- `existing_pr_number` 或 `match_by=head/base`

不实现条件：

- 如果需要本地 commit/push，交给 Codex git，不在 MCP 内实现。
- 开发阶段不做宽泛 `upsert`，先做 `create`，再做 `update`。

### 7. `pr.comment`

目标：

- 给 PR 追加评论。
- 显式远端写 operation。

要求：

- 显式 `pr_number`。
- 显式 `body`。
- 限制 body 大小。
- evidence 不记录完整超长 body，只记录长度、hash 或短 preview。

不实现条件：

- 不让 CI 诊断组合 operation 自动评论。

### 8. `pr.merge`

目标：

- 合并 PR。
- 显式远端写 operation。

强制参数建议：

- `pr_number`
- `expected_head_sha`
- `base_branch`
- `merge_method`
- `confirm=true`
- `require_ci_success=true`

不实现条件：

- 如果没有 `expected_head_sha`，不实现或不允许执行。
- 不隐藏在 `pr.publish` 或 `pr.preflight` 中。

### 9. cache 相关能力

候选：

```text
cache.diagnose
cache.list
cache.plan_delete
cache.delete
```

优先做 `cache.diagnose`，用于分析日志和 runner cache 配置相关失败模式。

不实现条件：

- 如果 Gitea 官方 API 不支持 Actions cache 管理，不实现 `cache.list/delete`。
- 不使用内部 API。
- 如果本地 shell 分析日志即可，不做冗余 MCP operation。

### 不实现为 MCP：`artifact.index_local`

原因：

- 它不是 Gitea 远端平台能力。
- Codex 已经能用 shell 查看 artifact 文件树。
- 放进 MCP 会模糊“远端平台事实”和“本地文件分析”的边界。

如后续确实需要便利能力，可以放到 skill 的本地脚本，不作为 MCP operation。

## 后续优先级

建议顺序：

```text
1. ci.find_run_candidates
2. runner.diagnose_queue
3. workflow.rerun_job
4. workflow.rerun_run
5. workflow.dispatch_and_track
6. pr.publish
7. pr.comment
8. pr.merge
9. cache.diagnose / cache.list
10. cache.plan_delete / cache.delete
```

原则：

- 先补只读诊断闭环。
- 再补受控远端写操作。
- 不补 Codex 本地已有的代码编辑、shell、git、测试能力。
