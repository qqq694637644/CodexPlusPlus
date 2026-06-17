# LocalGPT Codex App 改造重点

结论：

> 第一版只拦截 `mcp-request / turn/start`。  
> 对于 `D:\repos\CodexPlusPlus` 这个原项目：
>
> - 如果当前 `threadId` 还没有对应 workspace，就创建固定目录：
>   `D:\repos\CodexPlusPlus\data\{threadId}`
> - 如果当前 `threadId` 已经有对应 workspace，就继续把 `cwd` 改到这个固定目录

不新增入口，不改原生 UI，不接管 Git。

---

## 1. 最终链路

```text
用户在原生输入框输入任务并按 Enter
  → Codex App 发出 mcp-request / turn/start
  → JS 注入层读取 threadId / cwd / input
  → 如果 cwd 不是 D:\repos\CodexPlusPlus
       直接放行
  → 如果 cwd 是 D:\repos\CodexPlusPlus
       计算 workspace_path = D:\repos\CodexPlusPlus\data\{threadId}
       若 workspace 不存在：
         调用 bridge/bootstrap 创建该目录并写入 AGENTS.md / .agents\skills
       payload.request.params.cwd = workspace_path
       放行原始 dispatchMessage
```

失败策略：

```text
workspace 创建失败
  → 取消本次 turn/start
  → 不允许回退到旧 cwd 执行

workspace 理论上应存在但实际不存在
  → 取消本次 turn/start
  → 不允许回退到旧 cwd 执行
```

---

## 2. 为什么这样做

已验证：

- `turn/start.params.cwd` 决定 Codex native 的真实工作目录。
- `turn/start.params.input` 里有完整用户输入。
- `turn/start.params.threadId` 在同一会话内稳定，可作为 workspace 键。
- 重启 Codex App 后，同一会话的 `threadId` 仍可保持不变。
- 但 `cwd` 不会自动记住之前改写后的 workspace，后续请求仍可能回到原始项目目录。
- 只改 `turn/start.cwd`，目标 workspace 下的 `AGENTS.md` 和 `.agents\skills` 会被加载。
- 只取消 `thread-prewarm-start` 不够，它只是预热。

所以：

> 第一版不做复杂状态机，不猜“第一次输入”还是“继续输入”。  
> 只要 `turn/start` 的 `threadId` 已经能确定 workspace，就始终强制改写到这个固定目录。

---

## 3. 核心规则

设：

```text
SOURCE_CWD   = D:\repos\CodexPlusPlus
WORKSPACE_ROOT = D:\repos\CodexPlusPlus\data
WORKSPACE_PATH = D:\repos\CodexPlusPlus\data\{threadId}
```

规则：

```text
1. 只处理 type = "mcp-request" 且 request.method = "turn/start"
2. 读取 threadId / cwd / input
3. 若 cwd != SOURCE_CWD：
     直接放行
4. 若 cwd == SOURCE_CWD：
     用 threadId 计算固定目录 data\{threadId}
     若目录不存在：
       创建并 bootstrap
     将 payload.request.params.cwd 改成该固定目录
     放行
5. 若后续同一 threadId 再次请求，即使 incoming cwd 又回到 SOURCE_CWD：
     仍然改回 {threadId}
```

这等价于：

```text
threadId 决定唯一 workspace
同一个 threadId 永远落到同一个 workspace
```

---

## 4. 需要改的代码能力

### 4.1 JS 注入层

位置：

```text
assets/inject/renderer-inject.js
```

新增能力：

```text
patch dispatcher.dispatchMessage
捕获 type = "mcp-request"
确认 request.method = "turn/start"
读取 request.params.threadId
读取 request.params.cwd
若 cwd 命中 SOURCE_CWD：
  计算固定 workspace 路径
  如目录不存在则 await bridge bootstrap
  改写 request.params.cwd
失败时取消 turn/start
```

核心伪代码：

