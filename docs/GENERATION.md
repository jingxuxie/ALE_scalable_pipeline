# Provider adapters and the one-shot trust boundary

Paper2ALE v0.3 has one supported end-to-end generation path:

```powershell
paper2ale orchestrate manifests/my-paper.json `
  --replay replays/my-paper.jsonl `
  --asset-cache .paper2ale/assets
```

`orchestrate` resolves and locks local inputs, applies evidence-backed paper
triage, performs bounded map/reduce extraction, validates Workflow IR v2,
mines and triages candidates, constructs workflow bindings locally, and only
then asks a provider for a project proposal. See
[ORCHESTRATION.md](ORCHESTRATION.md).

The `generate` command is retained as a lower-level compatibility surface, but
it cannot establish the trusted workflow/candidate binding required by a
task-bearing project. A normal CLI invocation therefore fails closed before
provider completion and directs the operator to `orchestrate`; its `--build`
and `--publish` flags cannot bypass that gate.

Library callers may call `generate_project(...)` with
`trusted_workflow_bindings={task_id: binding}` when those bindings were
constructed by trusted local code. A provider may not supply or rewrite
`workflow_binding`, and it may propose only a family with a reviewed candidate
validator. Fixed authored-only HNN families remain available to reviewed
project files, not to one-shot model proposals. `require_tasks=False` exists
for controlled empty-project fixtures and migrations; it is not a task
generation path.

## Pin source metadata

Each local one-shot source has a separate strict JSON metadata object. Required
fields are `id`, `kind`, `uri`, `version`, `license`, and `visibility`.
`citation`, `retrieved_at`, and an expected `sha256` are optional. Unknown
fields, duplicate JSON keys, non-finite numbers, local absolute-path values,
and `file://` URIs are rejected.

```json
{
  "id": "source.hnn.paper",
  "kind": "paper",
  "uri": "https://arxiv.org/pdf/1906.01563",
  "version": "arXiv:1906.01563; exact local bytes pinned by sha256",
  "license": "operator-verified source license",
  "visibility": "author",
  "sha256": "<64 lowercase hexadecimal characters>",
  "citation": "Greydanus, Dzamba, and Yosinski. Hamiltonian Neural Networks."
}
```

When `sha256` is supplied, ingestion verifies it. Otherwise Paper2ALE computes
and pins the digest. Source paths and `--metadata` options pair positionally;
the normalized bundle is then sorted by source ID. Local paths are not copied
into provider messages or portable project data.

## PDF and text ingestion

Non-PDF sources must be nonempty UTF-8 text without NUL bytes. They receive
deterministic `lines:start-end` locators. PDF detection uses the suffix and PDF
header; `pypdf` produces `page:number` locators. Encrypted, malformed,
image-only, binary-looking, and over-limit inputs fail rather than being
silently OCRed or truncated.

The one-shot request records normalized evidence and extractor identity.
End-to-end orchestration additionally records a
`paper2ale.source-extraction/v1` lock for each source: raw SHA-256, media type,
byte count, extractor identity, aggregate extraction hash, and every chunk's
locator, text hash, and character count. These locks are included in the
orchestration receipt and final synthesis context without local paths.

Default one-shot limits are 64 MiB per source, 128 MiB total source bytes,
2,000,000 extracted characters per source, 4,000,000 extracted characters in
total, 1,000 PDF pages, and 20,000 characters per evidence chunk. CLI controls
are:

```text
--max-source-mb
--max-total-source-mb
--max-evidence-chars
--max-total-evidence-chars
--max-pdf-pages
--chunk-chars
```

All limits reject; none are truncation targets.

## Completion providers

No LLM API is mandatory. Both orchestration and the lower-level generation API
use the provider-neutral `CompletionProvider.complete(request)` interface.

`ReplayProvider` reads exact request-keyed JSON or JSONL responses and is fully
offline. `CommandProvider` invokes an operator-owned argv vector with
`shell=False`, writes one normalized request to standard input, and reads one
bounded response envelope from standard output. It can wrap a local model or a
hosted API client.

```powershell
paper2ale orchestrate manifests/my-paper.json `
  --command python `
  --command-arg provider_adapter.py `
  --asset-cache .paper2ale/assets
