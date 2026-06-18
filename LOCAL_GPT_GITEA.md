# LocalGPT Gitea MCP 设计契约

## 1. 设计原则

这个 MCP 是给 Codex 本地 workspace 使用的 Gitea 平台能力补充。

Codex 已经具备本地能力：

- 阅读、搜索、修改代码。
- 运行 shell、测试、构建、lint。
- 使用本地 `git` 做 status、diff、branch、commit、push。
- 使用现有编辑工具做 patch 和文件写入。
- 搜索 job log、查看 artifact 文件树、读取本地报告。

所以 Gitea MCP 不重复这些能力。它只负责 Codex 本地拿不到或不应该靠猜的远端平台事实：

- Gitea API 可达性和认证状态。
- 仓库、PR、Actions workflow/run/job/runner 元数据。
- CI job log 下载到本地文件。
- Actions artifact 同步到本地文件。
- 组合查询，把修 CI 所需的远端证据一次准备好。

一句话：

> Codex 负责读代码、改代码、跑测试、提交；Gitea MCP 负责查远端事实、下载日志和 artifact。

## 2. 顶层工具

顶层 MCP 工具保持少量稳定：

```text
gitea_status
gitea_describe_operations
gitea_execute
```

不要把每个 Gitea endpoint 拆成顶层 MCP tool。operation 通过 `gitea_execute` 扩展。

`gitea_describe_operations` 负责渐进披露：

- `detail=brief`：只返回 operation 名称、分类、描述、读写属性和风险等级。
- `detail=full`：返回单个 operation 的完整参数 schema、返回结构和示例。
- `category`：按 `ci`、`artifact`、`pr`、`workflow`、`runner`、`cache` 等分类过滤。
- `operation`：查看单个 operation 的完整契约。

## 3. Operation 契约

每个 operation 必须在 registry 中声明 metadata。metadata 是参数 schema 的唯一事实来源，文档和 skill 不重复维护完整参数表。

必需字段：

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

关键语义字段：

```text
read_only_remote
writes_local_files
writes_remote
requires_cwd
```

所有 operation 返回统一结构：

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

- `data` 放紧凑结果和本地路径。
- `evidence` 放真实 Gitea API 调用证据。
- `warnings` 放非致命问题。
- `next_suggested_operations` 给 Codex 下一步候选，不替 Codex 做最终判断。

失败时：

- `ok=false`
- `error.code`
- `error.message`
- `error.details`

不要把 traceback、大日志、完整 artifact 内容塞进返回值。

## 4. Evidence 契约

每次 Gitea API 调用都应有 evidence。

建议字段：

```text
step
provider
base_url
method
path
status_code
params_summary
result_count
download_path
bytes
link
x_total_count
```

要求：

- 不记录 token、secret、password、registration token。
- 不记录完整大 body。
- 列表 operation 应记录 `result_count`。
- 组合 operation 内部每个 API 调用都应追加 evidence。

## 5. 本地落盘规范

`cwd` 由调用方显式传入，必须是已存在的 Codex workspace 目录。

job log：

```text
{cwd}/jobs/<job_id>/job.log
```

artifact：

```text
{cwd}/jobs/<job_id>/artifact/
{cwd}/jobs/<job_id>/artifact/manifest.json
```

run 级 artifact 默认使用伪 job：

```text
{cwd}/jobs/run-<run_id>/artifact/
{cwd}/jobs/run-<run_id>/artifact/manifest.json
```

规则：

- 本地写入必须在 `cwd` 内。
- 不接受 `target_dir` 这类任意输出目录。
- job log 不直接返回正文。
- artifact 内容不直接返回正文。
- Codex 后续用 shell 搜日志、列文件树、读取报告。

## 6. Artifact Zip 策略

Gitea artifact API 的传输格式是 zip，但 zip 不是默认对外产物。

契约：

- 默认 `extract=true`。
- `extract=true`：zip 是临时传输文件，成功解压后删除。
- `extract=false`：允许保留 zip，返回 `data.zip_path`。
- manifest 必须记录 artifact id、name、extract_dir、file_count、transport_zip_bytes、evidence。
- 解压必须防路径穿越。

当前实现状态见 [LOCAL_GPT_GITEA_STATUS.md](D:/repos/CodexPlusPlus/LOCAL_GPT_GITEA_STATUS.md)。

## 7. 开发期严格模式

开发期必须快速暴露 schema、parser、registry 问题，不做“聪明兜底”。

契约：

- 未知 operation 必须失败。
- 未知 category 必须失败。
- 未声明 params 必须失败为 `unknown_param`。
- response shape 不匹配必须失败为 `unexpected_response_shape`。
- registry 与 handler 必须双向一致。
- operation metadata 缺字段必须 import-time fail。
- 不把 malformed response 当空列表。

这不是限制 GPT-5.5，而是调试质量要求。Codex 需要明确知道问题是“参数传错”、“环境没配”还是“Gitea 响应 shape 和 parser 不匹配”。

## 8. 远端写 Operation 接口契约

远端写 operation 是会修改 Gitea 远端状态的 operation，例如 publish、dispatch、rerun、delete、merge、comment。

契约：

- `writes_remote=true`。
- `risk_level=high`。
- 名称包含明确副作用动词，例如 `publish`、`dispatch`、`rerun`、`delete`、`merge`、`comment`。
- 参数应包含必要的 `expected_*`，避免 Codex 使用陈旧上下文修改新状态。
- `confirm=true` 可作为建议参数，不作为所有写 operation 的强制要求。
- `evidence` 不记录 secret、完整大 body、token、registration token。
- 失败不自动重试。
- 组合读 operation 禁止调用远端写 operation。

这些是远端副作用的接口契约，不是企业审批系统。

## 9. Skill 分层

skill 使用渐进式披露：

```text
templates/skills/localgpt-platform/
  SKILL.md
  references/
    ci-failure.md
    artifact-analysis.md
    pr-workflow.md
```

`SKILL.md` 只放：

- 何时使用 MCP。
- 何时不用 MCP。
- 最常用 CI 修复流程。
- 固定路径规范。
- 大日志和 artifact 的上下文成本规则。
- 指向 references。

复杂 runbook 放 references，不在 `SKILL.md` 堆叠。

## 10. 不进入 MCP 的能力

这些交给 Codex 本地能力，不做 MCP operation：

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
artifact.index_local
```

`artifact.index_local` 不进 Gitea MCP。Codex 已经能用 shell 查看 artifact 文件树；如果未来确实需要便利脚本，应放到 skill 的本地 `scripts/`，不是远端平台 MCP。

## 11. 状态文档

当前已实现 operation、待实现 operation 和后续优先级记录在：

```text
LOCAL_GPT_GITEA_STATUS.md
```

这份设计契约不作为当前实现状态的唯一来源。实现变更时，只需要同步状态文档和 operation registry。
