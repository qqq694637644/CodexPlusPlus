# LocalGPT 最小 MVP 集成方案

## 1. 目标

第一版只做一件事：

> 在 Codex App 发出 `mcp-request / turn/start` 时，命中指定源目录后，把 `cwd` 重写到 `data/threadId`。

不做完整平台，不做复杂抽象，不做 Python 主实现。

---

## 2. MVP 范围

本版只包含：

1. hook `type === "mcp-request"`
2. 只处理 `request.method === "turn/start"`
3. 读取 `threadId`、`cwd`、`input`
4. 当 `cwd == D:\repos\CodexPlusPlus` 时：
   - 计算目标目录 `D:\repos\CodexPlusPlus\data\threadId`
   - 若目录不存在则创建
   - 写入 `AGENTS.md`
   - 复制 `.agents\skills`
   - 将 `payload.request.params.cwd` 改写为目标目录
5. 当 `cwd != D:\repos\CodexPlusPlus` 时直接放行

---

## 3. 明确不做

当前不做：

- 不拦 `turn`
- 不拦 `thread/start`
- 不做 DOM 事件 hook
- 不做新 UI 入口
- 不做 `.venv`
- 不做 Git 包装
- 不做 PR / CI / artifact gateway
- 不做复杂状态持久化
- 不做 DLL
- 不做 Python 主实现

---

## 4. 实现方式

采用：

> 独立 crate + 最小接线

目标是尽量不和上游大面积耦合。

目录：

```text
build/CodexPlusPlus-localgpt/
  crates/


localgpt/
  Cargo.toml
  src/
    lib.rs
    bridge.rs
    bootstrap.rs
    paths.rs
    templates.rs
  js/
    turn_start_hook.js
  templates/
    AGENTS.md
    skills/
      ...
```

说明：

- `localgpt/` 是仓库根目录下的独立第三方模块
- 不放进 `build/CodexPlusPlus-localgpt/crates/`
- 目标是尽量不污染上游镜像目录；运行副本由脚本生成，方便后续持续同步 upstream

---

## 5. 职责拆分

### 5.1 JS hook

文件：

```text
localgpt/js/turn_start_hook.js
```

职责：

1. patch 发送请求的 dispatcher
2. 只拦 `mcp-request / turn/start`
3. 读取：
   - `threadId`
   - `cwd`
   - `input`
4. 调用 Rust bridge：

```text
/localgpt/prepare-turn-start
```

5. 根据 bridge 返回结果：
   - `passthrough`：原样放行
   - `rewrite`：改写 `payload.request.params.cwd`
   - `error`：直接取消本次请求

JS 不负责：

- 拼目录规则
- 写文件
- 创建 workspace
- 复制 skills

---

### 5.2 Rust bridge

文件：

```text
localgpt/src/bridge.rs
```

职责：

接收：

```json
{
  "threadId": "019ed3d7-2a4a-7e02-b92a-2ddb75c9c2ec",
  "cwd": "D:\\repos\\CodexPlusPlus",
  "input": []
}
```

返回：

#### 放行

```json
{
  "action": "passthrough"
}
```

#### 改写

```json
{
  "action": "rewrite",
  "cwd": "D:\\repos\\CodexPlusPlus\\data\\{threadId}"
}
```

---

### 5.3 bootstrap

文件：

```text
localgpt/src/bootstrap.rs
```

职责：

1. 判断是否命中源目录
2. 根据 `{threadId}` 计算固定 workspace
3. 目标目录不存在时创建
4. 写入 `AGENTS.md`
5. 复制 `.agents\skills`
6. 做最小存在性校验

---

## 6. 目录规则

固定规则：

```text
SOURCE_CWD     = D:\repos\CodexPlusPlus
WORKSPACE_ROOT = D:\repos\CodexPlusPlus\data
WORKSPACE_PATH = D:\repos\CodexPlusPlus\data\{threadId}
```

规则含义：

