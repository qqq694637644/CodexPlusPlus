# LocalGPT MVP 详细实现方案

## 1. 目标

当 Codex App 在固定源项目下启动新会话时，把该会话隔离到独立 workspace，并给这个会话绑定独立 `.venv`。

固定源项目：

```text
D:\repos\CodexPlusPlus
```

目标 workspace：

```text
D:\repos\CodexPlusPlus\data\localgpt-{uuid}
```

目标虚拟环境：

```text
D:\repos\CodexPlusPlus\data\localgpt-{uuid}\.venv
```

目标 PATH 前缀：

```text
D:\repos\CodexPlusPlus\data\localgpt-{uuid}\.venv\Scripts
```

最终效果：

```text
新会话第一次 turn：
  cwd         = data\localgpt-{uuid}
  VIRTUAL_ENV = data\localgpt-{uuid}\.venv
  PATH        = data\localgpt-{uuid}\.venv\Scripts;{原 PATH}

同一 threadId 后续所有 turn：
  cwd         = 同一个 data\localgpt-{uuid}
  VIRTUAL_ENV = 同一个 data\localgpt-{uuid}\.venv
  PATH        = 同一个 data\localgpt-{uuid}\.venv\Scripts;{原 PATH}
```

## 2. 已经验证过的事实

### 2.1 `thread/start` 注入环境有效

在 `thread/start` / `thread-prewarm-start` 的 params 里注入：

```js
config["shell_environment_policy.inherit"] = "all"
config["shell_environment_policy.set"].VIRTUAL_ENV = "...\\.venv"
config["shell_environment_policy.set"].PATH = "...\\.venv\\Scripts;" + inheritedPath
```

已验证能进入 Codex 命令执行环境。

### 2.2 `turn/start` 也必须补注入 shell env

`turn/start` 改写 `params.cwd` 有效。

已联合验证：后续 turn 里只保留 `cwd` 和 `VIRTUAL_ENV` 不够，`PATH` 会被 Codex 命令执行链路重新组织，导致 `python` 回落到系统 Python。必须在每个命中的 `turn/start` 里继续注入：

```js
params.config["shell_environment_policy.set"].VIRTUAL_ENV = "...\\.venv"
params.config["shell_environment_policy.set"].PATH = "...\\.venv\\Scripts;" + inheritedPath
```

已验证这样可以让后续 turn 的 `python`、`pip` 和 `sys.executable` 继续指向当前 workspace 的 `.venv`。

### 2.3 `thread/start` 时还没有真实 `threadId`

真实 `threadId` 是 `thread/start` response 回来后才出现的。

因此创建 workspace 的顺序必须是：

```text
thread/start 发出前：
  生成 localgpt-{uuid}
  创建 workspace
  注入 cwd + VIRTUAL_ENV + PATH
  JS 内存记录 request.id -> workspaceId

thread/start response 回来后：
  拿 result.thread.id
  持久化 threadId -> workspaceId
```

### 2.4 Codex App 重启后 JS hook 会丢

所以正式实现必须在 Codex++ 注入层每次重新安装 hook。

但持久化映射不能放 JS 内存，必须放 Rust 侧文件。

## 3. 总体状态设计

### 3.1 持久化状态：只存最终绑定

状态文件：

```text
D:\repos\CodexPlusPlus\data\localgpt-state.json
```

内容：

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

只持久化这个最终关系。

### 3.2 内存临时状态：只存正在创建的 request

JS hook 内部维护：

```js
const requestIdToWorkspaceId = new Map();
```

用途：

```text
thread/start 发出去时：
  requestIdToWorkspaceId[request.id] = workspaceId

thread/start response 回来时：
  workspaceId = requestIdToWorkspaceId[response.id]
  commit threadId -> workspaceId
  delete requestIdToWorkspaceId[response.id]
```

这个 Map 不持久化。App 重启时未完成的 `thread/start` 直接丢弃。

## 4. 目录与文件布局

