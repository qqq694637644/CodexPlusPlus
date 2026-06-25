# Workflow 远端写操作

只有当用户明确要求 trigger、dispatch 或 rerun Gitea Actions workflow/job 时，使用本参考。

## 操作列表

```text
workflow.dispatch_and_track
workflow.rerun_run
workflow.rerun_job
```

## 通用规则

- 调用前必须用 `gitea_describe_operations(operation=..., detail=full)` 查看 full schema。
- 必须传 JSON boolean `confirm=true`；字符串 `"true"`、数字 `1` 或其它 truthy 值都不合法。
- 必须传 schema 要求的 `expected_*` 参数。
- 不要把 rerun 或 dispatch 隐藏在只读 CI 诊断流程里。
- 不要在失败后自动重复远端写操作。
- 如果远端写请求可能已经成功但后续跟踪失败，先用只读 operation 查询真实 Gitea 状态。

## `workflow.rerun_job`

用途：重跑单个 job。

流程：

1. 读取 job。
2. 校验 required `run_id`。
3. 校验可选 `expected_status` 和 `expected_conclusion`。
4. POST 到 run-scoped job rerun endpoint。

示例：

```json
{
  "operation": "workflow.rerun_job",
  "repo": "owner/repo",
  "params": {
    "run_id": 123,
    "job_id": 456,
    "expected_status": "failure",
    "confirm": true
  }
}
```

## `workflow.rerun_run`

用途：重跑整个 workflow run。

流程：

1. 读取 run。
2. 校验 `expected_head_sha`。
3. 校验可选 `expected_status` 和 `expected_conclusion`。
4. POST 到 run rerun endpoint。

示例：

```json
{
  "operation": "workflow.rerun_run",
  "repo": "owner/repo",
  "params": {
    "run_id": 123,
    "expected_head_sha": "abc123",
    "confirm": true
  }
}
```

## `workflow.dispatch_and_track`

用途：触发 workflow_dispatch 并尝试匹配新 run。

示例：

```json
{
  "operation": "workflow.dispatch_and_track",
  "repo": "owner/repo",
  "params": {
    "workflow_id": "ci.yml",
    "ref": "main",
    "inputs": {
      "reason": "manual-test"
    },
    "confirm": true
  }
}
```

参数规则：

- `workflow_id` 是 workflow id 或 workflow 文件名。
- `ref` 是 dispatch ref。
- `inputs` 必须是 `object[string,string]`。
- `inputs` 中的 boolean、number、array、nested object、非 string key 都必须在调用前拒绝。
- `refs/heads/<branch>` 会归一化为 `branch=<branch>`。
- tag 或其它 full ref 不应强行当作 branch 查询。

## Dispatch 跟踪兼容规则

当前 provider 期望 dispatch 响应包含 Gitea `RunDetails.workflow_run_id`，并以它作为 definite match。

但真实 Gitea 环境可能出现：

```text
dispatch 已成功创建 run
后续 workflow-scoped runs tracking 失败或返回 404
repo-scoped /actions/runs 能看到新 run
```

遇到这种情况：

- 不要自动再次 dispatch；
- 不要直接断言 workflow 没有触发；
- 用只读 run 查询确认真实远端状态；
- 查询 repo-scoped runs 时不要传 `workflow_id`；
- 如果能看到新 run，应报告“dispatch 可能成功，但 provider tracking 不兼容”；
- 后续应修 provider/parser，而不是让模型重复远端写操作。

只读确认示例：

```json
{
  "operation": "actions.list_runs",
  "repo": "owner/repo",
  "params": {
    "branch": "main",
    "event": "workflow_dispatch",
    "limit": 10
  }
}
```