```

Adapter arguments beginning with a dash use
`--command-arg=--adapter-flag`. `--command-cwd` sets the adapter working
directory. Provider output is structured data and is never executed.

The adapter returns a bounded envelope:

```json
{
  "data": {"schema_version": "<stage-specific schema>"},
  "finish_reason": "stop",
  "usage": {"input_tokens": 1000, "output_tokens": 500}
}
```

The `data` object above is abbreviated. It must satisfy the complete strict
schema attached to that request. Adapter stderr is suppressed from portable
receipts and errors.

Replay JSON maps each normalized idempotency key to its response object. JSONL
uses one record per request:

```json
{"idempotency_key":"map-request_<digest>","data":{"schema_version":"paper2ale.evidence-map/v1","unit_id":"<bound-unit-id>","findings":[]}}
```

This schema is abbreviated. Real stage data must satisfy all required fields
and bounds. A changed normalized locator or text, prompt, output schema,
parameter, workflow batch, or capability catalog changes the relevant key. An
extractor implementation/version change alone does not necessarily change a
key when the normalized locators and text remain byte-identical; the exact
extractor still remains visible in the extraction lock and receipt.

## Workflow IR v2 and trusted bindings

Workflow artifacts use explicit materialization origins:

- `asset` requires an exact `asset_ref` for a resolved snapshot file;
- `trusted_generator` requires a registered `capability_ref`;
- `participant` requires a participant producer operation;
- `trusted_evaluator` requires a trusted-evaluator producer operation;
- `external` is not a self-contained participant input.

Direct input/reference evidence derived from an asset must cite the exact
`(asset_id, relative_path)` implied by the evidence. Closure validation checks
origins, producer authority, references, cycles, outputs, and required
evaluator independence. Workflow authority labels remain descriptive; they do
not install executable code.

After candidate mining, trusted local code persists a canonical
`paper2ale.workflow-binding/v1` object that binds the closed workflow, mined
candidate, and selected family. Its content-derived `binding_id` is rechecked
by the registered candidate validator during compilation. The final provider
schema forbids this field so model output cannot confer evaluator authority.

## Validation, compilation, and assets

Before atomically writing an orchestrated project, Paper2ALE requires exact
project/source/asset/candidate/capability agreement, strict project validation,
local workflow bindings, supported families/templates/protocols, admissible
triage decisions, and no disallowed unresolved findings. Existing output is
replaced only when the manifest explicitly permits overwrite.

Candidate mode writes a project for review. Run trusted commands separately:

```powershell
paper2ale inspect projects/my-paper.json
paper2ale audit projects/my-paper.json --asset-cache .paper2ale/assets
paper2ale build projects/my-paper.json --out dist --asset-cache .paper2ale/assets
paper2ale publish projects/my-paper.json --out dist --asset-cache .paper2ale/assets
```

`build` can return a non-publication-ready candidate. `publish` fails unless
every release gate passes. With manifest `release: true`, `orchestrate` supplies
the trusted audit callback, writes the project only after the callback reports
`publication_ready: true`, then invokes fail-closed `publish_project` under
`--build-out`. Release output is one envelope containing both `orchestration`
and `build`.

Project JSON stores path-free asset snapshots, not raw repository/dataset
bytes. `--asset-cache` points `orchestrate`, `audit`, `build`, and `publish` at
the same content-addressed store. Reviewed asset-aware families receive a
read-only `BuildContext` and request an exact `(asset_id, relative_path)`;
cache reads recheck byte count and SHA-256. The cache location does not enter
the build identity. Generic v1 templates cannot materialize asset files and
reject such workflows until a reviewed capability is added.

Compiler identity covers the registered `compiler_id`, capability catalog,
and implementation identities of the builder, protocol schema/validator, and
candidate and project/task validators. Verifier identity covers publication
and grader-runner implementations plus registered preparation hooks.
Trusted-code changes thus invalidate build/resume identity. Publication also rebuilds the file inventory
twice and runs every golden and mutant grader twice; mismatched package bytes,
stdout, stderr, process summary, or parsed score payload fail reproducibility.

## Difficulty and exact-build calibration

Difficulty v2 keeps `challenge`, `evaluation_power`, and
`benchmark_sampling` separate. Generic controls are consumed per template and
recorded in `author/difficulty_control_audit.json`; an explicit non-default
override that the selected template cannot consume fails closed. These are
structural checks, not empirical evidence that a frontier model will find the
task hard.

V2 trial rows have exactly these fields and no extras:

```json
{
  "trial_id": "trial-001",
  "task_id": "hnn-hard-variable-nbody",
  "task_build_id": "task-build_<64-hex-digest>",
  "level": "hard",
  "agent_system_id": "agent_system_<derived-digest>",
  "semantic_id": "task_calibration_<derived-digest>",
  "passed": false,
  "score": 0.31,
  "seed": 17,
  "attempt": 1
}
```

`trial_id` is a globally unique portable path component of at most 128
characters; Windows device names are rejected. `seed` and `attempt` are
nonnegative integers. The full run coordinate is unique, `passed` is Boolean,
and `score` is a mandatory finite number in `[0, 1]`. Agent descriptors require
a provider, an operator-pinned immutable model revision, an exact lowercase
40- or 64-hex harness commit, tool policy, budgets, network policy, and
evaluation date. Use `pin_agent_system` to derive the versioned descriptor ID.

For publication-grade calibration, verify trials against the exact completed
build:

```powershell
paper2ale calibrate calibration-trials-v2.json `
  --project dist/my-paper/b-<build-prefix>/project.lock.json `
  --catalog dist/my-paper/b-<build-prefix>/catalog.json
```

V2 requires `--project` and `--catalog` together. The catalog must be the
literal manifest-covered `catalog.json` beside the exact canonical
`project.lock.json`. Paper2ALE validates the complete build manifests and
archive structure, project/task set, nested task-build and QA identities,
per-trial build ID, family level support, and selected level before producing a
report. A stale semantic ID is a hard pre-report error.

V2 can run without either binding flag for exploratory format checks and
summaries; that mode reports `build_catalog_verified: false` and cannot
establish that claimed task-build IDs came from a real build. A v2 claim is
release-usable only when `verified_claim_ready` is true, which requires both
verified build provenance and passing statistical/monotonicity targets. The
CLI therefore exits with status 2 for no-catalog v2 reports even when
`all_calibrated` is true.

Legacy v1 trials may use `--project` alone, do not accept `--catalog`, and do
not provide v2 pinned-system or exact task-build guarantees. One verified
catalog binds one selected build/level per task, so cross-level comparisons
across distinct builds currently require the unverified exploratory summary
mode. See [DIFFICULTY.md](DIFFICULTY.md).

## Installation integration

The CLI entry point is declared by the package:

```toml
[project.scripts]
paper2ale = "paper2ale.cli:main"
```

After an editable install, the commands above use the current working tree.
