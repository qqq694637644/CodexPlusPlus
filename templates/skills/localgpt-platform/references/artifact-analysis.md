# Artifact 同步与分析

当任务需要检查 Gitea Actions artifact 或把 artifact 同步到本地分析时，使用本参考。

## 首选 Operation

同步整个 run 的 artifact：

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

如果省略 `artifact_name_pattern`，会选择 run artifacts endpoint 返回的全部 artifact。

## 输出布局

未显式传入 `job_id` 时，artifact 写入 run 伪 job 目录：

```text
{cwd}/jobs/run-<run_id>/artifact/
{cwd}/jobs/run-<run_id>/artifact/<artifact_name>/...
{cwd}/jobs/run-<run_id>/artifact/manifest.json
```

单个 artifact 使用 `actions.download_artifact`，写入：

```text
{cwd}/jobs/<job_id>/artifact/
{cwd}/jobs/<job_id>/artifact/manifest.json
```

Gitea artifact API 返回的 zip 只是临时传输文件。MCP 成功解压后必须删除该 zip，只保留解压后的文件和 `manifest.json`。

## 规则

- `cwd` 必须是已存在目录。
- 禁止传入 `target_dir`。
- 不暴露 `extract` 参数。
- 成功响应不返回 `zip_path`、`transport_zip_path`、`retained_zip_paths`。
- zip 解压必须拒绝 zip-slip 越界路径。
- artifact 内容不直接放进 MCP 响应。
- 同步后用 shell 按需列目录、搜索、读取本地文件。

## 严格响应处理

`artifact.sync_for_run` 期望 run artifacts endpoint 返回：

```text
object with artifacts: list[object]
```

响应 shape 错误必须返回 `unexpected_response_shape`，不能把 malformed response 当成空 artifact 列表。

artifact 名称过滤没有命中时可以返回 `ok=true` 加 warning，因为远端响应 shape 是合法的，只是本地过滤结果为空。
