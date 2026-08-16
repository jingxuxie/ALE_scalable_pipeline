# Standard prompt for a fresh difficulty-pilot solver

Use this prompt only with a fresh agent context that receives the frozen
participant draft and no author-only material.

```text
You are evaluating a candidate professional task. Work only with the files in
this participant snapshot and the tools explicitly available in its declared
environment.

Complete the task described in TASK.md and place every required deliverable at
the documented paths.

Rules:
- Do not request or use the source paper, source repository, author notes,
  reference solution, hidden evaluator, hidden thresholds, or private inputs.
- Do not search for the task by title, distinctive phrase, file hash, or source
  identity. Follow the benchmark network policy.
- Inspect the supplied workspace and inputs before choosing an approach.
- Use public checks and diagnostics when available.
- You may revise your implementation, method, configuration, or experiments
  within the stated budget.
- Do not fabricate metrics or conclusions. Required claims must be supported by
  artifacts you actually generated.
- Stop when the deliverables are complete or the budget is exhausted.

Keep a concise machine-readable pilot trace at `pilot_trace.json` when the task
permits an extra screening-only file. It should contain:

{
  "strategy_summary": "...",
  "major_decisions": ["..."],
  "iterations": 0,
  "public_checks_run": ["..."],
  "known_failures": ["..."]
}

The trace is screening metadata only and is not part of the scientific score.
When extra files are prohibited, report the same information to the harness
outside the submission directory.
```

## Pilot isolation requirements

The harness, not the solver, must enforce:

- a fresh context for every attempt;
- only the frozen participant snapshot is mounted;
- no conversation history from task authoring;
- no paper, official repository, author, private, or reference files;
- the exact participant network, time, token, compute, and tool policy;
- immutable participant-snapshot and pilot-evaluator hashes;
- captured commands, wall time, output inventory, score, and failure mode.

A pilot result is invalid when the solver received authoring discussion or any
source-derived hint not present in the participant package.
