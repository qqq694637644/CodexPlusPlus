# Workflow remote write operations

Use this reference only when the user explicitly asks to trigger or rerun Gitea Actions workflows/jobs.

## Operations

```text
workflow.rerun_job
workflow.rerun_run
workflow.dispatch_and_track
```

## Rules

- Inspect the full schema first with `gitea_describe_operations(operation=..., detail=full)`.
- Pass JSON boolean `confirm=true`; strings like `"true"`, numbers like `1`, and other truthy values are rejected.
- Pass required `expected_*` fields.
- Do not hide rerun or dispatch inside read-only CI diagnosis flows.
- Do not retry automatically after failure.

## `workflow.rerun_job`

Reads the job first, verifies required `run_id` plus optional `expected_status` and `expected_conclusion`, then posts to the run-scoped job rerun endpoint.

## `workflow.rerun_run`

Reads the run first, verifies required `expected_head_sha` and optional status/conclusion, then posts to the run rerun endpoint.

## `workflow.dispatch_and_track`

Dispatches a workflow with query parameter `return_run_details=true`, then requires the Gitea `RunDetails` response field `workflow_run_id`. It also queries candidate runs by workflow/ref/actor/created_after for context, but a definite match comes from `workflow_run_id` only.
