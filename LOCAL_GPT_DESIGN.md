# LocalGPT 设计文档（GPT-5.5 版）

## 1. 定位

LocalGPT 是 Codex++ 给 Codex App 增加的本地项目入口。

它不是新的聊天 UI，不替代 Codex App，也不替 Codex 执行普通 Git 工作流。

它的目标是：

> 在 Codex App 中一键创建带 8 位随机后缀的本地 workspace，并写入适合 GPT-5.5 接管的会话环境：`.venv`、`AGENTS.md`。

当前主路径是 Gitea，适合私有化部署。GitHub 只是可选 provider。

## 2. 核心原则

1. Codex native / `codex.exe` 才是真正执行命令的地方。
2. AI 自己在 workspace 里执行 `git`、测试、构建、修复和提交。
3. LocalGPT 不封装普通 Git 操作。
4. LocalGPT 不负责 clone/fetch/checkout/branch 这些业务 Git 决策。
5. LocalGPT 只做会话启动前的最小准备：创建 workspace 目录、准备本地环境、写入提示词。
6. PR、CI、workflow、runner、artifact 这类平台 API 能力统一走 Platform Gateway。

一句话：

> LocalGPT 负责把 Codex 放到正确项目现场；Codex 自己干活。

## 3. 用户体验

用户在 Codex App 中点击 LocalGPT / 新建维护任务入口，输入：

```text
实现支付回调重试，完成后提交 ai/pay-callback-retry 分支并创建 PR。
```

LocalGPT 做的事情：

1. 创建一个新的 workspace 目录，目录名追加 8 位随机数。
2. 确保 `.venv` 存在。
3. 写入或更新 `AGENTS.md`。
4. 打开或创建 Codex 新对话。


之后 Codex 自己执行：

```powershell
git status
git fetch
git switch -c ai/pay-callback-retry
git diff
git add
git commit
git push
```

如果需要查 PR、CI、runner、artifact，Codex 调用 LocalGPT Platform Gateway。

## 4. 架构分层

```text
Codex App Chromium 壳
  │
  │  项目入口、LocalGPT 按钮、任务输入、创建 workspace、打开 workspace
  ▼
Codex++ JS 注入层
  │
  │  通过 CDP 修改 renderer 层 UI，并调用本地 bridge
  ▼
Codex++ Rust bridge
  │
  │  只做路由、进程调用、JSON 输入输出、错误返回
  ▼
LocalGPT Python 工具层
  │
  ├─ Project Bootstrapper
  │    创建带 8 位随机数的 workspace，并写入 .venv、AGENTS.md
  │
  └─ Platform Gateway
       统一 Gitea / GitHub 的 PR、CI、workflow、runner、log、artifact 能力

Codex native 执行层
  │
  │  在生成的 workspace 中运行 shell、git、python、测试、构建
  ▼
真实 workspace 目录
```

关键点：

- Chrome/Electron 只是 Codex App 的 UI 壳。
- 真正执行命令和加载项目环境的是 Codex native / `codex.exe`。
- LocalGPT 不要试图把 Codex App “放进 venv”。
- LocalGPT 也不要替 AI 做 Git 编排。
- Rust 不实现 LocalGPT 业务逻辑，只转发给 Python。

## 5. Git 和平台能力边界

### 5.1 直接交给 Codex 执行的本地 Git

```text
git status
git fetch
git diff
git log
git show
git switch
git checkout
git restore
git add
git commit
git push
```

原因：

- Git 是 workspace 内的真实文件系统行为。
- Codex 在当前目录里直接执行最灵活。
- 不需要额外包一层工具去猜 AI 想怎么切分支、怎么对比、怎么提交。

### 5.2 必须统一包裹的平台能力

```text
查询 PR / Issue
创建 PR
更新 PR
评论 PR
查询 CI 状态
查询 workflow run
查询 job
读取 job log / run log
列出 runner
触发 workflow
重跑 workflow / job
列出 artifact
同步 artifact 到 workspace
列出 / 删除 Actions cache
合并 PR
```

原因：

- 这些不是本地 Git 行为，而是 Gitea / GitHub API 行为。
- Gitea 和 GitHub 的 API、字段、分页、认证、artifact 下载方式不同。
- Codex 应该面对统一的 Platform Gateway，而不是直接适配多个平台。

## 6. Project Bootstrapper

Project Bootstrapper 是 Python 实现的最小环境启动器。

它不解析平台、不判断任务类型、不做 Git 编排，也不要求一开始就是 Git 项目。

它只创建一个空的本地 workspace，并写入 Codex 启动所需的环境、`AGENTS.md` 和本地 skills。

workspace 命名规则：

```text
localgpt-<8位随机数>
```

示例：

```text
D:\LocalGPT\workspaces\localgpt-a1b2c3d4
```

8 位随机数使用十六进制字符串，只解决目录冲突和多任务并行问题，不承载业务含义。

输入：

```json
{
  "workspace_root": "D:\\LocalGPT\\workspaces",
  "platform": "gitea",
  "request": "实现支付回调重试，完成后提交 ai/pay-callback-retry 分支并创建 PR。"
}
```

