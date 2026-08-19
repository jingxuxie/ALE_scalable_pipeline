# Fast task-loop templates

Copy these files only when useful. The fast loop intentionally has no required schema system.

Recommended task directory:

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
    fresh_01/output/
  status.json
```

Template mapping:

| Template | Destination |
| --- | --- |
| `TASK.md.template` | `participant/TASK.md` |
| `evaluate.py.template` | `evaluator/evaluate.py` |
| `status.json.template` | `status.json` |

The authoring session writes the task-specific inputs and known-good solution directly.

Typical commands:

```text
python solution/solve.py --input participant/input --output _reference_output
python evaluator/evaluate.py --submission _reference_output
python evaluator/evaluate.py --submission attempts/fresh_01/output
```

A task is retained when the reference passes and one fresh agent fails within the recorded time limit for a substantive reason. Production ALE packaging can be performed later for retained tasks.
