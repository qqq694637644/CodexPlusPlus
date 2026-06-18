**核心约束**
- 顶层 MCP 工具保持 3 个：`gitea_status`、`gitea_describe_operations`、`gitea_execute`。
- 不新增大量 `gitea_xxx` 顶层工具。
- operation 分三类：原子读操作、组合读操作、显式写操作。
- job log 和 artifact 不返回正文，固定落盘。
- 本项目路径约束优先：使用 `{cwd}/jobs/<job_id>/...`，不要混回 `.gpt-artifacts/runs/...`，除非后续明确迁移。

**顶层工具设计**
`gitea_status`
- 检查 Gitea API 可达性、版本、认证状态。
- 不做 repo 级查询。
- 返回最小健康信息。

`gitea_describe_operations`
- 支持渐进披露。
- 参数建议：
  - `category`：可选，`ci`、`actions`、`artifact`、`pr`、`workflow`、`runner`、`cache`
  - `operation`：可选，传入时返回单个 operation 完整 schema
  - `detail`：`brief` 或 `full`
- `brief` 只返回名称、描述、读写属性。
- `full` 返回完整参数 schema、返回结构、示例、风险等级。

`gitea_execute`
- 唯一执行入口。
- 输入：`operation`、`repo`、`params`。
- 所有 operation 必须先在 registry 中声明 metadata。
- 不允许执行 registry 外 operation。

**Operation Metadata 必须字段**
每个 operation 都要声明：

```text
name
category
description
repo_required
read_only_remote
writes_local_files
writes_remote
requires_cwd
required_params
optional_params
returns
example
risk_level
```

关键布尔字段：

```text
read_only_remote
writes_local_files
writes_remote
```

审查标准：任何写远端的 operation 必须 `writes_remote=true`，名字也必须显式体现副作用，例如 `publish`、`dispatch`、`rerun`、`delete`、`merge`。

**统一返回结构**
所有 operation 返回同一形态：

```text
ok
operation
data
meta
evidence
warnings
next_suggested_operations
error
```

成功时：
- `ok=true`
- `data` 放紧凑业务结果
- `evidence` 放真实 API 调用证据
- `warnings` 放非致命问题
- `next_suggested_operations` 给 GPT-5.5 下一步候选，不替它决策

失败时：
- `ok=false`
- `error.code`
- `error.message`
- `error.details`
- 不抛大段 traceback 给模型

**Evidence 结构**
组合 operation 内部每次 API 调用都必须有 evidence entry：

```text
step
method
path
status_code
params_summary
download_path
bytes
```

注意：
- 不记录 token。
- 不记录 secret。
- 不记录完整 response body。
- 对分页调用要记录 page/limit 和结果数量。

**本地文件落盘规范**
当前项目统一使用：

```text
{cwd}/jobs/<job_id>/job.log
{cwd}/jobs/<job_id>/artifact/
{cwd}/jobs/<job_id>/artifact/<artifact_name>.zip
{cwd}/jobs/<job_id>/artifact/manifest.json
```

规则：
- `cwd` 必须由调用方显式传入。
- `cwd` 必须是已存在目录。
- 所有写入路径必须 `relative_to(cwd)`。
- 禁止 `target_dir`。
- 禁止任意绝对输出路径。
- zip 解压必须防 zip-slip。

