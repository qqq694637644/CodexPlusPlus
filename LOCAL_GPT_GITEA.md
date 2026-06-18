# LocalGPT Gitea MCP 设计说明

## 定位

这个 MCP 是给 Codex 本地 workspace 使用的 Gitea 平台能力补充。

Codex 已经具备本地能力：

- 阅读、搜索、修改代码。
- 运行 shell、测试、构建、lint。
- 使用本地 `git` 做 status、diff、branch、commit、push。
- 用现有编辑工具做 patch 和文件写入。

所以 Gitea MCP 不重复这些能力。它只负责 Codex 本地拿不到或不应该靠猜的远端平台信息：

- Gitea API 可达性和认证状态。
- 仓库、PR、Actions workflow/run/job/runner 元数据。
- CI job log 下载到本地文件。
- Actions artifact 同步到本地文件。
- 组合查询，把修 CI 所需的远端证据一次准备好。

一句话：

> Codex 负责读代码、改代码、跑测试、提交；Gitea MCP 负责查远端事实、下载日志和 artifact。

## 顶层 MCP 工具

当前保持三个顶层工具：

```text
gitea_status
gitea_describe_operations
gitea_execute
```

不要把每个 Gitea endpoint 拆成顶层 MCP tool。operation 通过 `gitea_execute` 扩展。

## 已实现功能

### 状态与描述

```text
server.version
auth.whoami
repo.get
```

用途：

- 检查 Gitea 版本。
- 检查当前 token 对应用户。
- 查询仓库元数据。

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

用途：

- 查 workflow。
- 查 run。
- 查 job。
- 查 artifact 列表。
- 查 repo 级 runner。

这些 operation 只读远端，不写本地文件。

### Job Log 下载

```text
actions.download_job_log
```

用途：

- 从 Gitea 下载单个 job log。
- 写入本地 workspace。
- MCP 只返回路径和大小，不返回日志正文。

落盘路径：

```text
{cwd}/jobs/<job_id>/job.log
```

Codex 后续直接用 shell 搜日志，例如：

```powershell
Select-String -Path .\jobs\<job_id>\job.log -Pattern "error|failed|panic|traceback|exception" -Context 3,3
Get-Content .\jobs\<job_id>\job.log -Tail 200
```

不需要做 `log.search` MCP operation。Codex 本地 shell 已经能完成，而且更灵活。

### Artifact 下载

```text
actions.download_artifact
```

用途：

- 下载单个 artifact。
- 解压到当前 workspace 的 job 目录。
- 写 manifest。
- MCP 返回路径、文件数量和 evidence，不返回 artifact 内容。

落盘路径：

```text
{cwd}/jobs/<job_id>/artifact/
{cwd}/jobs/<job_id>/artifact/<artifact_name>.zip
{cwd}/jobs/<job_id>/artifact/manifest.json
```

Codex 后续用 shell 查看文件树、搜索、读取相关报告即可。

### CI 失败上下文组合

```text
ci.prepare_failure_context
```

用途：

- 定位一个失败 run。
- 查询 run jobs。
- 找失败 job。
- 下载失败 job log 到本地。
- 可选列出该 run 的 artifacts。
- 返回 run 摘要、失败 job 摘要、log 路径、artifact 候选和 evidence。

它不做：

- 不判断根因。
- 不 rerun workflow。
- 不评论 PR。
- 不修改远端。
- 不返回完整日志正文。

这是当前最重要的组合 operation。

### Artifact 批量同步

```text
artifact.sync_for_run
```

用途：

- 列出某个 run 的 artifacts。
- 按名称模式筛选。
- 下载并解压选中 artifacts。
- 写本地 manifest。

默认落盘路径：

```text
{cwd}/jobs/run-<run_id>/artifact/
```

如果调用方提供 `job_id`，则落到：

```text
{cwd}/jobs/<job_id>/artifact/
```

### PR 前置检查

```text
pr.preflight
```

用途：

- 查询 PR metadata。
- 查询 base/head/head_sha。
- 查询 changed files 摘要。
- 查询 head_sha 对应 CI runs。

它不做：

- 不 checkout。
- 不 fetch。
- 不 merge。
- 不评论。
- 不改 PR。

本地分支、checkout、diff、提交仍由 Codex 直接使用 `git` 完成。

## 当前返回结构

所有 operation 统一返回：

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

设计重点：

- `data` 放紧凑结果和本地路径。
- `evidence` 放真实 Gitea API 调用证据。
- 大日志和 artifact 内容只落盘，不进模型上下文。
- `ok=false` 时看 `error.code`、`error.message`、`error.details`。

## 当前 skill 结构

已拆成渐进式披露：