- 同一个 `{threadId}` 永远映射到同一个目录
- 不额外维护映射表
- 不依赖内存状态
- 重启后仍然稳定

---

## 7. 与 Codex++ 运行副本的最小集成点

只改三处：

### 7.1 增加 path dependency

修改：

```text
build/CodexPlusPlus-localgpt/crates/codex-plus-core/Cargo.toml
```

增加：

```toml
localgpt = { path = "../../../../localgpt" }
```

说明：

- 不把 `localgpt/` 放进副本 workspace
- 不改副本根 `Cargo.toml` 的 members
- 只让 `codex-plus-core` 通过相对路径依赖它
- 这样运行副本可重复生成，upstream 镜像不需要保留这些改动

### 7.2 增加一个 bridge route

修改：

```text
build/CodexPlusPlus-localgpt/crates/codex-plus-core/src/routes.rs
```

在现有 route 分发中新增：

```text
/localgpt/prepare-turn-start
```

然后把处理转给 `localgpt` crate。

形式：

```rust
"/localgpt/prepare-turn-start" => localgpt::handle_bridge(payload.clone()).await,
```

### 7.3 追加 hook 脚本

修改：

```text
build/CodexPlusPlus-localgpt/crates/codex-plus-core/src/assets.rs
```

在现有注入脚本输出时，额外追加：

```text
localgpt turn_start_hook.js
```

避免把 LocalGPT 逻辑硬塞进现有大脚本。

形式：

```rust
format!(
    "...现有注入内容...\n{}",
    localgpt::hook_script()
)
```

---

## 7.4 运行副本最小改动清单

最终只动这几个运行副本文件：

```text
build/CodexPlusPlus-localgpt/crates/codex-plus-core/Cargo.toml
build/CodexPlusPlus-localgpt/crates/codex-plus-core/src/routes.rs
build/CodexPlusPlus-localgpt/crates/codex-plus-core/src/assets.rs
```

其余 LocalGPT 代码全部留在：

```text
localgpt/
```

这就是本方案最核心的“低耦合”和“不污染 upstream 镜像”要求。

---

## 8. 请求处理流程

```text
用户发送消息
  → Codex App 发出 mcp-request / turn/start
  → LocalGPT JS hook 拦截
  → 读取 threadId / cwd / input
  → 调 /localgpt/prepare-turn-start
  → Rust 判断是否命中 SOURCE_CWD
      → 否：返回 passthrough
      → 是：
          计算 threadId
          若不存在则 bootstrap
          返回 rewrite + 新 cwd
  → JS 改写 payload.request.params.cwd
  → 放行原请求
```

---

## 9. Fail Fast 规则

必须 fail fast：

### 9.1 缺少 `threadId`

直接取消本次 `turn/start`。

### 9.2 workspace 创建失败

直接取消本次 `turn/start`。

### 9.3 `AGENTS.md` 或 `.agents\skills` 准备失败

直接取消本次 `turn/start`。

### 9.4 bridge 异常

直接取消本次 `turn/start`。

不允许：

- 回退原目录继续执行
- 静默吞错
- 猜测性补救

---

## 10. MVP 验收标准

满足以下条件即通过：

1. 当 `cwd == D:\repos\CodexPlusPlus` 时：
   - 本次 `turn/start` 被改写到
     `D:\repos\CodexPlusPlus\data\{threadId}`
2. 同一 `threadId` 后续再次请求时：
   - 仍然改写到同一目录
3. 当 `cwd != D:\repos\CodexPlusPlus` 时：
   - 请求完全放行
4. workspace 不存在时：
   - 能自动创建最小目录结构
5. bootstrap 失败时：
   - 不回退原目录执行
   - 而是直接终止本次请求

---

## 11. 后续扩展

等 MVP 稳定后，再考虑：

- `.venv`
- workspace 模板更多内容
- 可配置源目录
- 多项目规则
- 独立 helper 进程
- Platform Gateway

当前一律不做。

