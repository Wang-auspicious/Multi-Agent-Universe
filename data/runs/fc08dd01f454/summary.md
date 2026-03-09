README.md 的内容如下：

# Personal Coding Workflow Agent OS

MVP implemented in `agent_os/` with:
- Router -> Coder -> Reviewer -> Summarizer pipeline
- Structured task and event model
- Shell executor + Codex/Gemini/Claude executor stubs
- SQLite memory (`data/agent_os.db`)
- CLI runner and Streamlit dashboard
- Star Office UI bridge (`agent_os/apps/ui_bridge.py`)

## Quick start

```bash
python main.py "Run project tests and summarize results"
python main.py --dashboard
```

## Bridge to Star Office

```bash
python -m agent_os.apps.ui_bridge <task_id>
```