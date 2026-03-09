README.md 的内容如下：

# Multi-Agent Project Workspace

A local-first multi-agent coding workspace for a single repository.

## What It Does
The system is centered on a collaborative execution path:
- `Planner` breaks a natural-language goal into work items
- `Coder` inspects and modifies repo files with local tools
- `Writer` drafts docs, explanations, and user-facing text
- `Reviewer` checks whether outputs match the goal and flags risks

All of this runs inside the current repository boundary.

## Main Path
Recommended executor: `collab_agent`

It supports:
- natural-language project tasks
- reading local files
- writing files inside the repo
- searching code
- running safe shell commands
- returning a final answer after multi-agent collaboration

## Quick Start
```bash
python main.py --healthcheck --repo .
python main.py --chat --repo . --executor collab_agent --strict-executor
python main.py "请分析当前项目结构并给出一个 README 重写计划" --repo . --executor collab_agent --strict-executor
python main.py --dashboard
python main.py --star-office
```

## Dashboard
- fixed to `collab_agent`
- result-first layout
- collaboration trace collapsed by default
- cleaner editorial visual style

## Star Office UI
A local launcher is now available:
```bash
python main.py --star-office
```
This starts the bundled Star Office backend on `http://127.0.0.1:19000`.

You can also sync task progress into Star Office state:
```bash
python -m agent_os.apps.ui_bridge <task_id>
python -m agent_os.apps.ui_bridge <task_id> --watch
```

## Project Structure
- `agent_os/`: main runtime, agents, executors, tools, memory, dashboard
- `configs/`: model and permission config
- `tests/`: test suite
- `scripts/`: helper scripts
- `Star-Office-UI-1.0.0/`: bundled visual office shell

## Key Design Principles
- one orchestrator shell, multiple role agents
- local tools are controlled by the app, not by the model directly
- model handles planning and reasoning
- repo access stays inside the workspace boundary
- keep project structure clean and easy to extend

## Current Default Roles
- `Planner`
- `Coder`
- `Writer`
- `Reviewer`

## Notes
- `shell` is now explicit-command only; it is no longer used as fake natural-language execution
- external CLI executors (`codex_cli`, `gemini_cli`, `claude_cli`) are optional and depend on each machine's installation/login state