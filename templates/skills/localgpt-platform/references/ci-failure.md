# CI 失败诊断

当任务要求检查 Gitea Actions run / job 状态、失败 CI 上下文或 job log 时，使用本参考。

`cwd` 一律表示 `THREAD_CWD`，不是 `REPO_ROOT`。

## 首选操作

目标是理解失败 run 时，优先使用 `ci.prepare_failure_context`：

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

未知 `run_id` 时，用候选条件定位：

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

## 行为

- 读取 run metadata。
- 列出 run jobs。
- 下载失败 job logs 到 `THREAD_CWD/jobs/<job_id>/job.log`。
- 可选列出 run artifacts。
- 不 rerun workflow。
- 不 rerun job。
- 不评论 PR。
- 不返回完整日志正文。

## 本地文件处理

operation 返回后，只读取相关片段：

```text
<THREAD_CWD>/jobs/<job_id>/job.log
```

不要把完整大日志复制进上下文。需要汇报时，只摘取与失败直接相关的命令、错误行、路径和退出码。

## 只读补充查询

需要更轻量的 run / job 摘要时，使用：

```text
ci.find_run_candidates
ci.get_run_summary
actions.get_run
actions.list_run_jobs
actions.get_job
actions.list_artifacts
```

不要从 workflow run 列表里假设 job 明细；需要 job 状态时显式查询 jobs。

## 严格响应处理

开发期 malformed Gitea response 必须返回：

```text
ok=false
error.code=unexpected_response_shape
```

不要把 missing keys 当成空列表。

strict parser 期望的关键 shape：

```text
actions.list_runs:      object with workflow_runs: list[object]
actions.list_run_jobs:  object with jobs: list[object]
actions.list_artifacts: object with artifacts: list[object]
```

如果 strict parsing 失败，检查 `error.details.step`、`path`、`expected` 和 `actual_keys`，然后修 provider / parser 以适配真实 Gitea API shape。
