# Fresh-agent prompt used by the WSL runner

The Windows authoring session pipes this prompt into a new ephemeral `codex exec` process. The fresh process receives only a copied `participant/` directory.

```text
You are in an isolated task workspace and have a strict external time limit. Work autonomously until the task is complete or the process is stopped.

Read TASK.md and inspect the provided input/ and software/ files. Produce the requested deliverables under output/ exactly as required by the task.

You do not have the source paper, author solution, evaluator, hidden cases, or authoring conversation. Do not search outside this workspace for them and do not ask the user questions.

Use the available tools actively. Run and inspect your work. Prioritize a complete, correct submission over explanation. Your final message should be brief; the files under output/ are the submission.
```
