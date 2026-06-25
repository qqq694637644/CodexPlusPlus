# Artifact 同步与分析

当任务需要检查 Gitea Actions artifact 或把 artifact 同步到本地分析时，使用本参考。

## 边界

- Gitea 是当前项目 artifact 事实源。
- `cwd` 表示 `THREAD_CWD`，不是 `REPO_ROOT`。
- artifact zip、解压文件、manifest 只能写入 `THREAD_CWD/jobs/...`。
- 禁止把 artifact 写入 Git 仓库。
- 禁止传 `target_dir`。
- artifact 内容不直接放进 MCP 响应；同步后用 shell 读取本地文件。

## 首选操作

同步整个 run 的 artifact：

```json
{
  "operation": "artifact.sync_for_run",
  "repo": "owner/repo",
  "params": {
    "cwd": "<THREAD_CWD>",
    "run_id": 123,
    "artifact_name_pattern": "test-*"
  }
}
```

如果省略 `artifact_name_pattern`，会选择 run artifacts endpoint 返回的全部 artifact。

## 输出布局

未显式传入 `job_id` 时，artifact 写入 run 伪 job 目录：

```text
<THREAD_CWD>/jobs/run-<run_id>/artifact/
<THREAD_CWD>/jobs/run-<run_id>/artifact/<artifact_name>/...
<THREAD_CWD>/jobs/run-<run_id>/artifact/manifest.json
```

单个 artifact 使用 `actions.download_artifact`，写入：

```text
<THREAD_CWD>/jobs/<job_id>/artifact/
<THREAD_CWD>/jobs/<job_id>/artifact/manifest.json
```

Gitea artifact API 返回的 zip 只是临时传输文件。MCP 成功解压后必须删除该 zip，只保留解压后的文件和 `manifest.json`。

## 单个 artifact 下载

```json
{
  "operation": "actions.download_artifact",
  "repo": "owner/repo",
  "params": {
    "cwd": "<THREAD_CWD>",
    "job_id": 456,
    "artifact_id": 789,
    "artifact_name": "test-results"
  }
}
```

## 分析方式

同步成功后，用 shell 在 `THREAD_CWD/jobs/...` 下执行最小必要读取：

```text
列目录
读取 manifest.json
搜索关键失败文件
读取相关文本片段
```

不要把完整 artifact 内容塞进上下文。二进制、超大文件或未知格式文件，只报告路径、大小、hash 或解析失败原因。

## 安全规则

- `cwd` 必须是已存在的 `THREAD_CWD`。
- 禁止传入 `target_dir`。
- 不暴露 `extract` 参数。
- 成功响应不返回 `zip_path`、`transport_zip_path`、`retained_zip_paths`。
- zip 解压必须拒绝 zip-slip 越界路径。
- artifact 名称必须作为路径片段安全化。

## 严格响应处理

`artifact.sync_for_run` 期望 run artifacts endpoint 返回：

```text
object with artifacts: list[object]
```

响应 shape 错误必须返回 `unexpected_response_shape`，不能把 malformed response 当成空 artifact 列表。

artifact 名称过滤没有命中时可以返回 `ok=true` 加 warning，因为远端响应 shape 是合法的，只是本地过滤结果为空。
