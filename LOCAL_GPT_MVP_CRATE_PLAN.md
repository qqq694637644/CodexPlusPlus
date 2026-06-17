# LocalGPT MVP 方案

## 目标

只做一件事：当 Codex App 从源项目 `D:\repos\CodexPlusPlus` 新开会话时，自动把该会话切到独立 workspace，并让该会话使用对应的 `.venv` 环境。

```text
SOURCE_CWD      = D:\repos\CodexPlusPlus
WORKSPACE_ROOT  = D:\repos\CodexPlusPlus\data
WORKSPACE_ID    = localgpt-{uuid}
WORKSPACE_PATH  = D:\repos\CodexPlusPlus\data\localgpt-{uuid}
VENV_PATH       = D:\repos\CodexPlusPlus\data\localgpt-{uuid}\.venv
TEMPLATE_ROOT   = D:\repos\CodexPlusPlus\templates
```

同一个 `threadId` 后续所有 turn 都必须继续使用同一个 `WORKSPACE_PATH`。

## 已验证结论

- `thread/start` / `thread-prewarm-start` 注入 `shell_environment_policy` 有效。
- `turn/start` 改写 `cwd` 有效。
- `turn/start` 注入 `shell_environment_policy` 无效，不使用这条路。
- Codex App 重启后 JS hook 会丢，所以正式 hook 需要随 App 注入重新安装。
- 映射必须持久化到 Rust 侧文件，不依赖 JS 内存。

## 当前不做

- 不做多项目配置。
- 不做 UI。
- 不修改 `launcher.rs` / `cli_wrapper.rs`。
- 不把模板编译进二进制。
- 不在 `turn/start` 找不到映射时偷偷创建 workspace。
- 不持久化未完成的 `requestId` 中间态。

## 文件布局

```text
localgpt/
  Cargo.toml
  config.json
  src/
    lib.rs
    bridge.rs
    bootstrap.rs
    config.rs
    paths.rs
    state.rs
    templates.rs
  js/
    localgpt_hook.js

templates/
  AGENTS.md
  skills/
    localgpt-workspace/
      SKILL.md

scripts/
  prepare_副本.py

build/CodexPlusPlus-localgpt/
  # 自动生成的运行副本

data/
  localgpt-state.json
  localgpt-{uuid}/
    AGENTS.md
    .agents/
      skills/
    .venv/
```

## 配置

`localgpt/config.json` 写死业务路径：

```json
{
  "source_cwd": "D:\\repos\\CodexPlusPlus",
  "workspace_root": "D:\\repos\\CodexPlusPlus\\data"
}
```

模板运行时从源项目读取：

```text
D:\repos\CodexPlusPlus\templates\AGENTS.md
D:\repos\CodexPlusPlus\templates\skills
```

## 状态设计

### 持久化状态

只持久化最终绑定关系：

```json
{
  "threads": {
    "019ed5af-d10d-7c12-b3c7-cd81b7b1ea44": "localgpt-8be71464-be84-49c9-a166-37458d61a674"
  }
}
```

含义：

```text
threadId -> workspaceId
```

建议保存到：

```text
D:\repos\CodexPlusPlus\data\localgpt-state.json
```

### 内存临时状态

只在 JS hook 内存中保存正在创建的 thread：

```js
requestIdToWorkspaceId.set(request.id, workspaceId)
```

用途：`thread/start` response 回来时，把真实 `threadId` 和刚创建的 `workspaceId` 对上。

response 成功后立即删除：

```js
requestIdToWorkspaceId.delete(request.id)
```

这个中间态不持久化。App 重启时未完成的 `thread/start` 请求直接丢弃。

## JS hook 流程

### 1. 拦截 `thread/start`

匹配：

```js
type === "mcp-request" && request.method === "thread/start"
```

以及：

```js
type === "thread-prewarm-start" && request.method === "thread/start"
```

处理规则：

```text
如果 params.cwd != SOURCE_CWD：
    passthrough

否则：
    调 Rust bridge 创建 workspace
    JS 内存记录 request.id -> workspaceId
    改写 params.cwd = WORKSPACE_PATH
    注入 shell_environment_policy
```

注入字段：

```js
params.config = {
  ...params.config,
  "shell_environment_policy.inherit": "all",
  "shell_environment_policy.set": {
    ...params.config?.["shell_environment_policy.set"],
    VIRTUAL_ENV: venvPath
  }
}
```

