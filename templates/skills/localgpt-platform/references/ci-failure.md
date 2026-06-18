# CI failure workflow

Use this reference when a task asks for Gitea Actions run/job status, failed CI context, or job logs.

## Preferred operation

Use `ci.prepare_failure_context` first when the goal is to understand a failed run.

```json
{
  "operation": "ci.prepare_failure_context",
  "repo": "owner/repo",
  "params": {
    "cwd": "D:\\work\\repo",
    "run_id": 123
  }
}
```

Alternative locator params when `run_id` is unknown:

```json
{
  "operation": "ci.prepare_failure_context",
  "repo": "owner/repo",
  "params": {
    "cwd": "D:\\work\\repo",
    "head_sha": "abc123",
    "status": "failure",
    "limit": 10
  }
}
```

## Behavior

- Reads run metadata.
- Lists run jobs.
- Downloads failed job logs to `{cwd}/jobs/<job_id>/job.log`.
- Optionally lists run artifacts.
- Does not rerun workflows or jobs.
- Does not comment on PRs.
- Does not return full log text.

## Local file handling

Read only relevant local snippets after the operation returns:

```text
{cwd}/jobs/<job_id>/job.log
```

Do not paste full logs into the model context.

## Strict response handling

During development, malformed Gitea responses must fail with `ok=false` and `error.code=unexpected_response_shape`. Do not treat missing keys as empty lists.

Expected shapes used by the strict parser:

```text
actions.list_runs:      object with workflow_runs: list[object]
actions.list_run_jobs:  object with jobs: list[object]
actions.list_artifacts: object with artifacts: list[object]
```

If strict parsing fails, inspect `error.details.step`, `path`, `expected`, and `actual_keys`, then update the provider/parser with the real Gitea API shape.
