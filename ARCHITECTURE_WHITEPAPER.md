## 系统技术架构白皮书（草案）

> 面向：本地多智能体 IDE 工作台（Agent Universe Workbench）  
> 对标：VS Code / Cursor 交互体验 + OpenClaw 多智能体能力 + Gemini CLI 终端控制

---

### 1. 总体目标与原则

- **目标**：在单一本地仓库内，提供「类 VS Code Workbench + Cursor 多模态助手 + OpenClaw Agent OS」的统一工作台，用于日常编码、调试与自动化协作。
- **边界**：所有读写、终端操作均限定在当前 `repo` 路径内，参考源码仓（`vscode-main`、`openclaw-main` 等）仅作为**只读档案**。
- **安全原则**：
  - 禁止静默删除（所有删除必须走 UI 确认，并可通过补丁历史回滚）。
  - Shell 命令必须通过白名单与危险 token 过滤（见 `PermissionPolicy`）。
  - 路径访问必须限制在仓库内部，并屏蔽 `.env`、密钥文件等敏感片段。

---

### 2. 交互层架构（Refined UI/UX）

#### 2.1 Workbench Shell 总览

- 实现文件位于：`agent_os/apps/workbench.py` + `agent_os/apps/workbench_static/*`。
- 前端结构：
  - **Explorer 面板**：树形文件管理 + 过滤输入框 + 是否包含参考源码（`includeArchives`）。
  - **Editor 面板**：多标签页文本编辑器 + 行号栏 + 下方面板（Diff / Snippet Patch / Patch History）。
  - **Assistant 面板**：右侧多标签（Agent / Task / Trace），承载聊天流、任务摘要、事件轨迹。
  - **状态栏**：显示文件/任务/会话数量。
- 交互特点（对标 Cursor / VS Code）：
  - 左树 + 中编辑器 + 右侧 Chat 的三栏布局，支持多标签切换。
  - 内置 diff 视图与 snippet 级 patch 应用，结合服务器端补丁历史支持一键回滚。
  - Chat 区绑定后端任务与事件流，可从聊天消息跳转到对应任务与 trace。

#### 2.2 Explorer 与文件索引

- 服务器端 `iter_workspace_files`（`workbench.py`）：
  - 基于 `os.walk` 扫描仓库，应用 `IGNORED_DIRS` / `IGNORED_PREFIXES` 过滤。
  - `REFERENCE_ARCHIVES = {"codex-main", "gemini-cli-main", "void-main", "vscode-main", "openclaw-main"}`：
    - 默认 **不** 展示这些参考源码目录。
    - 勾选「Include reference source archives」时，才纳入文件树。
- 客户端：
  - `/api/explorer` 返回扁平文件列表，由前端构建为树形结构。
  - `fileQuery` 支持前端轻量过滤（子串匹配），适配大仓库本地使用。

> **对标 VS Code Explorer**：  
> 通过服务器端 `iter_workspace_files` + 前端树化渲染，实现「大仓树懒加载 + 可选包含参考源码」的轻量索引方案，为后续更深的语义索引（向量检索）预留空间。

#### 2.3 编辑流与 Diff / Snippet / History

- 当前 Editor 交互三层能力：
  - **Buffer Diff**：`/api/file/diff` 使用 `difflib.unified_diff` 对比当前 buffer 与上次保存内容。
  - **Snippet Patch**：`/api/file/patch` 接收 `find/replace/count`，进行局部替换。
  - **Patch History + Rollback**：
    - `agent_os/tools/files.py` 中 `_record_patch_history` 将每次 write/patch 记录为 JSONL（before/after/diff）。
    - `/api/file/history` 与 `/api/file/rollback` 提供可视化历史与一键回滚。

> **对标 Cursor Inline 编辑 / Diff rail**：  
> 通过统一的 patch 历史管道，Diff/Snippet/History 三者共享同一数据源，使任何变更都可以在 UI 中追踪并回滚。

---

### 3. Agentic Backend（多智能体执行内核）

#### 3.1 AgentRuntime 与执行路径

- 核心类：`agent_os/core/runtime.py` 中的 `AgentRuntime`。
- 关键职责：
  - 绑定当前 `repo_path`，管理 `data/runs/*` 目录（事件流 + artifacts + summary）。
  - 初始化 Memory 层（`MemoryStore`、`RepoMemory`、`TaskMemory`、`FailureMemory`）。
  - 基于 `PermissionPolicy` 和 `SafeShell` 管理本地 Shell 执行。
  - 构造多执行器映射：`collab_agent` / `local_agent` / `shell` / `codex_cli` / `gemini_cli` / `claude_cli`。
  - 协调 `RouterAgent`、`CoderAgent`、`ReviewerAgent`、`SummarizerAgent`，构成完整多轮执行链。

