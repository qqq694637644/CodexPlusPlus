# PR 前置检查与 PR 写操作

当任务要求检查、修复、审查、创建、更新、评论或合并 Gitea PR 时，使用本参考。

## 边界

- Gitea 是当前项目 PR 事实源。
- 不要用 GitHub、网页搜索、公开镜像或旧 fork 推断当前 PR 状态。
- 本地代码修改、commit、push 使用 shell 和本地 Git。
- PR metadata、changed files、head SHA、CI 状态使用 Gitea MCP。
- 创建、更新、评论、合并 PR 都是远端写操作。代码修改任务中的 PR 创建或更新属于默认交付路径；评论和合并必须由用户明确要求。

## PR 前置检查

修复、审查或合并 PR 前，优先使用 `pr.preflight`：

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

## `pr.preflight` 行为

- 读取 PR metadata；
- 读取 base/head refs 和 head SHA；
- 读取 changed files summary；
- 查询 PR head SHA 对应 Actions runs；
- 不 checkout 代码；
- 不 fetch 或修改 Git 状态；
- 不 merge；
- 不评论。

## 修复已有 PR 的推荐流程

1. `pr.preflight` 获取 PR 事实。
2. 用本地 Git 准备或切换到 PR head 分支。
3. 阅读最小必要代码上下文。
4. 做最小必要修改。
5. 运行相关验证。
6. 查看 diff。
7. commit 并 push 到 Gitea。
8. 用 `pr.preflight` 或 run 查询确认新 head SHA 和 CI 状态。

## 创建或更新 PR

`pr.publish` 是远端写操作。用户要求完成代码修改、修复或提交 PR 时，它可以作为默认 PR 交付路径使用；只读分析任务中不要调用。

创建：

```json
{
  "operation": "pr.publish",
  "repo": "owner/repo",
  "params": {
    "mode": "create",
    "head": "gpt/fix-ci",
    "base": "main",
    "title": "Fix CI failure",
    "body": "Summary and validation.",
    "expected_head_sha": "abc123",
    "confirm": true
  }
}
```

更新：

```json
{
  "operation": "pr.publish",
  "repo": "owner/repo",
  "params": {
    "mode": "update",
    "existing_pr_number": 42,
    "title": "Updated title",
    "body": "Updated summary.",
    "expected_head_sha": "abc123",
    "confirm": true
  }
}
```

规则：

- 调用前查看 full schema。
- 必须传 `confirm=true`。
- 必须传 `expected_head_sha`。
- `mode=create` 需要 `head` 和 `title`。
- `mode=update` 需要 `existing_pr_number`。
- `pr.publish` 不做宽泛 upsert。

## PR 评论

`pr.comment` 是远端写操作，只在用户明确要求评论时使用：

```json
{
  "operation": "pr.comment",
  "repo": "owner/repo",
  "params": {
    "pr_number": 42,
    "body": "CI failure summary.",
    "confirm": true
  }
}
```

规则：

- 调用前查看 full schema。
- 必须传 `confirm=true`。
- 评论正文不要包含 secret、token、完整大日志或无关 artifact 内容。
- 响应返回 body length 和 hash，不返回完整 comment body。

## PR 合并

`pr.merge` 是高风险远端写操作。只有用户明确要求合并时才允许。

合并前必须完成：

1. `pr.preflight`；
2. 确认 PR 是 open；
3. 确认 PR 非 draft；
4. 确认 base branch 符合用户目标；
5. 确认当前 head SHA；
6. 确认 CI 策略；
7. 查看 full schema；
8. 传 `confirm=true` 和 `expected_head_sha`。

示例：

```json
{
  "operation": "pr.merge",
  "repo": "owner/repo",
  "params": {
    "pr_number": 42,
    "expected_head_sha": "abc123",
    "base_branch": "main",
    "merge_method": "merge",
    "require_ci_success": true,
    "confirm": true
  }
}
```

## 严格响应处理

期望 shape：

```text
pulls.get:       object with head: object, base: object, state, and head.sha
pulls.files:     top-level list[object]
actions.list_runs for head_sha: object with workflow_runs: list[object]
```

malformed files 或 runs response 必须返回 `unexpected_response_shape`。不要把缺失 key 转成空 changed-file 或空 CI summary。

## 后续动作

- 如果 CI summary 包含 failed runs，使用 `ci.prepare_failure_context`。
- 如果 artifact 与失败相关，使用 `artifact.sync_for_run`。
- 如果 runner/queue 可疑，使用 `runner.diagnose_queue`。