```text
D:\repos\CodexPlusPlus\
  localgpt\
    Cargo.toml
    config.json
    src\
      lib.rs
      bridge.rs
      bootstrap.rs
      config.rs
      paths.rs
      state.rs
      templates.rs
    js\
      localgpt_hook.js

  templates\
    AGENTS.md
    skills\
      localgpt-workspace\
        SKILL.md

  data\
    localgpt-state.json
    localgpt-{uuid}\
      AGENTS.md
      .agents\
        skills\
      .venv\

  scripts\
    prepare_副本.py

  build\
    CodexPlusPlus-localgpt\
      # 自动生成的运行副本
```

## 5. 配置文件

`localgpt/config.json`：

```json
{
  "source_cwd": "D:\\repos\\CodexPlusPlus",
  "workspace_root": "D:\\repos\\CodexPlusPlus\\data"
}
```

要求：

- 这个配置可以继续通过 `include_str!` 编译进 `localgpt` crate。
- 模板不要编译进二进制，运行时从 `source_cwd\templates` 读取。
- 不做多项目配置。

## 6. Rust crate 设计

### 6.1 `lib.rs`

导出三个 bridge 函数和 hook script：

```rust
pub fn hook_script() -> &'static str;
pub async fn prepare_thread_start(payload: serde_json::Value) -> anyhow::Result<serde_json::Value>;
pub async fn commit_thread_start(payload: serde_json::Value) -> anyhow::Result<serde_json::Value>;
pub async fn prepare_turn_start(payload: serde_json::Value) -> anyhow::Result<serde_json::Value>;
```

不再使用一个含糊的 `handle_bridge` 处理所有语义。

### 6.2 `config.rs`

职责：

- 读取 `localgpt/config.json`。
- 校验 `source_cwd` 非空。
- 校验 `workspace_root` 非空。
- 返回：

```rust
pub struct LocalGptConfig {
    pub source_cwd: PathBuf,
    pub workspace_root: PathBuf,
}
```

开发阶段 fail fast：配置解析失败直接返回 Err。

### 6.3 `paths.rs`

职责：

- 路径规范化。
- 判断 `cwd == source_cwd`。
- 校验 `threadId`。
- 校验 `workspaceId`。
- 从 `workspaceId` 推导 workspace 和 venv。

必须提供的函数：

```rust
pub fn source_cwd() -> anyhow::Result<PathBuf>;
pub fn workspace_root() -> anyhow::Result<PathBuf>;
pub fn is_source_cwd(path: &Path) -> anyhow::Result<bool>;
pub fn workspace_path(workspace_id: &str) -> anyhow::Result<PathBuf>;
pub fn venv_path(workspace_id: &str) -> anyhow::Result<PathBuf>;
pub fn validate_thread_id(thread_id: &str) -> anyhow::Result<()>;
pub fn validate_workspace_id(workspace_id: &str) -> anyhow::Result<()>;
pub fn display_path(path: &Path) -> String;
```

`threadId` 校验：

```text
只能包含 ASCII 字母、数字、短横线、下划线
不能为空
不能包含 ..
不能包含 / 或 \
不能包含 :
```

`workspaceId` 校验：

```text
必须以 localgpt- 开头
后面必须是合法 UUID 字符串
不能包含路径分隔符
不能包含 ..
```

### 6.4 `templates.rs`

职责：

- 模板路径固定从：

```text
{source_cwd}\templates\AGENTS.md
{source_cwd}\templates\skills
```

- 校验：

```text
AGENTS.md 是文件
skills 是目录
```

不要兼容旧路径 `localgpt/templates`。

### 6.5 `bootstrap.rs`

职责：创建新的 workspace。

入口：

```rust
pub fn bootstrap_new_workspace(workspace_id: &str) -> anyhow::Result<WorkspaceInfo>;
```

返回：

```rust
pub struct WorkspaceInfo {
    pub workspace_id: String,
    pub workspace: PathBuf,
    pub venv: PathBuf,
    pub venv_scripts: PathBuf,
}
```

创建规则：