#### 3.2 事件总线与可观测性

- 事件定义：`agent_os/core/events.py` 中的 `Event` / `EventTypes`：
  - `task.created` / `task.assigned` / `agent.started`
  - `plan.created` / `work_item.started` / `work_item.completed`
  - `command.started` / `command.finished` / `diff.generated`
  - `review.failed` / `task.completed`
- 事件流处理：
  - `AgentRuntime._emit` 将事件同时发布到：
    - 内存总线 `EventBus`。
    - `MemoryStore.events` 表（持久化）。
    - 可选外部回调 `_event_hook`（用于 UI 实时更新）。
  - `agent_os/apps/workbench.py` 中的 `/api/task/<task_id>` 将事件打包到前端「Trace」视图。

> **对标 OpenClaw 会话与心跳机制**：  
> 当前系统已经具备任务级事件时间线与失败记忆（`FailureMemory`），可平滑扩展为「心跳任务」「自动运维任务」，并可接入 OpenClaw 的会话与路由策略。

#### 3.3 MemoryStore 与多维记忆

- `agent_os/memory/store.py`：
  - 统一的 SQLite 存储层，表覆盖任务、事件、仓库记忆、失败记忆、聊天消息、任务 checkpoint。
  - `dashboard_snapshot` 聚合 tasks/chats/failures/checkpoints，为全局仪表盘提供数据源。
- 上层记忆类型：
  - `RepoMemory`：仓库级 Key-Value 记忆（例如最近目标、索引状态）。
  - `TaskMemory`：任务级状态追踪（在其他模块中使用）。
  - `FailureMemory`：失败与修复尝试记录，可用于后续「反思/避免重复错误」能力。

> **对标 OpenClaw 工作区 AGENTS/HEARTBEAT/MEMORY**：  
> 这里选择「结构化 SQLite + 文件补丁历史」而非纯 markdown，侧重于**可回放**与**可索引**，更适合 IDE 内多任务并发。

---

### 4. 参考架构映射：VS Code & OpenClaw

#### 4.1 VS Code Workbench 映射

- 参考目录：`vscode-main/test/smoke/src/areas/*` 与 `test/unit/*`。
- 映射关系：
  - VS Code 的 `Workbench` 与 `Activity Bar / Side Bar / Editor / Panel` → 本项目的 `app-shell` + `activity-bar` + 三栏布局。
  - VS Code Terminal 区的自动化测试（如 `terminal.test.ts`）→ 后续在本项目中引入「终端集成 + 错误监听 + Fix it」流。
  - Explorer 的 lazy loading / 多根工作区支持 → 当前通过 `iter_workspace_files` + `REFERENCE_ARCHIVES` 提供基础能力，可按需扩展为多 Root。

#### 4.2 OpenClaw 多智能体映射

- 关键文件：
  - `openclaw-main/src/infra/openclaw-root.ts`：负责在多种运行环境中解析 OpenClaw 包根路径。
  - `openclaw-main/src/agents/openclaw-tools.ts`：将浏览器、Canvas、Cron、Sessions、Subagents、WebSearch/WebFetch、PDF/图像等工具组合为统一工具集。
  - `openclaw-main/docs/start/openclaw.md`：详解心跳、会话、工作区与安全策略。
- 能力迁移思路：
  - **工具拼装模式**：借鉴 `createOpenClawTools` 的「核心工具 + 插件工具」模式，为 `AgentRuntime` 的工具集留出插件注入点（例如后续接入浏览器控制、媒体工具）。
  - **Session 与 Channel 概念**：在当前 Workbench 中，`chat_id` 与 `task_id` 已经承载类似概念，可继续绑定「终端会话」「测试会话」等逻辑分组。
  - **Heartbeat 心跳**：结合 `MemoryStore.dashboard_snapshot` 与 RepoMemory，可在本地仓库层面实现「定时项目健康体检」任务（例如定期运行测试/格式化/安全扫描）。

---

### 5. 终端共生与自动修复（设计蓝图）

> 本节为本地 IDE 终端 + 多智能体联动的目标设计，后续阶段在 `workbench` 中逐步落地。

