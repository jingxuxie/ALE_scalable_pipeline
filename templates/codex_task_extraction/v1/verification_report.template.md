# Verification report: <task ID>

## Decision

- Status: `<status>`
- Provisional difficulty: `structurally_hard_candidate`
- Frontier-agent calibration: `<not run / summary>`
- Blocking issues: `<none or list>`

## 1. Source and provenance

- Paper/version:
- Official code repository and commit:
- Dataset/version:
- Licenses:
- Source hashes:
- Paper/code/data conflicts:
- Grounded workflow evidence:

## 2. Target leaf and workflow boundary

- Target claim/result leaf:
- Why it is scientifically meaningful:
- Included participant operations:
- Intermediate private-rubric artifacts:
- Public boundary:
- Private evaluation boundary:
- Derivation type:

## 3. Specification closure

| Solution-critical decision | Disclosed | Inferable | Method-agnostic | Invalid hidden dependency | Evidence |
| --- | ---: | ---: | ---: | ---: | --- |
|  |  |  |  |  |  |

All rows closed: `<yes/no>`

### Paper-blind specification review

- Reviewer/context:
- Source access confirmed absent:
- Task restatement:
- Missing definitions or files identified:
- Intended method freedom understood:
- Material ambiguities resolved:
- Status:

## 4. Intrinsic difficulty audit

- Meaningful operation count:
- Dependency depth:
- Branch count:
- Tools:
- Required artifacts:
- Independent challenge sources:
- Expected human workflow and effort:
- Why the task is not a one-formula, clone-and-run, or formatting task:

### Shortcut attempts

| Shortcut/baseline | Command | Result | Why it passes/fails |
| --- | --- | --- | --- |
|  |  |  |  |

## 5. Privileged oracle run

- Command:
- Environment:
- Source-only information used:
- Runtime:
- Peak memory:
- Output inventory:
- Evaluator score:
- Status:

## 6. Clean-room public-input reference run

Confirm that the solve environment contained only participant-visible assets
and declared dependencies.

- Clean-room construction:
- Solver command:
- Network policy:
- Runtime:
- Peak memory:
- Output inventory:
- Evaluator metrics:
- Total score:
- Status:
- Hidden access audit:

## 7. Alternative valid implementation

- Algorithmic independence:
- Command:
- Metrics and score:
- Status:
- If unavailable, justification:

## 8. Tolerance calibration

For every numeric comparison, document scale, conditioning, repeated-run
variation, alternative-implementation disagreement, and final absolute/relative
tolerance.

| Metric | Reference variation | Absolute tolerance | Relative tolerance | Justification |
| --- | ---: | ---: | ---: | --- |
|  |  |  |  |  |

For stochastic tasks:

- Hidden seed/instance count:
- Aggregation:
- Confidence/variance rule:
- Baseline-relative rule:
- Reference distribution:

## 9. Mutant results

| Mutant | Category | Expected | Observed score | Pass/fail | Notes |
| --- | --- | --- | ---: | --- | --- |
|  |  |  |  |  |  |

Mutation categories covered:

## 10. Metamorphic and invariant tests

| Test | Expected relation | Observed | Status |
| --- | --- | --- | --- |
|  |  |  |  |

## 11. Evaluator robustness

- Repeated deterministic runs:
- Malformed output:
- Partial output:
- NaN/Inf:
- Oversized output:
- Stale cached output:
- Fabricated self-reported metrics:
- Hard-coded public examples:
- Private-file access:
- Network access:
- Symlink/path traversal:
- Executable submission isolation:

## 12. Hidden-instance validity

- Generator:
- Varying factors:
- Scientific invariants preserved:
- Reference behavior over generated instances:
- Public review instances retired:
- Private seed policy:

## 13. Participant package audit

- Paper/source identifiers removed:
- Task semantics remain complete:
- Inputs sufficient:
- Output contract clear:
- Public success criteria clear:
- Environment reproducible:
- No private artifacts included:

## 14. Commands to reproduce verification

```text
python tasks/<task_slug>/scripts/verify.py
```

Additional commands:

```text
<commands>
```

## 15. Remaining risks and next actions

- Scientific review:
- Engineering review:
- ALE integration:
- Frontier-agent calibration:
- Other:
