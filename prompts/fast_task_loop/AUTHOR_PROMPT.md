# Fast paper-to-task author prompt

Replace the placeholders and paste the text below into one Codex authoring session. The prompt is self-contained; the longer guide is optional background.

```text
You are creating one hard, paper-derived ALE task candidate.

Inputs:
- Paper: <PAPER_PATH_OR_URL>
- Optional source code: <CODE_PATH_OR_URL_OR_NONE>
- Optional data: <DATA_PATH_OR_URL_OR_NONE>
- Output directory: <OUTPUT_DIRECTORY>

Follow only this fast workflow. Do not read or use the older V1/V2 authoring pipelines unless I explicitly ask.

Goal:
Create one participant task, one known-good solution, and one quick evaluator. The participant task should be intrinsically difficult for a fresh strong agent, not difficult because of missing information, formatting, or compute.

Target active authoring time for the first round: 20-30 minutes.
- paper/code skim: 5 minutes maximum;
- task design and public inputs: 8 minutes maximum;
- known-good solution and evaluator: 10 minutes maximum;
- reference run and quick fixes: 5 minutes maximum.

If the paper does not quickly yield a promising non-recipe task, reject it and move on. Do not spend an hour forcing a candidate.

Prefer tasks involving one or more of:
- debugging or repairing a multi-file scientific pipeline;
- adapting a method to a shifted regime;
- method selection or optimization under a budget;
- reproduction followed by a nontrivial ablation or extension;
- experiment design and evidence reconciliation;
- a run-inspect-revise feedback loop.

Avoid:
- formula transcription;
- fully specified recurrences or algorithms;
- one standard least-squares/optimizer/library call;
- clone-and-run reproduction;
- generating many rows from one rule;
- long output-format specifications that reveal the solution.

Create exactly this minimal structure:

<OUTPUT_DIRECTORY>/
  participant/
    TASK.md
    input/
    software/          # optional
  solution/
    solve.py           # or another simple executable solution
  evaluator/
    evaluate.py
    hidden/            # optional and small
  attempts/
  status.json

Requirements:
1. The fresh agent will receive only participant/.
2. TASK.md must clearly state the objective, files, required outputs, environment, and constraints.
3. Do not disclose the full reference algorithm unless there is no method freedom. If full disclosure makes the task a direct implementation exercise, reject it or redesign it.
4. The known-good solution must pass the evaluator.
5. The evaluator must finish quickly, use reasonable numerical tolerance, and print a small JSON result containing passed, score, and reason.
6. The reference solution should normally run in under two minutes and evaluation in under 30 seconds.
7. Do not create hashes, source manifests, evidence maps, workflow YAML, alternative solvers, mutant suites, metamorphic suites, license reports, archive checks, or long verification reports.
8. Do not claim the task is hard yet. Set status to ready_for_fresh_agent after the reference passes.

Before finishing:
- run the known-good solution once;
- run the evaluator once;
- fix only obvious task/evaluator problems;
- report the exact commands;
- briefly explain what consequential decision, diagnosis, or feedback loop should make the task difficult.

Stop after producing a working candidate. Start the fresh-agent session separately and move to the next paper instead of waiting for it. Do not spend time on production packaging.
```
