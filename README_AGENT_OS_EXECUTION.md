# Agent OS Execution State

## Goal
Turn this repository into a clean local-first multi-agent workspace that can collaborate on real project tasks.

## Current Main Architecture
- `Planner`: breaks a goal into work items
- `Coder`: reads/writes files and runs safe repo commands
- `Writer`: produces docs, explanations, and polished text
- `Reviewer`: reviews outputs and closes the loop
- `collab_agent`: orchestrates the shared board across those roles

## Active Main Path
Use `collab_agent` as the default executor.

## Current Status
Completed:
- removed the old parallel system split (`agents/`, `Tools/`, old search flow) from the main path
- unified runtime around `agent_os/`
- added shared collaboration board models
- added `PlannerAgent` and `WriterAgent`
- added `CollaborativeExecutor`
- made `local_agent` a compatibility alias to the collaborative executor
- updated CLI and dashboard to default toward `collab_agent`
- dashboard now hides collaboration trace by default and keeps the result view clean
- dashboard now shows result-first chat cards with artifact files, diff panels, file previews, and folded collaboration traces
- same-chat conversation memory now flows into planner and executor prompts so references like "this file" can use recent turns
- added local Star Office launcher: `python main.py --star-office`
- added Star Office progress watcher: `python -m agent_os.apps.ui_bridge <task_id> --watch`
- made `shell` explicit-command only
- fixed Gemini provider healthcheck/model failover
- added patch/diff editing (`apply_patch` / `patch_file`) to the main collaborative loop
- added verified final answers constrained to successful tool artifacts
- upgraded the collaborative loop into a state graph with one repair cycle
- layered strong-model reasoning/finalization onto DeepSeek while keeping worker steps fast
- tests passing

Remaining next-step ideas:
- websocket/live dashboard streaming instead of rerun updates
- richer long-term workspace memory

## Validation Commands
```bash
python main.py --healthcheck --repo .
python main.py --chat --repo . --executor collab_agent --strict-executor
python main.py --dashboard
python main.py --star-office
python -m agent_os.apps.ui_bridge <task_id> --watch
python -m pytest -q
```

## Progress Report Format
- `Step`
- `Done`
- `Next`
- `Blocker`
