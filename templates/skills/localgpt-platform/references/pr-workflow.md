# PR preflight workflow

Use this reference when a task asks to inspect a Gitea PR before fixing, reviewing, or merging.

## Preferred operation

Use `pr.preflight`:

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

## Behavior

- Reads PR metadata.
- Reads base/head refs and head SHA.
- Reads changed files summary.
- Queries Actions runs for the PR head SHA.
- Does not checkout code.
- Does not fetch or modify git state.
- Does not merge or comment.

## Strict response handling

Expected shapes:

```text
pulls.get:       object with head: object, base: object, state, and head.sha
pulls.files:     top-level list[object]
actions.list_runs for head_sha: object with workflow_runs: list[object]
```

A malformed files or runs response must return `unexpected_response_shape`. Do not convert missing keys into empty changed-file or CI summaries.

## Follow-ups

If the returned CI summary includes failed runs, use `ci.prepare_failure_context` with the failing `run_id` or `head_sha`.

If artifacts are present and relevant, use `artifact.sync_for_run` for that run.

## Remote write operations

Use only when the user explicitly asks to create/update/comment/merge PR state.

```text
pr.publish
pr.comment
pr.merge
```

Rules:

- Always inspect the full schema with `gitea_describe_operations(operation=..., detail=full)` before calling.
- Pass `confirm=true`.
- Pass required `expected_*` fields.
- `pr.publish` supports `mode=create|update`; it does not implement broad upsert.
- `pr.comment` returns body length and hash, not full comment body.
- `pr.merge` requires `expected_head_sha`, `base_branch`, `merge_method`, and defaults to `require_ci_success=true`.
