# Offline end-to-end orchestration fixture

This fixture exercises paper triage, source locking, evidence mapping,
reduction, workflow synthesis, candidate mining, generic protocol validation,
dynamic publication audit, and atomic project output without an LLM API.

From the repository root:

```powershell
paper2ale orchestrate examples/orchestration/manifest.json `
  --replay examples/orchestration/replay.json
```

Manifest-relative paths are resolved against `examples/orchestration/`, so the
command writes `examples/orchestration/generated/project.json`; that directory
is intentionally ignored by Git. The JSON receipt should report an `eligible`
paper, one closed candidate, and `publication_ready_candidate`. The replay
contains four content-keyed responses: map, reduce, workflow synthesis, and
final project synthesis.

The source claims that held-out affine predictions are independently
checkable. Because the manifest attests that a deterministic synthetic oracle
is possible, the default policy permits the paper even though it has no public
code or data. Changing a source byte, prompt, schema, capability, or stage
input changes the corresponding request ID, so a stale replay fails closed.

For a real paper, replace the source and metadata, add local code/data under
`assets`, and use a structured command adapter in place of `--replay`. Assets
can ground evidence immediately; a task that consumes their raw files also
needs a reviewed asset-backed compiler capability or custom family. Set
`"release": true` only when the command should require publication readiness
and produce release packages via `--build-out`.
