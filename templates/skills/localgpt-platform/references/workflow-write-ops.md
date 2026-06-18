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
- Pass `confirm=true`.
- Pass required `expected_*` fields.
- Do not hide rerun or dispatch inside read-only CI diagnosis flows.
- Do not retry automatically after failure.

## `workflow.rerun_job`

Reads the job first, verifies optional `expected_status`, `expected_conclusion`, and `expected_run_id`, then posts to the job rerun endpoint.

## `workflow.rerun_run`

Reads the run first, verifies required `expected_head_sha` and optional status/conclusion, then posts to the run rerun endpoint.

## `workflow.dispatch_and_track`

Dispatches a workflow, then queries candidate runs by workflow/ref/actor/created_after. It returns candidate runs and does not claim a definite match unless the dispatch response contains a run id.