**第一批原子 Operation**
保留这些原子能力：

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
```

注意语义：
- `actions.download_job_log`，不是 `get_job_log`。
- 因为它有本地写文件副作用。
- metadata 应该是：
  - `read_only_remote=true`
  - `writes_local_files=true`
  - `writes_remote=false`

**第一批组合 Operation**
优先做这三个：

1. `ci.prepare_failure_context`
2. `artifact.sync_for_run`
3. `pr.preflight`

`ci.prepare_failure_context`
- 输入：
  - `repo`
  - `cwd`
  - `run_id`，或 `branch/head_sha/status`
- 内部：
  - 定位 run
  - 获取 run summary
  - list jobs
  - 找 failed/cancelled/timed_out jobs
  - 下载失败 job log 到 `{cwd}/jobs/<job_id>/job.log`
  - 可选列出 artifacts
- 返回：
  - run summary
  - failed jobs
  - log paths
  - artifact candidates
  - evidence[]
  - next_suggested_operations
- 不做：
  - 不 rerun
  - 不评论 PR
  - 不判断根因
  - 不返回完整日志

`artifact.sync_for_run`
- 输入：
  - `repo`
  - `cwd`
  - `run_id`
  - 可选 artifact name pattern
- 内部：
  - list artifacts
  - 下载选中的 artifacts
  - 解压到 job 或 run 关联目录
  - 写 manifest
- 返回：
  - manifest path
  - artifact dirs
  - zip paths
  - file count
  - evidence[]
- 注意：如果 artifact 无法映射到 job，可放到 `{cwd}/jobs/run-<run_id>/artifact/`，但必须在 schema 中明确。

`pr.preflight`
- 输入：
  - `repo`
  - `pr_number`
- 内部：
  - 获取 PR metadata
  - 获取 base/head/head_sha
  - 获取 changed files summary
  - 查询 head_sha 相关 CI runs
- 返回：
  - PR state
  - base/head/head_sha
  - changed files summary
  - ci summary
  - evidence[]
- 不做：
  - 不 checkout
  - 不 fetch
  - 不 merge
  - 不评论

**第二批写 Operation**
后续再做：

```text
pr.publish
workflow.dispatch_and_track
workflow.rerun_run
workflow.rerun_job
cache.plan_delete
cache.delete
```

要求：
- 写操作必须 `writes_remote=true`。
- operation 名字必须显式。
- 不允许藏在读组合里。
- skill 里必须要求 GPT-5.5 在执行前确认意图或说明副作用。
- Codex MCP 配置层面可把写 operation 所在 tool 设为 `prompt/approve`，但由于目前是单 execute 入口，需要在 operation metadata 和 skill 层明确风险。

**Skill 结构**
不要把所有内容放进一个 `SKILL.md`。建议：

```text
localgpt-platform/
  SKILL.md
  references/
    ci-failure.md
    artifact-analysis.md
    pr-workflow.md
    workflow-rerun.md
    runner-diagnose.md
    cache-ops.md
    write-ops.md
  examples/
    ci-prepare-failure-context.json
    artifact-sync-for-run.json
    pr-preflight.json
    pr-publish.json
```

`SKILL.md` 只放：
- 何时使用 MCP
- 何时不用 MCP
- 最常用 CI 修复流程
- 固定路径规范
- 大日志处理原则
- 指向 references

`references/ci-failure.md`
- 写完整 CI runbook：
  - `ci.find_runs`
  - `ci.prepare_failure_context`
  - 本地 grep/tail 日志
  - 修复代码
  - 本地验证
  - 再查 CI

`references/write-ops.md`
- 专门写副作用 operation 规则。
- 所有 `writes_remote=true` 的操作都集中说明。

**大日志处理框架**
第一阶段不需要做 `log.search` MCP operation，让 GPT-5.5 用 shell 读本地文件片段即可。

skill 中明确：
- 先 `download_job_log`
- 再用 shell 搜索：
  - error
  - failed
  - panic
  - traceback
  - exception
- 只读取上下文片段或 tail
- 不要整份日志塞进上下文

后续如果需要统一体验，再加：

```text
log.extract_error_blocks
```

但它仍然只读本地文件，不再调用 Gitea。

**审查重点**
我后续审查时会卡这些点：

1. `actions.get_job_log` 必须不存在，只能有 `actions.download_job_log`。
2. job log 不允许返回原始正文。
3. artifact 不允许传 `target_dir`。
4. 所有本地写入必须在 `cwd` 内。
5. 组合 operation 必须返回 `evidence[]`，不能只返回总结。
6. 读组合不能顺手执行写远端操作。
7. 写 operation 必须有 `writes_remote=true`。
8. `describe_operations` 不能一次性返回过大的完整 schema；要支持 `brief/full` 或按 operation inspect。
9. skill 必须是渐进披露，不要把所有 runbook 堆进 `SKILL.md`。
10. 返回结构必须稳定，错误必须结构化。

**推荐实施顺序**
1. 先整理 operation registry metadata。
2. 改造 `describe_operations` 支持 `category/detail/operation`。
3. 实现 `ci.prepare_failure_context`。
4. 实现 `artifact.sync_for_run`。
5. 实现 `pr.preflight`。
6. 拆 skill references。
7. 再考虑写操作：`pr.publish`、`workflow.rerun`。

最终目标就是：MCP 负责收集证据和落盘大文件，skill 负责流程，GPT-5.5 负责判断和修复。