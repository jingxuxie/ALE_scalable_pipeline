# End-to-end fast paper-to-task prompt

Replace the placeholders and paste this once into the **main Codex session running on Windows**. The main session must complete the whole loop itself, including launching fresh Codex runs in WSL.

```text
You are the main Windows Codex session responsible for creating and screening one hard, paper-derived ALE task. Complete the entire loop autonomously. Do not ask me to launch a fresh agent, copy files, grade an attempt, or approve a hardening round.

Inputs:
- Paper: <PAPER_PATH_OR_URL>
- Optional source code: <CODE_PATH_OR_URL_OR_NONE>
- Optional data: <DATA_PATH_OR_URL_OR_NONE>
- Output directory: <OUTPUT_DIRECTORY>

Fresh-agent configuration:
- WSL distro: <WSL_DISTRO_OR_DEFAULT>
- Model: <MODEL_OR_GPT-5.6-SOL>
- Time limit: <SECONDS_OR_360>; never exceed 600 seconds
- Maximum total rounds: <ROUNDS_OR_2>

Use only the fast loop below. Do not use the older V1/V2 authoring pipelines. Do not create hashes, evidence graphs, source manifests, alternative solvers, mutant suites, metamorphic suites, archive checks, long reports, or production ALE packaging.

Create only:

<OUTPUT_DIRECTORY>/
  participant/
    TASK.md
    input/
    software/          # optional
  solution/
    solve.py           # or another small known-good solution
  evaluator/
    evaluate.py
    hidden/            # optional and small
  attempts/
  status.json

The task must be clear and self-contained, but do not turn TASK.md into a line-by-line solution recipe. Prefer debugging/repair, transfer under shift, method selection, optimization under a budget, reproduction plus an extension, experiment design, or a run-inspect-revise workflow. Avoid formula transcription, fully disclosed recurrences, one standard fit/library call, clone-and-run reproduction, and large amounts of repetitive output.

Execute this loop without stopping for user input:

1. SKIM AND DESIGN
   - Spend at most 3-5 minutes identifying one promising workflow.
   - If no promising non-recipe task appears quickly, write status `rejected` and stop.
   - Build one task only.

2. BUILD THE MINIMAL CANDIDATE
   - Create participant/TASK.md and all necessary public files.
   - Create one known-good solution and one quick evaluator.
   - The evaluator must print one JSON object with `passed`, `score`, and `reason` and should finish within 30 seconds.
   - Use reasonable numerical tolerance; do not require exact bytes.

3. CHECK THE REFERENCE
   - Run the known-good solution once and evaluate it once.
   - If it does not pass after one obvious fix, mark `reference_failed` or `rejected` and stop.

4. LAUNCH A FRESH WSL CODEX SESSION YOURSELF
   - Run the repository helper from Windows PowerShell:

     powershell -NoProfile -ExecutionPolicy Bypass -File tools/fast_task_loop/run_fresh_wsl.ps1 `
       -TaskDirectory <OUTPUT_DIRECTORY> `
       -Round <ROUND_NUMBER> `
       -TimeoutSeconds <TIME_LIMIT> `
       -Model <MODEL> `
       [-Distro <WSL_DISTRO>]

   - The helper copies only participant/ into a new temporary WSL workspace and invokes a new non-interactive ephemeral Codex session there.
   - Never copy solution/, evaluator/, the paper, source code, or this authoring conversation into the WSL workspace.
   - Use a new WSL workspace and a new `codex exec --ephemeral` invocation for every round.
   - Do not treat the Codex process exit code as the answer. Grade the produced files.

5. EVALUATE THE FRESH ATTEMPT
   - The helper copies the fresh output to attempts/fresh_NN/output/.
   - Run evaluator/evaluate.py on that directory.
   - Save the evaluator JSON as attempts/fresh_NN/evaluation.json and update status.json.

6. DECIDE OR ITERATE
   - If the fresh attempt is wrong, incomplete, or times out without a passing output, and the failure is not clearly caused by a missing file or contradictory task statement: set status to `pilot_hard_candidate` and stop.
   - If the fresh attempt passes: the task is too easy. Inspect its output and logs, identify the shortcut, and make one structural change. Good changes include interacting faults in a multi-file workspace, a meaningful regime shift, method choice, an ablation/extension, or a required feedback loop. Do not merely add rows, stricter formatting, tighter tolerances, hidden trivia, or more compute.
   - After changing the task, update the known-good solution and evaluator, rerun the reference check, and launch another fresh WSL session automatically.
   - If the fresh run failed only because of an obvious setup/specification problem, fix that problem automatically and rerun. Do not count infrastructure failure as hardness.
   - If the task still passes after the configured maximum rounds, set status to `rejected` with reason `remains_too_easy` and stop.

Keep status.json small. Record the current round, reference result, fresh-agent model/time limit, evaluator result, final status, and one-sentence reason.

At the very end, report only:
- task directory and title;
- number of rounds;
- reference score;
- each fresh-agent score and whether it timed out;
- final status: `pilot_hard_candidate`, `rejected`, or `reference_failed`;
- one sentence explaining why.

Do not pause between proposal, fresh-agent execution, evaluation, and hardening. The only acceptable manual blocker is that the paper/input is inaccessible or WSL Codex is not installed/authenticated.
```