输出：

```json
{
  "workspace_path": "D:\\LocalGPT\\workspaces\\localgpt-a1b2c3d4",
  "venv_path": "D:\\LocalGPT\\workspaces\\localgpt-a1b2c3d4\\.venv",
  "agents_path": "D:\\LocalGPT\\workspaces\\localgpt-a1b2c3d4\\AGENTS.md",
  "skills_path": "D:\\LocalGPT\\workspaces\\localgpt-a1b2c3d4\\.agents\\skills",
  "agents_content": "..."
}
```

它只负责：

1. 创建带 8 位随机数后缀的空 workspace 目录。
2. 创建 `.venv`。
3. 写入 `AGENTS.md`。
4. 复制 LocalGPT skills 到 `.agents\skills`。
5. 返回 `workspace_path` 和 `agents_content`。

workspace 内最终结构：

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

skill 原始模板不放在 workspace 里维护。原始文件放在 LocalGPT Python 包的模板目录中：

```text
localgpt\
  templates\
    AGENTS.md
    skills\
      localgpt-platform\
        SKILL.md
      localgpt-workspace\
        SKILL.md
```

Bootstrapper 每次创建 workspace 时，把 `localgpt/templates/skills/*` 原样复制到当前 workspace 的 `.agents\skills\`。

这样做的边界：

- `localgpt/templates/` 是源文件。
- `workspace\.agents\skills\` 是运行时副本。
- 修改通用 skill 时改模板目录。
- 单个 workspace 需要临时调整时，只改该 workspace 的副本。

它不负责：

- 判断 repo / PR 任务类型。
- 查询 PR。
- 查询 CI。
- clone / fetch。
- 创建 branch。
- checkout PR。
- commit / push。

这些都交给 Codex 在 workspace 里根据用户需求自己做。

## 7. Platform Gateway

Platform Gateway 用 Python 实现。默认 provider 是 Gitea，GitHub 是可选实现。

Provider 接口：

```text
get_pull_request(repo_ref, number)
list_pull_requests(repo_ref, filters)
create_pull_request(repo_ref, head, base, title, body)
update_pull_request(repo_ref, number, fields)
comment_pull_request(repo_ref, number, body)
merge_pull_request(repo_ref, number, method)

query_ci_status(repo_ref, ref_or_pr)
list_workflows(repo_ref)
dispatch_workflow(repo_ref, workflow_id, ref, inputs)
get_run(repo_ref, run_id)
list_runs(repo_ref, filters)
list_jobs(repo_ref, run_id)
get_job_log(repo_ref, job_id)
get_run_log(repo_ref, run_id)
rerun_workflow_run(repo_ref, run_id)
rerun_workflow_job(repo_ref, job_id)
cancel_workflow_run(repo_ref, run_id)

list_artifacts(repo_ref, run_id)
sync_artifacts_to_workspace(repo_ref, run_id, workspace_path)
list_runners(repo_ref)
list_caches(repo_ref, filters)
delete_cache(repo_ref, cache_id)
```

`repo_ref` 优先由 Codex 显式传入。

最小实现顺序：

1. `query_ci_status`
2. `list_jobs`
3. `get_job_log`
4. `list_artifacts`
5. `sync_artifacts_to_workspace`
6. `get_pull_request`
7. `create_pull_request`
8. `comment_pull_request`
9. `dispatch_workflow`
10. `rerun_workflow_run`
11. `rerun_workflow_job`

## 8. AGENTS.md 生成策略

每个 workspace 写入一个项目级 `AGENTS.md`，让 Codex 进入目录后自动获得 LocalGPT 规则。

推荐模板：

```markdown
# LocalGPT workspace 指令

## 目标

你正在一个真实 Git workspace 中工作。请根据用户任务完成代码维护，并把结果推进到可验证状态。

## 当前任务

<用户原始需求>

## 工作方式

- 直接在当前目录阅读、修改、测试代码。
- 普通 Git 操作直接使用本地 `git`。
- 需要 PR、CI、workflow、runner、artifact、日志时使用 LocalGPT Platform Gateway。
- Python 命令优先使用 `./.venv/Scripts/python.exe`。
- 不需要激活虚拟环境。

## 成功标准

- 修改最小且可 review。
- 已运行最相关验证；无法运行时说明原因。
- 如涉及 PR/CI，最终说明真实 PR、commit、CI、artifact 状态。
- 不编造测试、提交、PR、CI 或 artifact 结果。

## 输出风格

简洁、直接、先给结论，再给证据和下一步。
```

## 9. 给 GPT-5.5 的 AGENTS.md 结构

LocalGPT 生成的 `AGENTS.md` 不要写成很长的流程脚本。

推荐结构：

```markdown
你要在当前 workspace 完成这个代码维护任务。

## 用户需求

<原始需求>

## 当前环境

- workspace：<workspace_path，目录名包含 8 位随机数>
- 平台：gitea
- Python：优先使用 ./.venv/Scripts/python.exe

## 工作方式

