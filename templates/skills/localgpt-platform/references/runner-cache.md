# Runner / cache 诊断

当 CI queued、stuck、runner 相关或 cache 边界可疑时，使用本参考。

## 边界

- Gitea 是当前项目 run、queue、runner 事实源。
- 本 MCP 当前只使用 Gitea 官方 `/api/v1` REST API。
- 当前只提供 runner/cache 诊断，不提供 runner 修改或 cache 删除。
- 不要用网页搜索、GitHub 或旧 fork 推断当前项目 runner/cache 状态。

## Runner 队列

使用 `runner.diagnose_queue` 收集远端事实：

```json
{
  "operation": "runner.diagnose_queue",
  "repo": "owner/repo",
  "params": {
    "limit": 10
  }
}
```

可选过滤：

```json
{
  "operation": "runner.diagnose_queue",
  "repo": "owner/repo",
  "params": {
    "branch": "main",
    "workflow_id": "ci.yml",
    "limit": 10,
    "disabled": false
  }
}
```

行为：

- 读取 queued runs；
- 读取 in-progress runs；
- 读取 repository runners；
- 不修改 runner；
- 不 rerun workflow/job。

## Cache 边界

使用 `cache.diagnose` 记录当前边界并收集近期 run candidates：

```json
{
  "operation": "cache.diagnose",
  "repo": "owner/repo",
  "params": {
    "status": "failure",
    "limit": 10
  }
}
```

当前规则：

- MCP 当前没有列出、计划删除或删除 Actions cache 的 operation。
- 只有等 Gitea 暴露官方 repository Actions cache management endpoint 后，才应加入 cache 修改 operation。
- 需要分析 cache key、restore-key、runner tool cache 或下载日志时，先通过 Gitea MCP 收集远端事实，再用本地 shell 分析已落盘日志或仓库配置。

## 判断建议

- queued runs 多且 runner 不在线：优先报告 runner 不可用或容量不足。
- queued runs 多但 runner 在线：检查 label、workflow runner 要求和 runner scope。
- 失败集中在 dependency/cache step：结合 job log 诊断 cache key、restore-key、权限或网络问题。
- 平台偶发问题才建议 rerun；rerun 仍属于远端写操作，必须用户明确要求。
