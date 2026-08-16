# Private robustness probes

This directory contains deliberately invalid submissions used to verify that
the evaluator fails closed. It is private evaluator material and must never be
copied into the participant package.

`build_probes.py` deterministically materializes each submission under
`cases/<probe-id>/output/analyze.py`. Every generated submission has the exact
public inventory, except that its behavior or source size deliberately violates
one evaluator boundary. The manifest records source hashes and the expected
failure reason.

The suite covers malformed source and CSV, NaN and infinity, missing and extra
artifacts, oversized source and runtime output, private-path reads, input
mutation, output-directory escape, forbidden network/process imports, and
dynamic execution. The programs do not contact a network or launch a process:
the relevant security probes merely request a denied capability and are stopped
by the audit hook.

From the task root, run:

```text
python -B private/probes/build_probes.py
python -B private/probes/run_probes.py
```

`run_probes.py` invokes the real grader, requires score `0.0` plus a hard-gate
failure for every probe, checks the expected diagnostic fragment, and verifies
that protected grader, suite, and hidden-input files did not change.