同时建议改写：

```js
params.workspaceRoots = [workspacePath]
```

### 2. 监听 `thread/start` response

从 response 里取：

```text
request.id
result.thread.id
```

然后：

```text
workspaceId = requestIdToWorkspaceId[request.id]
持久化 threads[result.thread.id] = workspaceId
删除 requestIdToWorkspaceId[request.id]
```

如果找不到内存映射，fail fast。  
如果 response 里没有 `threadId`，fail fast。

### 3. 拦截 `turn/start`

匹配：

```js
type === "mcp-request" && request.method === "turn/start"
```

处理规则：

```text
threadId = params.threadId
workspaceId = 持久化状态 threads[threadId]

如果 workspaceId 存在：
    params.cwd = WORKSPACE_ROOT\workspaceId

否则如果 params.cwd == SOURCE_CWD：
    fail fast

否则：
    passthrough
```

`turn/start` 不创建 workspace，也不注入 `shell_environment_policy`。

## Rust bridge 接口

### `/localgpt/prepare-thread-start`

输入：

```json
{
  "requestId": "thread/start request.id",
  "cwd": "D:\\repos\\CodexPlusPlus"
}
```

输出：

```json
{
  "action": "rewrite",
  "requestId": "...",
  "workspaceId": "localgpt-uuid",
  "workspace": "D:\\repos\\CodexPlusPlus\\data\\localgpt-uuid",
  "venv": "D:\\repos\\CodexPlusPlus\\data\\localgpt-uuid\\.venv"
}
```

职责：

- 校验 `cwd == SOURCE_CWD`。
- 生成 `localgpt-{uuid}`。
- 事务式创建 workspace。
- 创建 `.venv` 目录或运行 `python -m venv`，按当前实现阶段决定。
- 复制模板 `AGENTS.md` 和 `skills`。
- 不写 `threadId` 映射，因为此时还没有真实 `threadId`。

### `/localgpt/commit-thread-start`

输入：

```json
{
  "threadId": "019e...",
  "workspaceId": "localgpt-uuid"
}
```

职责：

```text
校验 workspaceId 合法
校验 workspace 存在
写入 threads[threadId] = workspaceId
保存 localgpt-state.json
```

### `/localgpt/prepare-turn-start`

输入：

```json
{
  "threadId": "019e...",
  "cwd": "..."
}
```

输出一：命中映射

```json
{
  "action": "rewrite",
  "threadId": "019e...",
  "cwd": "D:\\repos\\CodexPlusPlus\\data\\localgpt-uuid"
}
```

输出二：非目标 cwd 放行

```json
{
  "action": "passthrough",
  "reason": "cwd_mismatch"
}
```

规则：

```text
如果 threadId 已绑定：rewrite
如果未绑定且 cwd == SOURCE_CWD：fail fast
否则：passthrough
```

## workspace 初始化

创建新 workspace 时必须事务式：

```text
data\.localgpt-{uuid}.tmp
  AGENTS.md
  .agents\skills\
  .venv\

rename -> data\localgpt-{uuid}
```

校验最小条件：

```text
AGENTS.md 是文件
.agents\skills 是目录
.venv 是目录
```

如果临时目录已存在，直接 fail fast。  
如果最终目录已存在，直接 fail fast。  
不要补救半成品目录。

## 验证用例

### 新会话

输入：

```text
请运行命令打印当前 cwd 和 VIRTUAL_ENV
```

期望：

```text
cwd = D:\repos\CodexPlusPlus\data\localgpt-{uuid}
VIRTUAL_ENV = D:\repos\CodexPlusPlus\data\localgpt-{uuid}\.venv
```

状态文件出现：

```json
{
  "threads": {
    "{threadId}": "localgpt-{uuid}"
  }
}
```

### 同会话后续 turn

继续输入同样命令。

期望：

```text
cwd 不变
VIRTUAL_ENV 不变
```

### 重启 Codex App

重启后重新安装正式 hook，打开旧会话继续输入。

期望：

```text
threadId 从 localgpt-state.json 恢复
cwd 仍然是原 workspace
VIRTUAL_ENV 仍然是原 .venv
```

## 实现约束

- 简单优先，不做未要求的扩展。
- Fail Fast，不吞掉 bridge 错误。
- 不在源项目根目录执行 AI 工作。
- 不保留旧目录规则兼容。
- 不把用户输入完整落盘到日志。