#### 5.1 安全终端通道

- 基于现有 `SafeShell`（`agent_os/tools/shell.py`）：
  - 所有命令必须通过 `PermissionPolicy` 校验：
    - 命令白名单：`{"git", "python", "pytest", "node", "npm", "pnpm"}`。
    - 危险 token 屏蔽：`rm -rf`、`del /f`、`format`、`shutdown`、`reboot`、`deploy`、`push` 等。
  - 所有命令在 `repo_path` 下运行，并记录耗时与退出码。
- 设计中的 Workbench 终端视图：
  - 用户输入命令 → 后端 `SafeShell.run` 执行 → 前端终端区域展示 stdout/stderr。
  - 当退出码非 0 或输出中包含「Traceback / Error / FAILED」等关键词时，UI 自动高亮错误并弹出「Fix it」建议按钮。

#### 5.2 “Fix it” 建议与多智能体协作

- 触发条件：
  - 终端命令失败（非 0 退出码，或关键错误模式匹配）。
- 行为：
  - Workbench 自动组装一条任务提示词，包含：
    - 运行的命令与工作目录。
    - 终端输出（按长度截断，避免过长）。
  - 将该提示词预填入右侧 Assistant 的输入框，并高亮「Run Task」或「Fix it」按钮，由用户显式确认后再启动 `collab_agent`/`local_agent`。
- 多智能体协作路径：
  1. RouterAgent 选择合适执行器（本地 / CLI / Shell）。
  2. CoderAgent 读取错误堆栈、相关源码片段，生成补丁（通过 `write_file`/`patch_file`）。
  3. ReviewerAgent 校验补丁是否真正解决错误，必要时给出回滚/改进建议。
  4. SummarizerAgent 输出人类可读的修复说明（同步到 Chat 与 Task Summary）。

> **设计约束**：  
> 终端命令的执行始终是「显式命令 + 白名单校验」，修复流程则是「AI 自动规划 + 用户点击确认」的二阶段模式，避免静默执行高风险操作。

---

### 6. 文件安全锁与回滚机制（设计蓝图）

#### 6.1 写入与补丁历史

- 所有写入路径均通过 `write_file` / `patch_file`：
  - 写入前读取旧内容，写入后与新内容做 unified diff。
  - 将 `before/after/diff` 作为 JSONL 记录到 `data/patch_history/<path>.jsonl`。
  - 为每个 patch 分配唯一 `patch_id`，用于 UI 回溯与 `rollback`。

#### 6.2 安全删除策略

- 新增 `delete_file` 工具（设计）：
  - 在删除前读取完整文件内容，并记录一条 `operation=delete` 的补丁历史（`before=原文件内容, after=""`）。
  - 调用 `Path.unlink()` 实际删除文件。
  - 通过现有 `rollback_patch` 即可从历史记录中恢复被删文件（`before` 内容）。
- Workbench UI 行为：
  - Explorer 或 Editor 中点击「Delete」前，弹出确认对话框（包含路径）。
  - 只有在用户显式确认后才调用后端 `/api/file/delete`。
  - 删除后：
    - 关闭对应 Editor 标签。
    - 刷新 Explorer。
    - 提示「文件已删除，可在 History 视图中通过 rollback 恢复」。

> 该机制确保任何删除都具备「可审计 + 可恢复」的属性，符合「禁止静默删除」「一键撤销」的项目基准。

---

### 7. 路线图对齐与后续扩展

- **阶段一：深度调研**
  - 已梳理：VS Code Workbench 交互模式、OpenClaw 工具编排与安全模型。
  - 已对齐：本地 Workbench 的 Explorer / Editor / Assistant 三层架构与事件/记忆系统。
- **阶段二：安全骨架搭建**
  - 在现有 Workbench 上补齐：
    - 文件安全锁（删除确认 + 可回滚）。
    - 参考源码只读策略与 UI 标识（archives 视图）。
- **阶段三：Agent 注入与联调**
  - 将终端视图与 `SafeShell` / `AgentRuntime` 打通，形成：
    - 显式终端执行 → 错误监听 → Fix it 提示 → 多智能体修复。
  - 为后续扩展 OpenClaw 插件工具（WebChat、外部通道）保留统一接入点。

本白皮书作为当前架构的「快照」与「设计蓝图」，后续每个阶段落地时，可在本文件中追加实现状态与决策记录，形成完整的技术演进时间线。

