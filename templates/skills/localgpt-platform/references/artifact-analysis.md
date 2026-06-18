# Artifact sync and analysis

Use this reference when a task asks to inspect Gitea Actions artifacts or synchronize artifacts for local analysis.

## Preferred operation

Use `artifact.sync_for_run` for a whole run:

```json
{
  "operation": "artifact.sync_for_run",
  "repo": "owner/repo",
  "params": {
    "cwd": "D:\\work\\repo",
    "run_id": 123,
    "artifact_name_pattern": "test-*"
  }
}
```

If `artifact_name_pattern` is omitted, all artifacts returned by the run artifacts endpoint are selected.

## Output layout

When no explicit `job_id` is provided, artifacts are written under a run pseudo-job:

```text
{cwd}/jobs/run-<run_id>/artifact/
{cwd}/jobs/run-<run_id>/artifact/<artifact_name>.zip
{cwd}/jobs/run-<run_id>/artifact/<artifact_name>/...
{cwd}/jobs/run-<run_id>/artifact/manifest.json
```

For a single artifact, `actions.download_artifact` writes to:

```text
{cwd}/jobs/<job_id>/artifact/
{cwd}/jobs/<job_id>/artifact/<artifact_name>.zip
{cwd}/jobs/<job_id>/artifact/manifest.json
```

## Rules

- `cwd` must be an existing directory.
- `target_dir` is forbidden.
- Zip extraction rejects zip-slip paths.
- Artifact content is never returned in the MCP response.
- Read local files selectively after sync.

## Strict response handling

`artifact.sync_for_run` expects the run artifacts endpoint to return:

```text
object with artifacts: list[object]
```

A malformed shape must return `unexpected_response_shape`; do not convert it into `ok=true` with an empty artifact list.

No matching artifact name pattern is allowed to be `ok=true` with a warning, because the response shape was valid but the filter selected nothing.
