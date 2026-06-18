# LocalGPT Gitea MCP 第一版

## 定位

`localgpt_platform` 是给 Codex 使用的 Python MCP server，通过 Gitea 官方 `/api/v1` REST API 查询 CI/CD 状态。

第一版只做只读诊断：

- 查询 Gitea 版本和当前用户。
- 查询仓库。
- 查询 Actions workflow、run、job、job log。
- 查询 artifact，并把 artifact 下载到 workspace 的 job 目录。
- 查询仓库级 runner。

不做：

- 本地 `git` 操作。
- 本地测试、构建、shell 编排。
- workflow 重跑、取消、secret 修改、runner 删除等写操作。
- Gitea 内部 `/api/actions_pipeline` 协议。

## Codex MCP 配置

先安装依赖：

```powershell
python -m pip install -r requirements.txt
```

```powershell
cd D:\repos\CodexPlusPlus
codex mcp add localgpt-gitea --env GITEA_BASE_URL=https://gitea.example.com --env GITEA_TOKEN=<token> -- python -m localgpt_platform.mcp_server
```

也可以写入 `~/.codex/config.toml`：

```toml
[mcp_servers.localgpt-gitea]
command = "python"
args = ["-m", "localgpt_platform.mcp_server"]
cwd = "D:\\repos\\CodexPlusPlus"
env_vars = ["GITEA_BASE_URL", "GITEA_TOKEN"]
tool_timeout_sec = 60
```

## 环境变量

| 名称 | 必填 | 说明 |
| --- | --- | --- |
| `GITEA_BASE_URL` | 是 | Gitea 实例地址，例如 `https://gitea.example.com` |
| `GITEA_TOKEN` | 大多数操作需要 | Gitea API token |
| `GITEA_TIMEOUT` | 否 | 请求超时秒数，默认 `30` |
| `GITEA_VERIFY_SSL` | 否 | 是否校验证书，默认 `true` |

`actions.get_job_log` 和 `actions.download_artifact` 需要传入当前 Codex workspace 的 `cwd` 参数，并固定写入：

```text
{cwd}/jobs/{job_id}/job.log
{cwd}/jobs/{job_id}/artifact/
```

`actions.download_artifact` 不接受任意下载目录参数。所有 zip 和解压文件都必须落在 `{cwd}/jobs/{job_id}/artifact/` 内，路径越界会直接失败。

## MCP 工具

| 工具 | 用途 |
| --- | --- |
| `gitea_status` | 检查 Gitea 服务器版本 |
| `gitea_describe_operations` | 列出当前启用 operation |
| `gitea_execute` | 执行白名单 operation |

`gitea_describe_operations` 会返回每个 operation 的：

- `repo_required`
- `required_params`
- `optional_params`
- `example`

## 返回结构

成功：

```json
{
  "ok": true,
  "operation": "actions.get_job_log",
  "data": {
    "job_id": "123",
    "log_path": "D:\\work\\repo\\jobs\\123\\job.log",
    "content_returned": false
  },
  "meta": {
    "repo": "owner/repo"
  },
  "evidence": {
    "provider": "gitea",
    "method": "GET",
    "path": "/repos/owner/repo/actions/jobs/123/logs",
    "status_code": 200,
    "download_path": "D:\\work\\repo\\jobs\\123\\job.log"
  }
}
```

失败：

```json
{
  "ok": false,
  "operation": "actions.get_job_log",
  "error": {
    "code": "missing_token",
    "message": "缺少 GITEA_TOKEN 环境变量"
  }
}
```

## CLI 调试

```powershell
python -m localgpt_platform operations
python -m localgpt_platform status
python -m localgpt_platform execute --operation actions.list_runs --repo owner/repo --params-json "{\"limit\": 5}"
```

也可以通过文件传入：

```json
{
  "operation": "actions.list_run_jobs",
  "repo": "owner/repo",
  "params": {
    "run_id": 123
  }
}
```

```powershell
python -m localgpt_platform execute --input-json request.json
```

下载 job log 示例：

```json
{
  "operation": "actions.get_job_log",
  "repo": "owner/repo",
  "params": {
    "cwd": "D:\\work\\repo",
    "job_id": 456
  }
}
```

下载 artifact 示例：

```json
{
  "operation": "actions.download_artifact",
  "repo": "owner/repo",
  "params": {
    "cwd": "D:\\work\\repo",
    "job_id": 456,
    "artifact_id": 789,
    "artifact_name": "test-results",
    "extract": true
  }
}
```
