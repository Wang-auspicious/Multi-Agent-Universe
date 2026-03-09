Summary (local fallback)
- Executor: gemini_cli
- Review: Approved
- Output:
$ gemini "用 gemini_cli 帮我总结当前仓库的主要目录结构"
我将为您梳理当前仓库的主目录结构。首先，我将列出根目录下的文件和文件夹。
我将深入查看 `agent_os` 和 `agents` 目录，以更准确地总结其功能。
我将查看 `Tools` 和 `configs` 目录，以完善对仓库结构的整体把握。
当前仓库 `my_agent_universe` 是一个基于智能体（Agent）的系统框架。以下是其主要目录结构的总结：

### 核心架构
*   **`agent_os/`**: 项目的核心引擎，类似于“智能体操作系统”。包含：
    *   `core/`: 核心逻辑。
    *   `executors/`: 执行器，负责任务运行。
    *   `providers/`: 服务提供者（如 LLM 接口）。
    *   `memory/` & `tools/`: OS 级别的记忆管理和内置工具。
*   **`agents/`**: 具体智能体的定义。
    *   包含 `analysis_agent.py`（分析）、`search_agent.py`（搜索）、`orchestrator.py`（编排）等。
    *   辅助模块如 `agent_log.py` 和 `cost_tracker.py`（成本追踪）。

### 功能组件
*   **`Tools/`**: 智能体可调用的外部工具集，如 `web_search.py`（网页搜索）、`summarizer.py`（总结）。
*   **`configs/` / `config/`**: 系统配置文件，包括模型定义 (`models.yaml`) 和权限控制 (`permissions.yaml`)。
*   **`memory/`**: 存储智能体的长期或短期记忆数据