- 普通 Git 操作直接在当前目录执行。
- 如果需要分支、diff、commit、push，由你自己用 git 完成。
- 如果需要查询 PR、CI、workflow、runner、artifact 或日志，使用 LocalGPT Platform Gateway。
- artifact 同步到 `.gpt-artifacts/runs/<run_id>/` 后再分析。

## 成功标准

- 定位并完成用户需求。
- 修改保持最小、可审计。
- 运行最相关验证。
- 如需要，push 工作分支并创建或更新 PR。
- 如涉及 CI，查询真实 CI 状态；失败时读取相关日志或 artifact。

## 停止条件

当你已经完成修改、验证、提交/PR/CI 状态说明，或遇到缺少凭据、权限、必要输入导致无法继续时，停止并给出结论。
```

## 10. Codex App UI 集成

Codex++ JS 注入层新增 LocalGPT 入口：

- 在项目目录项下增加 `LocalGPT 新任务`。
- 新建任务弹窗默认平台为 `gitea`。
- 输入自然语言需求。
- 创建带 8 位随机数后缀的 `workspace_path`。
- 调用 Rust bridge 的 `/localgpt/bootstrap-project`。
- 拿到 workspace_path。
- 打开 Codex App 新对话。

UI 层只做交互，不做业务逻辑。

## 11. Rust bridge 集成

Rust 只做轻量 bridge，不做 LocalGPT 业务。

新增 routes：

```text
/localgpt/bootstrap-project
/localgpt/platform
/localgpt/sync-artifacts
```

Rust route 行为：

1. 接收 JSON。
2. 调用 Python CLI。
3. 设置 cwd 和超时。
4. 读取 stdout JSON。
5. 原样返回结构化结果。
6. stderr 和 exit code 作为错误返回。

不要在 Rust 里实现 Git workflow。

## 12. Python 模块规划

建议目录：

```text
localgpt/
  __init__.py
  cli.py
  bootstrap_project.py
  venv.py
  agents_md.py
  skills.py
  state.py
  templates/
    AGENTS.md
    skills/
      localgpt-platform/
        SKILL.md
      localgpt-workspace/
        SKILL.md
  platform/
    __init__.py
    base.py
    gitea.py
    github.py
    models.py
```

CLI 示例：

```powershell
python -m localgpt.cli bootstrap-project --input-json <path>
python -m localgpt.cli platform --input-json <path>
```

LocalGPT Python 只输出 JSON，方便 Rust bridge 和调试脚本复用。

## 13. 主要流程

### 13.1 普通代码维护任务

```text
用户在 Codex App 点击 LocalGPT 新任务
  → 输入需求
  → bootstrap-project
  → 创建带 8 位随机数后缀的空 workspace
  → 创建 .venv / AGENTS.md
  → Codex App 打开新对话
  → Codex 自己执行 git、测试、修改、提交、push
```

### 13.2 CI 失败任务

```text
用户在当前 workspace 输入“修 CI”需求
  → Codex 通过 Platform Gateway 查询 CI
  → 定位失败 run/job
  → 读取 job log
  → 如需要，同步 artifact 到 .gpt-artifacts/runs/<run_id>/
  → Codex 在 workspace 修复
  → Codex 本地验证
  → Codex git commit / push
  → Codex 再查 CI
```

### 13.3 PR 任务

```text
用户输入 PR 编号或 PR URL
  → Codex 自己判断需要 fetch、checkout、diff 还是新建分支
  → PR 元数据和评论通过 Platform Gateway 查
  → 本地 Git 操作由 Codex 自己执行
```

## 14. 阶段目标

### 第一阶段：项目会话启动

- 在 Codex App 中出现 LocalGPT 新任务入口。
- Python `bootstrap-project` 跑通。
- 创建带 8 位随机数后缀的空 workspace。
- 创建 `.venv`。
- 写入 `AGENTS.md`。
- Codex App 能打开该 workspace，并通过 `AGENTS.md` 加载任务说明。
### 第二阶段：Platform Gateway

- Gitea provider 优先实现。
- 查询 CI run/job。
- 读取 log。
- 同步 artifact。
- 查询 PR。
- 创建 / 评论 PR。
- 触发 / 重跑 workflow。
- 查询 runner。

### 第三阶段：体验增强

- 重新打开最近 workspace。
- 在每次创建新 workspace 前，检测超过 24 小时未改动的子项目 workspace，后续再扩展清理。
- 展示当前 workspace 的 repo、branch、PR、CI 状态。

## 15. 明确不做

当前不做：

- 新网页聊天 UI。
- 替代 Codex App 的 diff、terminal、thread、Git UI。
- 用 Rust 实现 LocalGPT 业务逻辑。
- 包装普通本地 Git 操作。
- 自动 clone / fetch / checkout / branch 编排。
- 企业级权限审批系统。
- 操作风险分级。
- 私有 CI/CD runner 部署。
- 复杂任务编排 DSL。
- 强制固定 workflow。

LocalGPT 的价值不是控制 Codex 每一步怎么做，而是给 Codex 一个正确、轻量、上下文完整的 workspace 会话入口。
