```text
data\.localgpt-{uuid}.tmp\
  AGENTS.md
  .agents\skills\

rename -> data\localgpt-{uuid}

在最终 workspace 路径创建真实 venv：
python -m venv data\localgpt-{uuid}\.venv
```

最小校验：

```text
AGENTS.md 是文件
.agents\skills 是目录
.venv 是目录
```

Fail Fast 规则：

- 临时目录已存在：报错。
- 最终目录已存在：报错。
- 模板缺失：报错。
- 模板 skills 内出现非普通文件且当前实现不支持：报错。
- rename 失败：报错。

`.venv` 阶段策略：

创建真实 Python venv，只做明确实现：

```text
python -m venv {workspace}\.venv
```

必须在 rename 到最终 workspace 之后再执行，不能在临时目录创建 venv 后移动。不要自动搜索多个 Python，不要兜底兼容。找不到 `python` 就 fail fast。venv 创建或最终校验失败时整个 `prepare-thread-start` 失败，不写入 `localgpt-state.json`，并删除刚创建的最终 workspace，避免留下半成品目录。

### 6.6 `state.rs`

职责：读写 `localgpt-state.json`。

状态结构：

```rust
#[derive(Serialize, Deserialize, Default)]
pub struct LocalGptState {
    pub threads: BTreeMap<String, String>,
}
```

必须提供：

```rust
pub fn load_state() -> anyhow::Result<LocalGptState>;
pub fn save_state(state: &LocalGptState) -> anyhow::Result<()>;
pub fn get_workspace_id(thread_id: &str) -> anyhow::Result<Option<String>>;
pub fn set_thread_mapping(thread_id: &str, workspace_id: &str) -> anyhow::Result<()>;
```

保存要求：

- `data` 目录不存在时创建。
- 写入临时文件：

```text
localgpt-state.json.tmp
```

- 写完后 rename 覆盖：

```text
localgpt-state.json.tmp -> localgpt-state.json
```

- 不保存 requestId。
- 不保存用户输入。

并发要求：

- 至少在进程内用 `Mutex` 包住读改写，避免同时 commit 时覆盖。
- 不做跨进程锁，MVP 不需要。

## 7. Rust bridge 接口

### 7.1 `/localgpt/prepare-thread-start`

输入：

```json
{
  "requestId": "66e79b8f-c020-4731-bc94-fff13ba69cdb",
  "cwd": "D:\\repos\\CodexPlusPlus"
}
```

处理：

```text
1. 校验 requestId 非空。
2. 校验 cwd 非空。
3. 如果 cwd != source_cwd：返回 passthrough。
4. 读取 Codex++ 后端进程环境里的原 PATH；读取失败直接 fail fast，不能创建孤儿 workspace。
5. 生成 workspaceId = localgpt-{uuid}。
6. 调 bootstrap_new_workspace(workspaceId)。
7. 生成 path = venvScripts + ";" + 原 PATH。
8. 返回 rewrite 信息。
```

输出：rewrite

```json
{
  "action": "rewrite",
  "requestId": "66e79b8f-c020-4731-bc94-fff13ba69cdb",
  "workspaceId": "localgpt-8be71464-be84-49c9-a166-37458d61a674",
  "workspace": "D:\\repos\\CodexPlusPlus\\data\\localgpt-8be71464-be84-49c9-a166-37458d61a674",
  "venv": "D:\\repos\\CodexPlusPlus\\data\\localgpt-8be71464-be84-49c9-a166-37458d61a674\\.venv",
  "venvScripts": "D:\\repos\\CodexPlusPlus\\data\\localgpt-8be71464-be84-49c9-a166-37458d61a674\\.venv\\Scripts",
  "path": "D:\\repos\\CodexPlusPlus\\data\\localgpt-8be71464-be84-49c9-a166-37458d61a674\\.venv\\Scripts;...原 PATH..."
}
```

输出：passthrough

```json
{
  "action": "passthrough",
  "reason": "cwd_mismatch"
}
```

### 7.2 `/localgpt/commit-thread-start`

输入：

