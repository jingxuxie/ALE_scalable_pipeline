# Fast task-loop templates

The fast loop uses one Windows authoring session and automatically launches fresh Codex attempts in WSL. No manual handoff is required.

Minimal task directory:

```text
<task>/
  participant/
    TASK.md
    input/
    software/          # optional
  solution/
    solve.py
  evaluator/
    evaluate.py
    hidden/            # optional
  attempts/
  status.json
```

Template mapping:

| Template | Destination |
| --- | --- |
| `TASK.md.template` | `participant/TASK.md` |
| `evaluate.py.template` | `evaluator/evaluate.py` |
| `status.json.template` | `status.json` |

The authoring session writes task-specific inputs and the known-good solution directly. It then runs:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File tools/fast_task_loop/run_fresh_wsl.ps1 `
  -TaskDirectory <task> `
  -Round 1 `
  -TimeoutSeconds 360 `
  -Model gpt-5.6-sol
```

The helper copies only `participant/` to a new WSL workspace, launches an ephemeral fresh Codex run, and copies the resulting `output/` to `attempts/fresh_01/output/`. The Windows authoring session then runs the task-specific evaluator and either keeps the task or revises it automatically.

Use `prompts/fast_task_loop/AUTHOR_PROMPT.md` as the single initial prompt.
