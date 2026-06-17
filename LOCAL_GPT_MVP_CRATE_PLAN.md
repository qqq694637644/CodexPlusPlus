# LocalGPT MVP 方案

## 目标

只做一件事：拦截 Codex App 的 `mcp-request / turn/start`，当请求 `cwd` 等于固定源目录时，把本次请求的 `cwd` 改写到独立线程工作目录。

```text
SOURCE_CWD      = D:\repos\CodexPlusPlus
WORKSPACE_ROOT  = D:\repos\CodexPlusPlus\data
WORKSPACE_PATH  = D:\repos\CodexPlusPlus\data\{threadId}
TEMPLATE_ROOT   = D:\repos\CodexPlusPlus\templates
```

## 当前不做

- 不拦 `turn`
- 不拦 `thread/start`
- 不做 UI
- 不做多项目配置
- 不做运行时配置
- 不兼容旧模板路径 `localgpt/templates`
- 不静默补救半成品 workspace

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
    templates.rs
  js/
    turn_start_hook.js

templates/
  AGENTS.md
  skills/
    localgpt-workspace/
      SKILL.md

scripts/
  prepare_副本.py

build/CodexPlusPlus-localgpt/
  # 自动生成的运行副本
```

## 路径配置

`localgpt/config.json` 写死业务路径，并通过 `include_str!` 编译进二进制：

```json
{
  "source_cwd": "D:\\repos\\CodexPlusPlus",
  "workspace_root": "D:\\repos\\CodexPlusPlus\\data"
}
```

修改 `localgpt/config.json` 后必须重新编译。

模板不编译进二进制；创建新 workspace 时运行时读取：

```text
D:\repos\CodexPlusPlus\templates\AGENTS.md
D:\repos\CodexPlusPlus\templates\skills
```

修改模板后不需要重新编译。

## 请求流程

```text
Codex App dispatchMessage
  -> LocalGPT JS middleware
  -> 只处理 type == "mcp-request" 且 request.method == "turn/start"
  -> 调 /localgpt/prepare-turn-start
  -> Rust bridge 校验 threadId / cwd
  -> cwd 不等于 SOURCE_CWD：passthrough
  -> cwd 等于 SOURCE_CWD：确保 data\{threadId} 存在
  -> JS 把 request.params.cwd 改成 data\{threadId}
```

## workspace 初始化规则

新 workspace 使用事务式初始化：

```text
1. 校验 templates\AGENTS.md 是非空文件
2. 校验 templates\skills 是目录
3. 创建临时目录 data\.{threadId}.localgpt-tmp
4. 复制 AGENTS.md
5. 递归复制 templates\skills 到 .agents\skills
6. 校验临时目录至少包含 AGENTS.md 和 .agents\skills
7. rename 临时目录为 data\{threadId}
```

实际临时目录名没有空格：

```text
D:\repos\CodexPlusPlus\data\.{threadId}.localgpt-tmp
```

如果发现临时目录已经存在，直接失败，要求人工处理；不自动覆盖、不自动补救。

已有 workspace 只做最小校验：

```text
AGENTS.md 是文件
.agents\skills 是目录
```

已有 workspace 不覆盖、不补文件、不检查具体 skill 文件。

## 运行副本接线

`prepare_副本.py` 从 `upstream/CodexPlusPlus` 生成 `build/CodexPlusPlus-localgpt`，并只做最小字符串替换。

接线点：

```text
build/CodexPlusPlus-localgpt/crates/codex-plus-core/Cargo.toml
build/CodexPlusPlus-localgpt/Cargo.lock
build/CodexPlusPlus-localgpt/crates/codex-plus-core/src/routes.rs
build/CodexPlusPlus-localgpt/crates/codex-plus-core/src/assets.rs
build/CodexPlusPlus-localgpt/assets/inject/renderer-inject.js
build/CodexPlusPlus-localgpt/crates/codex-plus-core/tests/model_catalog.rs
```

其中 `renderer-inject.js` 建立唯一 dispatch middleware 管线，LocalGPT 只注册 `localgpt-turn-start` middleware。

当前 Codex App dispatcher 明确来自：

```text
vscode-api-*.js 的 module.f
```

找不到该导出时直接失败并记录日志。

## Fail Fast 规则

以下情况直接失败并取消本次 `turn/start`：

- 缺少 `threadId`
- `threadId` 非法
- 缺少 `cwd`
- 模板目录缺失
- workspace 初始化失败
- 发现残留临时初始化目录
- bridge 返回失败
- dispatcher 接线失败

不允许回退到原 `cwd` 继续执行。

## 验证命令

```powershell
python -m py_compile .\scripts\prepare_副本.py
python .\scripts\prepare_副本.py
node --check .\localgpt\js\turn_start_hook.js
node --check .\build\CodexPlusPlus-localgpt\assets\inject\renderer-inject.js
```

本机当前没有 `cargo` 时，不在本机做 Rust 编译；交给 GitHub Actions 编译 artifact。
