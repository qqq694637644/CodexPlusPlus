# LocalGPT 需要改造的 Codex App 能力清单

本文只记录 **Codex App / Codex++ 注入层需要具备或改造的能力**。

LocalGPT Python 层怎么创建 workspace、`.venv`、`AGENTS.md`、skills，不放在本文展开。

当前结论：

> LocalGPT 不需要改 Codex native 的 Git 行为，也不需要替 Codex 执行 Git。  
> 需要改的是 Codex App 壳层：拦截正常输入提交、判断当前项目是否属于 LocalGPT 项目、调用 bridge、打开新 workspace、新建对话、让 Codex 进入刚创建的 workspace。

---

## 1. 需要改造的能力总览

### A. 拦截正常输入提交并判断是否进入 LocalGPT 流程

目标：

- 不新增 `LocalGPT 新任务` 按钮。
- 用户仍然使用 Codex App 原生输入框。
- 用户在当前项目下输入任务并按 Enter。
- JS 注入层在提交前读取当前项目目录。
- 如果当前项目目录是 LocalGPT 管理范围，就拦截原始提交，改走 LocalGPT bootstrap 流程。
- 如果不是 LocalGPT 项目，就完全放行，保持 Codex App 原生行为。

需要探测：

- Codex App 输入框 DOM 结构。
- 按 Enter 提交时触发的是：
  - form submit；
  - keydown；
  - button click；
  - dispatcher message；
  - 还是组合事件。
- 如何稳定读取输入框当前文本。
- 如何稳定读取当前项目目录。
- 如何判断“当前项目目录是否是我们的项目”。
- 如何在 LocalGPT 命中时阻止原生提交。
- 如何在非 LocalGPT 项目时完全不干扰原生提交。

当前源码证据：

- 已有项目区 DOM 识别逻辑：
  - `sidebarProjectRows()`
  - `projectRowPath(row)`
  - `currentProjectContext()`
- 已有 dispatcher patch 模式：
  - `loadCodexAppModule("setting-storage-")`
  - `dispatcher.dispatchMessage(type, payload)`
- 已观察到与提交相关的消息类型：
  - `start-conversation`
  - `start-turn-for-host`
  - `send-cli-request-for-host`

初步判断：

> 第一版不加 UI 入口。  
> 优先探测“输入框 Enter → dispatcher payload”链路。  
> LocalGPT 的触发条件应该是“当前项目路径命中 LocalGPT 规则”，而不是额外按钮。

---

### B. JS 注入层调用本地 bridge

目标：

- 前端把用户输入传给 Rust bridge。
- Rust bridge 调 Python `bootstrap-project`。
- 返回：

```json
{
  "workspace_path": "D:\\LocalGPT\\workspaces\\localgpt-a1b2c3d4",
  "venv_path": "...\\.venv",
  "agents_path": "...\\AGENTS.md",
  "skills_path": "...\\.agents\\skills",
  "agents_content": "..."
}
```

需要新增 bridge route：

```text
/localgpt/bootstrap-project
```

后续平台能力 route：

```text
/localgpt/platform
/localgpt/sync-artifacts
```

当前源码证据：

- `crates/codex-plus-core/src/routes.rs`
  - `handle_bridge_request(...)`
  - 已有多条本地能力路由：
    - `/settings/get`
    - `/settings/set`
    - `/upstream-worktree/create`
    - `/move-thread-workspace`
    - `/zed-remote/open`
- `assets/inject/renderer-inject.js`
  - 已通过 `window.__codexSessionDeleteBridge(path, payload)` 调 bridge。
  - `sendCodexPlusDiagnostic(...)` 已在用 bridge。

初步判断：

> bridge 能力已经存在，只需要新增 LocalGPT route 和 JS 调用封装。

---

### C. 创建 workspace 后，让 Codex App 打开该 workspace

目标：

- Python 创建空 workspace 后，Codex App 能进入该 workspace。
- 新对话应该以 `workspace_path` 作为项目目录。
- Codex native 后续 shell / git / python 都在该 workspace 里运行。

需要探测：

- Codex App 原生“打开项目 / 进入项目”的消息类型是什么。
- 新对话的 `start-conversation` payload 里 workspace 字段是什么。
- 是否能通过 dispatchMessage 构造打开 workspace。
- 如果不能直接打开，是否可用已有 `/move-thread-workspace` 创建后迁移当前 thread。

当前源码证据：

- `assets/inject/renderer-inject.js` 已经能 patch Codex dispatcher：
  - `loadCodexAppModule("setting-storage-")`
  - 找 `dispatchMessage`
  - 包装 `dispatcher.dispatchMessage(type, payload)`