```text
templates/skills/localgpt-platform/
  SKILL.md
  references/
    ci-failure.md
    artifact-analysis.md
    pr-workflow.md
```

`SKILL.md` 只保留常用入口和边界。复杂流程放 references。

## 不需要做进 MCP 的能力

这些交给 Codex 本地能力，不要重复实现：

```text
workspace prepare
workspace exec
workspace diff
workspace patch
workspace write file
workspace reset
create local branch
git status / diff / log / show / commit / push
运行测试 / 构建 / lint
搜索日志文件
读取 artifact 内文件
解析本地测试报告
```

这些不是 Gitea 平台 API 的价值点。把它们塞进 MCP 会制造重复抽象，也会限制 Codex 本地能力。

## 必要技术边界

保留这些边界，因为它们是工具安全和上下文成本问题，不是限制 GPT-5.5 的推理能力：

- 不返回 token、secret、私钥、registration token。
- job log 不直接返回正文。
- artifact 内容不直接返回正文。
- 本地写入只写到传入的 `cwd` 下面。
- 不接受 `target_dir` 这类任意输出目录。
- zip 解压要防路径穿越。
- 组合读 operation 不顺手执行远端写操作。

## 待实现功能

下面留给后续实现。

### 1. `ci.find_runs`

目标：

- 只查 run，不下载日志。
- 根据 branch、head_sha、status、workflow、event 查询候选 runs。
- 返回紧凑列表。

用途：

- 当 Codex 还不确定应该分析哪个 run 时，先用它找候选。

### 2. `ci.get_run_summary`

目标：

- 查询单个 run。
- 查询 jobs。
- 返回 run + job 紧凑摘要。
- 不下载日志。

用途：

- 比 `ci.prepare_failure_context` 更轻。
- 适合只想看 CI 当前状态的场景。

### 3. `workflow.rerun_run`

目标：

- 显式重跑整个 workflow run。
- 远端写操作，metadata 必须标记 `writes_remote=true`。

说明：

- 只在 Gitea 官方 API 确认支持后实现。
- 不要藏进 `ci.prepare_failure_context`。

### 4. `workflow.rerun_job`

目标：

- 显式重跑单个 job。
- 远端写操作，metadata 必须标记 `writes_remote=true`。

用途：

- 平台偶发、网络偶发、runner 偶发失败时使用。

### 5. `workflow.dispatch_and_track`

目标：

- 触发 workflow dispatch。
- 再根据 workflow_id、ref、created_after 查询候选 runs。
- 返回 candidate runs，不硬说一定匹配。

说明：

- 远端写操作。
- `dispatch` 不应假设直接拿到 run_id。

### 6. `pr.publish`

目标：

- 创建或更新 PR。
- 输入 head、base、title、body、mode。
- 返回 PR number、URL、created_or_updated、evidence。

说明：

- 只处理 Gitea 平台 PR API。
- 本地 commit 和 push 仍由 Codex 用 git 完成。
- 后续可支持 `expected_head_sha`。

### 7. `pr.comment`

目标：

- 给 PR 追加评论。
- 显式远端写操作。

说明：

- 不要让 CI 诊断组合 operation 自动评论。

### 8. `pr.merge`

目标：

- 合并 PR。
- 显式远端写操作。

说明：

- 只在用户明确要求合并时由 Codex 调用。
- 建议参数包含 `expected_head_sha`。

### 9. `runner.diagnose_queue`

目标：

- 查询 queued/in_progress runs。
- 查询 repo runners。
- 返回 runner 在线、禁用、busy、label mismatch 的事实摘要。

用途：

- 判断 CI 卡住是否与 runner 有关。

### 10. `artifact.index_local`

目标：

- 对已下载 artifact 生成本地文件树索引。
- 返回 path、bytes、kind。
- 不返回文件内容。

说明：

- 这个不是必须。Codex 可以用 shell 做。
- 如果实现，只作为便利 operation。

### 11. cache 相关能力

候选：

```text
cache.list
cache.plan_delete
cache.delete
```

说明：

- 只有 Gitea 官方 API 明确支持 Actions cache 管理时才实现。
- 不使用内部 API。
- `cache.delete` 必须是显式远端写/删操作。

## 后续实现优先级

建议顺序：

```text
1. ci.find_runs
2. ci.get_run_summary
3. workflow.rerun_run
4. workflow.rerun_job
5. pr.publish
6. pr.comment
7. runner.diagnose_queue
8. workflow.dispatch_and_track
9. pr.merge
10. artifact.index_local
11. cache.*
```

优先补远端平台状态和平台动作，不补 Codex 本地已经有的代码编辑、shell、git、测试能力。