```json
{
  "threadId": "019ed5af-d10d-7c12-b3c7-cd81b7b1ea44",
  "workspaceId": "localgpt-8be71464-be84-49c9-a166-37458d61a674"
}
```

处理：

```text
1. 校验 threadId。
2. 校验 workspaceId。
3. 校验 workspace 目录存在。
4. 校验 .venv 目录存在。
5. 写入 localgpt-state.json：threads[threadId] = workspaceId。
```

输出：

```json
{
  "status": "ok"
}
```

如果同一个 `threadId` 已经绑定到不同 `workspaceId`，直接 fail fast。
如果同一个 `threadId` 重复绑定到相同 `workspaceId`，可以返回 ok，保持幂等。

### 7.3 `/localgpt/prepare-turn-start`

输入：

```json
{
  "threadId": "019ed5af-d10d-7c12-b3c7-cd81b7b1ea44",
  "cwd": "D:\\repos\\CodexPlusPlus"
}
```

处理：

```text
1. 校验 threadId。
2. 校验 cwd 非空。
3. 从 state 查 threads[threadId]。
4. 如果存在：返回 rewrite 到 workspace，并返回 `VIRTUAL_ENV` / `PATH` 注入需要的路径。
5. 如果不存在且 cwd == source_cwd：fail fast。
6. 如果不存在且 cwd != source_cwd：passthrough。
```

输出：rewrite

```json
{
  "action": "rewrite",
  "threadId": "019ed5af-d10d-7c12-b3c7-cd81b7b1ea44",
  "workspaceId": "localgpt-8be71464-be84-49c9-a166-37458d61a674",
  "cwd": "D:\\repos\\CodexPlusPlus\\data\\localgpt-8be71464-be84-49c9-a166-37458d61a674",
  "venv": "D:\\repos\\CodexPlusPlus\\data\\localgpt-8be71464-be84-49c9-a166-37458d61a674\\.venv",
  "venvScripts": "D:\\repos\\CodexPlusPlus\\data\\localgpt-8be71464-be84-49c9-a166-37458d61a674\\.venv\\Scripts",
  "path": "D:\\repos\\CodexPlusPlus\\data\\localgpt-8be71464-be84-49c9-a166-37458d61a674\\.venv\\Scripts;...原 PATH..."
}
```

输出：passthrough

```json
{
  "action": "passthrough",
  "reason": "cwd_mismatch"
}
```

## 8. Codex++ route 接入

在运行副本的：

```text
build\CodexPlusPlus-localgpt\crates\codex-plus-core\src\routes.rs
```

增加三个 route arm：

```rust
"/localgpt/prepare-thread-start" => localgpt::prepare_thread_start(payload.clone()).await,
"/localgpt/commit-thread-start" => localgpt::commit_thread_start(payload.clone()).await,
"/localgpt/prepare-turn-start" => localgpt::prepare_turn_start(payload.clone()).await,
```

这些函数都返回：

```rust
anyhow::Result<serde_json::Value>
```

不要自己包装假的 error JSON。让现有 route 错误通道处理错误。

`scripts/prepare_副本.py` 需要负责把这三个 route patch 到运行副本。

## 9. renderer 注入层设计

### 9.1 唯一 dispatcher patch

在：

```text
assets\inject\renderer-inject.js
```

保留一个 dispatcher patch，目标仍然是当前已验证的：

```js
const module = await loadCodexAppModule("vscode-api-");
const dispatcher = module.f;
```

要求：

```text
dispatcher.dispatchMessage 必须存在，否则启动失败。
dispatcher.handleMessage 必须存在，否则启动失败。
```

不要动态扫描所有 bundle。不要 retry 猜 dispatcher。

### 9.2 outbound middleware

现有 dispatch middleware 继续使用：

```js
window.__codexPlusRegisterDispatchMiddleware(name, handler)
```

要求 handler 支持返回 Promise。

### 9.3 inbound middleware

新增 inbound middleware 注册入口：

```js
window.__codexPlusRegisterInboundMiddleware(name, handler)
```