- 已观察到这些消息类型：
  - `start-conversation`
  - `send-cli-request-for-host`
  - `start-thread-for-host`
  - `start-turn-for-host`
  - `pending-worktree-create`
- 已有 workspace 迁移 route：
  - `routes.rs`：`/move-thread-workspace`
  - JS：`moveSessionToProject(ref, target)`

初步判断：

> 这是最关键探测点。  
> 要先抓一次 Codex App 原生“在某项目中新建对话”的 `start-conversation` payload，再决定怎么注入 `workspace_path`。

---

### D. AGENTS.md / skills 加载确认

目标：

- Codex native 进入 workspace 后能读取：
  - `AGENTS.md`
  - `.agents\skills\...`

需要探测：

- Codex App 是否自动读取 workspace 根目录 `AGENTS.md`。
- workspace 内 `.agents\skills` 是否被当前 Codex 加载。
- 如果 `.agents\skills` 不自动加载，是否需要写入项目 `.codex/config.toml` 或通过现有机制指定 skill 路径。

当前设计：

```text
D:\LocalGPT\workspaces\localgpt-a1b2c3d4\
  .venv\
  .agents\
    skills\
      localgpt-platform\
        SKILL.md
      localgpt-workspace\
        SKILL.md
  AGENTS.md
```

初步判断：

> AGENTS.md 大概率可用；`.agents\skills` 需要实测。  
> 不要在没确认前继续扩展 skill 结构。

---

### E. Platform Gateway 暴露给 Codex 的方式

目标：

- Codex 在 workspace 中需要查 PR / CI / artifact 时，有明确入口。

可能方式：

1. 通过 skill 指令告诉 Codex 调本地 Python CLI：

```powershell
python -m localgpt.cli platform --input-json <path>
```

2. 通过 Codex++ bridge route 给前端用：

```text
/localgpt/platform
```

3. 后续如果需要，再做 MCP。

当前判断：

> 第一版不急着做 MCP。  
> 先让 workspace 内 AGENTS.md / skill 写清楚 CLI 用法，够用。

---

## 2. 当前应该优先探测的顺序

### 第 1 步：探测输入框 Enter 提交链路

状态：已完成第一轮探测。

探测文件：

```text
scripts/probe_codex_dispatcher.py
_dump/localgpt-dispatcher-probe-enter.json
```

探测方式：

- 通过 CDP 注入 dispatcher patch。
- 当前 Codex App 的 dispatcher 来源：

```text
app://-/assets/vscode-api-D4QUNFB4.js#d.getInstance()
```

已观察到的关键链路：

```text
输入框输入文本
  → persisted-atom-update: composer-prompt-drafts-v1
  → thread-prewarm-start
      request.method = "thread/start"
      request.params.cwd = 当前项目目录
  → mcp-request
      request.method = "turn/start"
      request.params.cwd = 当前项目目录
      request.params.input[0].text = 用户输入
  → thread-stream-state-changed
```

本次实测关键字段：

```json
{
  "type": "thread-prewarm-start",
  "request": {
    "method": "thread/start",
    "params": {
      "cwd": "D:\\repos\\CodexPlusPlus"
    }
  }
}
```

```json
{
  "type": "mcp-request",
  "request": {
    "method": "turn/start",
    "params": {
      "cwd": "D:\\repos\\CodexPlusPlus",
      "input": [
        {
          "type": "text",
          "text": "你好测试2\n"
        }
      ],
      "responsesapiClientMetadata": {
        "workspace_kind": "project"
      }
    }
  },
  "hostId": "local"
}
```

结论：

> 当前版本的输入提交链路可以在 dispatcher 层观测。  
> 真正决定执行目录的是 `thread/start` 和 `turn/start` payload 里的 `cwd`。  
> LocalGPT 后续要么在 DOM Enter 阶段提前 bootstrap，再让原生提交使用新 cwd；要么在 dispatcher 层改写 `thread-prewarm-start` / `mcp-request turn/start` 的 `cwd`。

下一步要继续探测：

- `thread-prewarm-start` 和 `mcp-request turn/start` 是否可以安全改写 `cwd`。
- 改写 `cwd` 后 Codex native 是否真的在新 workspace 中执行。
- 如果 dispatcher 层不能异步等待 bootstrap，则需要改在 DOM Enter capture 阶段拦截。

目标：