```js
const SOURCE_CWD = "D:\\repos\\CodexPlusPlus";
const WORKSPACE_ROOT = "D:\\repos\\CodexPlusPlus\\data";

function workspacePathForThread(threadId) {
  return `${WORKSPACE_ROOT}\\${threadId}`;
}

if (type === "mcp-request" && payload?.request?.method === "turn/start") {
  const params = payload.request?.params || {};
  const threadId = params.threadId || "";
  const cwd = params.cwd || "";
  const input = params.input || [];

  if (!threadId) {
    throw new Error("turn/start 缺少 threadId");
  }

  if (cwd !== SOURCE_CWD) {
    return originalDispatchMessage(type, payload);
  }

  const workspacePath = workspacePathForThread(threadId);
  const result = await window.__codexSessionDeleteBridge(
    "/localgpt/prepare-turn-start",
    {
      threadId,
      cwd,
      input,
    }
  );

  if (result?.action !== "rewrite" || !result.cwd) {
    throw new Error("LocalGPT bridge 未返回 rewrite");
  }

  payload.request.params.cwd = result.cwd;
  return originalDispatchMessage(type, payload);
}
```

注意：

- 必须 `await` 完成后再放行。
- 不能先放行，再后台补 workspace。
- `threadId` 缺失直接 fail fast。
- bridge 失败就不要调用原始 `dispatchMessage`。
- 不能因为 bootstrap 失败而回退原目录继续执行。

---

### 4.2 Rust bridge

位置：

```text
crates/codex-plus-core/src/routes.rs
```

新增 route：

```text
/localgpt/prepare-turn-start
```

职责：

```text
接收 threadId / cwd / input
确认 workspacePath 是否存在
不存在则创建 workspace
存在则只做最小校验，不覆盖
返回 passthrough 或 rewrite
```

最小返回：

```json
{
  "action": "rewrite",
  "threadId": "019ed3d7-2a4a-7e02-b92a-2ddb75c9c2ec",
  "cwd": "D:\\repos\\CodexPlusPlus\\data\\019ed3d7-2a4a-7e02-b92a-2ddb75c9c2ec"
}
```

---

### 4.3 Python bootstrap

Python 只负责准备环境：

```text
创建固定目录 data\{threadId}
写 AGENTS.md
复制 .agents\skills
返回 JSON
```

不负责：

```text
Git 操作
PR 操作
CI 操作
任务编排
线程判断
```

固定目录示例：

```text
D:\repos\CodexPlusPlus\data\019ed3d7-2a4a-7e02-b92a-2ddb75c9c2ec
```

---

## 5. 探测证据

### 5.1 原生提交 payload

```json
{
  "type": "mcp-request",
  "request": {
    "method": "turn/start",
    "params": {
      "threadId": "019ed3d7-2a4a-7e02-b92a-2ddb75c9c2ec",
      "cwd": "D:\\repos\\CodexPlusPlus",
      "input": [
        {
          "type": "text",
          "text": "用户输入内容\n"
        }
      ]
    }
  },
  "hostId": "local"
}
```

### 5.2 一次改写、后续只观察的验证结果

验证结果：

```text
第一次 turn/start：
  original cwd = D:\repos\CodexPlusPlus
  next cwd     = D:\repos\CodexPlusPlus\data\testworkspace

后续同一 threadId：
  有一次 incoming cwd 已经变成 testworkspace
  但再后面又回到了 D:\repos\CodexPlusPlus
```

说明：

```text
第一次改写后，后续 cwd 不稳定。
不能假设 Codex App 会永久继承第一次改写后的 cwd。
```

### 5.3 重启后的验证结果

验证结果：

```text
重启 Codex App 后：
  threadId 不变
  cwd 又恢复为 D:\repos\CodexPlusPlus
```

说明：

```text
threadId 可以作为稳定键
cwd 不能作为持久状态来源
```

---

## 6. 第一版不做

```text
不新增 LocalGPT 入口
不拦 DOM Enter
不模拟打开项目
不做 prompt.md / context.json / task.json
不用 git worktree
不做 Git 包装层
不做自动 clone / fetch / checkout
不做自动 PR / CI
不做复杂会话状态机
不靠用户输入文本判断新旧线程
```

---

## 7. 第一版验收标准

用户在原项目下输入任务后：

```text
如果该 threadId 首次出现：
  在 data 下创建 {threadId}
  本次 turn 的 cwd 改到该目录

如果该 threadId 再次出现：
  即使 incoming cwd 还是 D:\repos\CodexPlusPlus
  也会继续被改回 {threadId}

Codex 回答当前目录是 {threadId}
AGENTS.md 已加载
.agents\skills 已加载
```

失败验收：

```text
workspace 缺失或创建失败时
不会回退原目录执行
而是直接取消本次 turn/start
```