包住：

```js
dispatcher.handleMessage(event)
```

执行顺序：

```text
event -> inbound middlewares -> original handleMessage(event)
```

如果 inbound middleware 抛错，直接抛出，不吞掉。

LocalGPT 用 inbound middleware 监听 `mcp-response`，从里面取 `thread/start` 的 response。

## 10. JS hook 详细设计

文件：

```text
localgpt\js\localgpt_hook.js
```

### 10.1 安装前置检查

启动时必须检查：

```js
typeof window.__codexPlusRegisterDispatchMiddleware === "function"
typeof window.__codexPlusRegisterInboundMiddleware === "function"
typeof window.__codexSessionDeleteBridge === "function"
```

缺一个就 throw。

### 10.2 内存 Map

```js
const requestIdToWorkspaceId = new Map();
```

只存在 JS 内存中。

### 10.3 拦截 `thread/start`

匹配：

```js
message.type === "mcp-request" && message.request?.method === "thread/start"
```

或：

```js
message.type === "thread-prewarm-start" && message.request?.method === "thread/start"
```

流程：

```text
1. params = message.request.params。
2. requestId = message.request.id。
3. requestId 缺失则 throw。
4. 调 bridge /localgpt/prepare-thread-start。
5. 如果返回 passthrough：原样返回 message。
6. 如果返回 rewrite：
   requestIdToWorkspaceId.set(requestId, result.workspaceId)
   改 params.cwd = result.workspace
   改 params.workspaceRoots = [result.workspace]，如果原 params 有 workspaceRoots 或当前就是目标项目。
   注入 shell_environment_policy。
7. 返回改写后的 message。
```

注入方式：

```js
const currentConfig = params.config && typeof params.config === "object" ? params.config : {};
const currentSet = currentConfig["shell_environment_policy.set"] && typeof currentConfig["shell_environment_policy.set"] === "object"
  ? currentConfig["shell_environment_policy.set"]
  : {};

nextParams.config = {
  ...currentConfig,
  "shell_environment_policy.inherit": "all",
  "shell_environment_policy.set": {
    ...currentSet,
    VIRTUAL_ENV: result.venv,
    PATH: result.path,
  },
};
```

`result.path` 由 Rust bridge 生成，规则是：

```text
result.venvScripts + ";" + inheritedPath
```

其中 `inheritedPath` 从 Codex++ 后端进程环境读取。Windows 下优先读取 `PATH`，如果为空再读取 `Path`；两者都为空则 fail fast。不要在 JS 里写 `${PATH}` 这种占位符，也不要只设置 `.venv\Scripts` 覆盖掉原 PATH。

### 10.4 监听 `mcp-response`

inbound middleware 从 event 里解析数据。

观察到的结构是：

```js
event.data.type === "mcp-response"
event.data.message 是 JSON 字符串
JSON.parse(event.data.message) 形如 { id, result }
```

处理：

```text
1. 如果 event.data.type != "mcp-response"：放行。
2. 解析 message。
3. responseId = message.id。
4. 如果 requestIdToWorkspaceId 没有 responseId：放行。
5. threadId = message.result.thread.id。
6. 如果 threadId 缺失：throw。
7. workspaceId = requestIdToWorkspaceId.get(responseId)。
8. 调 bridge /localgpt/commit-thread-start。
9. 成功后 requestIdToWorkspaceId.delete(responseId)。
10. 放行 event。
```

注意：只处理内存 Map 命中的 response，避免误处理其他 mcp-response。

### 10.5 拦截 `turn/start`

匹配：

```js
message.type === "mcp-request" && message.request?.method === "turn/start"
```

流程：

```text
1. params = message.request.params。
2. 校验 params.threadId。
3. 调 bridge /localgpt/prepare-turn-start。
4. passthrough：原样返回。
5. rewrite：改 params.cwd，并注入 `VIRTUAL_ENV` / `PATH`。
```

`turn/start` 的 env 注入必须和 `thread/start` 使用同一套 config 形状。

## 11. `prepare_副本.py` 修改点

