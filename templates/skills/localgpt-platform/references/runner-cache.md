# Runner and cache diagnosis

Use this reference when CI appears queued, stuck, runner-related, or cache-related.

## Runner queue

Use `runner.diagnose_queue` to collect remote facts:

```json
{
  "operation": "runner.diagnose_queue",
  "repo": "owner/repo",
  "params": {
    "limit": 10
  }
}
```

It reads queued runs, in-progress runs, and repository runners. It does not modify runners.

## Cache boundary

Use `cache.diagnose` only to record the current boundary and collect recent run candidates:

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

Current rule:

- The MCP uses only Gitea official `/api/v1` REST API.
- It does not implement `cache.list`, `cache.plan_delete`, or `cache.delete` until Gitea exposes official repository Actions cache management endpoints.
- Diagnose cache keys, restore-keys, runner tool cache, and downloaded logs with local shell after remote facts are collected.