- 记录用户在原生输入框按 Enter 时触发的 DOM 事件和 dispatcher `type/payload`。
- 特别关注：
  - `start-conversation`
  - `start-turn-for-host`
  - `send-cli-request-for-host`
  - `sourceWorkspaceRoot`
  - `cwd`
  - `workspace`
  - `project`
  - `startingState`

建议方法：

- 在 `renderer-inject.js` 增加临时观测 patch；
- 或在 DevTools Console 手动 patch dispatcher；
- 输出到 console / diagnostics。

验收：

- 能记录一次普通项目输入 Enter 的 payload。
- 能记录一次 LocalGPT 项目输入 Enter 的 payload。
- 能判断拦截点应该在 DOM submit/keydown 还是 dispatcher 层。

---

### 第 2 步：探测如何打开指定 workspace

目标：

- 证明可以让 Codex App 进入某个本地目录。

候选路径：

1. 模拟原生打开项目行为。
2. 构造 dispatcher 消息。
3. 先新建 thread，再调用 `/move-thread-workspace`。

验收：

- Codex App UI 显示新 workspace。
- Codex native 后续命令 cwd 是该 workspace。

---

### 第 3 步：探测 AGENTS.md 是否被加载

目标：

- 在随机 workspace 中写入明显的 `AGENTS.md` 标记。
- 打开 workspace 后让 Codex 回答或执行任务，确认它是否读到。

验收：

- Codex 明确遵循 `AGENTS.md` 中的测试指令。

---

### 第 4 步：探测 `.agents\skills` 是否被加载

目标：

- 在 `.agents\skills\localgpt-workspace\SKILL.md` 写一个可观察的技能说明。
- 看 Codex 是否能发现或遵循。

验收：

- 如果自动加载：保留当前设计。
- 如果不自动加载：不要硬猜，改成只依赖 `AGENTS.md`，或再研究 Codex skill 加载路径。

---

### 第 5 步：探测 bridge 调 Python bootstrap

目标：

- 新增最小 `/localgpt/bootstrap-project` route。
- 先不做完整平台能力，只返回 mock 或最小真实 workspace。

验收：

- JS 能调用 bridge；
- Rust 能调用 Python；
- Python 能创建：
  - workspace；
  - `.venv`；
  - `AGENTS.md`；
  - `.agents\skills`。

---

## 3. 第一阶段最小改造目标

第一阶段只追求这个闭环：

```text
Codex App 原生输入框输入需求并按 Enter
  → JS 判断当前项目路径是否命中 LocalGPT
  → JS 调 /localgpt/bootstrap-project
  → Python 创建 localgpt-xxxxxxxx workspace
  → 写 .venv / AGENTS.md / .agents\skills
  → Codex App 打开该 workspace 的新对话
  → Codex 后续自己执行 git / 测试 / 修改
```

暂不做：

- 自动 clone；
- 自动 fetch；
- 自动 checkout；
- 自动创建业务分支；
- 新增 LocalGPT 按钮；
- 自动发第一条消息；
- 自动创建 PR；
- 自动查 CI。

---

## 4. 已确认可复用的现有能力

### 4.1 JS bridge

现有：

```text
window.__codexSessionDeleteBridge(path, payload)
```

用途：

- 前端调用 Rust 本地能力。

### 4.2 Rust route 分发

现有：

```rust
handle_bridge_request(ctx, path, payload)
```

可新增：

```text
/localgpt/bootstrap-project
/localgpt/platform
/localgpt/sync-artifacts
```

### 4.3 dispatcher patch

现有模式：

```js
const module = await loadCodexAppModule("setting-storage-");
const dispatcherClass = typeof module.v === "function" && String(module.v).includes("dispatchMessage") ? module.v : null;
const dispatcher = dispatcherClass?.getInstance?.();
dispatcher.dispatchMessage = (type, payload) => { ... };
```

用途：

- 可观测或改写 Codex App 内部消息。

### 4.4 项目上下文识别

现有函数：

```js
currentProjectContext()
currentProjectRepoPath()
sidebarProjectRows()
projectContextFromRow(row)
```

用途：

- 可帮助定位当前 Codex App 项目状态。

---

## 5. 当前最大未知点

1. Codex App 如何通过内部消息打开任意本地 workspace。
2. `start-conversation` payload 中 workspace 字段到底叫什么。
3. `AGENTS.md` 在 Codex App 新 workspace 中是否稳定加载。
4. `.agents\skills` 是否会被 Codex 自动加载。
5. 输入提交拦截点应该在 DOM 事件层还是 dispatcher 层。

下一步从第 1 点开始探测。