脚本需要自动把独立模块接入运行副本。

必须做：

1. 拷贝干净上游到：

```text
build\CodexPlusPlus-localgpt
```

2. 删除运行副本 `.git`。

3. 修改运行副本 core Cargo.toml，加入：

```toml
localgpt = { path = "../../../../localgpt" }
```

实际相对路径按当前文件位置计算，不能写错。

4. 修改 workspace members，加入 localgpt 依赖所需项。

5. 修改 `routes.rs`，增加三个 LocalGPT route。

6. 修改 `renderer-inject.js`：

- 建立唯一 dispatcher patch。
- 保留 outbound middleware。
- 新增 inbound middleware。
- 注入 `localgpt::hook_script()`。

7. 每次 patch 前校验目标文本存在。目标文本不匹配就 fail fast，提示上游文件变了。

不要写模糊替换。不要静默跳过。

## 12. 错误处理规则

### Rust

- 所有业务错误返回 `anyhow::Error`。
- route 统一走现有错误通道。
- 不返回伪装的 `{ action: "error" }`。
- 不落盘完整用户输入。

### JS

- bridge 返回 `{ status: "failed", message }` 时 throw 原始 message。
- 未知 action 直接 throw。
- 缺少 request.id / threadId / cwd 直接 throw。
- dispatcher 或 bridge 缺失直接 throw。

## 13. 验证用例

### 13.1 新会话

步骤：

1. 从 `D:\repos\CodexPlusPlus` 新开会话。
2. 输入：

```text
请运行命令打印当前 cwd 和 VIRTUAL_ENV
```

期望：

```text
cwd = D:\repos\CodexPlusPlus\data\localgpt-{uuid}
VIRTUAL_ENV = D:\repos\CodexPlusPlus\data\localgpt-{uuid}\.venv
PATH 前缀 = D:\repos\CodexPlusPlus\data\localgpt-{uuid}\.venv\Scripts
```

状态文件包含：

```json
{
  "threads": {
    "{threadId}": "localgpt-{uuid}"
  }
}
```

### 13.2 同会话后续 turn

继续输入同样命令。

期望：

```text
cwd 仍然是同一个 workspace
VIRTUAL_ENV 仍然是同一个 .venv
PATH 仍然以同一个 .venv\Scripts 开头
```

### 13.3 重启 Codex App

步骤：

1. 关闭 Codex App。
2. 重新打开 Codex App。
3. 让 Codex++ 重新注入 hook。
4. 打开旧会话。
5. 输入同样命令。

期望：

```text
threadId 从 localgpt-state.json 恢复
cwd 仍然是原 workspace
VIRTUAL_ENV 仍然是原 .venv
PATH 仍然以原 .venv\Scripts 开头
```

### 13.4 非目标 cwd

如果 `thread/start` 或 `turn/start` 的 `cwd` 不是：

```text
D:\repos\CodexPlusPlus
```

且没有已绑定 `threadId`，应 passthrough。

### 13.5 映射缺失但 cwd 是源项目

`turn/start` 中：

```text
threadId 未绑定
cwd == D:\repos\CodexPlusPlus
```

必须 fail fast。
不要偷偷创建 workspace。

## 14. 最终实现边界

要做：

- `thread/start` 创建 workspace。
- `thread/start` 注入 `VIRTUAL_ENV`。
- `thread/start` 注入 `PATH = .venv\Scripts;原 PATH`。
- response 后持久化 `threadId -> workspaceId`。
- `turn/start` 根据持久化映射改 `cwd`。
- `turn/start` 根据持久化映射注入 `VIRTUAL_ENV`。
- `turn/start` 根据持久化映射注入 `PATH = .venv\Scripts;原 PATH`。
- App 重启后依靠状态文件恢复旧会话 workspace。

不要做：

- 不做多项目。
- 不做 UI 配置。
- 不修改 Codex CLI wrapper。
- 不修改 launcher 进程环境。
- 不持久化 requestId 中间态。
- 不兼容旧目录名。
