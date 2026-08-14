# End-to-end orchestration

`paper2ale orchestrate` is the recommended v0.3 entry point. It coordinates
local byte resolution, deterministic triage, bounded structured extraction,
workflow closure, candidate mining, final project generation, and optional
release gates. It is a coordinator, not another source of executable trust.

## Run it

With a deterministic replay:

```powershell
paper2ale orchestrate manifests/my-paper.json --replay replays/my-paper.jsonl
```

The repository includes a credential-free end-to-end fixture:

```powershell
paper2ale orchestrate examples/orchestration/manifest.json `
  --replay examples/orchestration/replay.json
```

With an operator-owned local or hosted provider adapter:

```powershell
paper2ale orchestrate manifests/my-paper.json `
  --command python `
  --command-arg provider_adapter.py `
  --asset-cache .paper2ale/assets
```

An LLM API is optional. A replay can reproduce every map, reduction,
synthesis, and final-project response offline. A command adapter receives
provider-neutral requests on standard input and returns bounded structured
response envelopes on standard output. No provider output is executed.

## Manifest contract

Discovery, if used, must stop at this contract. It may rank papers and fetch
candidate artifacts under operator policy, but it must materialize them
locally and write an explicit manifest. Paper2ALE performs no implicit network
fetch.

A concise manifest looks like this:

```json
{
  "schema_version": "paper2ale.orchestration-manifest/v1",
  "project_id": "example-paper-suite",
  "paper": {
    "paper_id": "source.example.paper",
    "title": "Example scientific workflow",
    "readable": true,
    "provenance_complete": true,
    "license_status": "known",
    "scientific_quality": 0.85,
    "evidence_coverage": 0.9,
    "independent_verification_possible": true,
    "analytic_oracle_possible": true,
    "synthetic_data_possible": true,
    "public_code": true,
    "public_data": true,
    "code_license_known": true,
    "data_license_known": true,
    "workflow_reconstructable": true,
    "contradictions_resolved": true,
    "resources_bounded": true
  },
  "sources": [
    {
      "path": "sources/paper.pdf",
      "metadata": {
        "id": "source.example.paper",
        "kind": "paper",
        "uri": "https://example.org/paper.pdf",
        "version": "published-v1",
        "license": "CC-BY-4.0",
        "visibility": "author",
        "citation": "Author. Example scientific workflow."
      }
    }
  ],
  "assets": [
    {
      "asset_id": "asset.example.code",
      "path": "sources/repository",
      "kind": "repository",
      "metadata": {
        "commit": "<full commit hash>",
        "license": "MIT",
        "visibility": "public",
        "role": "associated implementation"
      }
    },
    {
      "asset_id": "asset.example.data",
      "path": "sources/data",
      "kind": "dataset",
      "metadata": {
        "version": "v1",
        "license": "CC-BY-4.0",
        "visibility": "public"
      }
    }
  ],
  "output_path": "projects/example-paper-suite.json",
  "allowed_paper_decisions": ["eligible"],
  "allowed_candidate_decisions": ["eligible"],
  "allowed_families": ["generic"],
  "allow_unresolved": false,
  "max_candidates": 64,
  "max_final_context_chars": 2000000,
  "difficulty": "hard",
  "release": false,
  "overwrite": false
}
```

The manifest’s local `path` and `output_path` fields are operator controls.
They are not copied into the portable project or model-facing evidence.
Portable source records contain public provenance and hashes; asset snapshots
contain safe relative file names, byte counts, media types, extraction status,
and hashes.

An optional `sources[].metadata.sha256` must be exactly 64 lowercase hexadecimal
characters and is verified before any provider call. When omitted as above,
the resolver computes and pins the digest of the local bytes.

Most `paper` fields are operator attestations. Paper2ALE does not pretend that
a language model can objectively peer-review scientific quality, evidence
coverage, conflict resolution, or verifier strength. It does mechanically
reconcile the availability claims after resolution: `public_code` requires a
resolved public `repository`, `public_data` requires a resolved public
`dataset`, and an effective known-license signal requires concrete non-unknown
licenses on all corresponding public assets. An unsupported positive
availability/license assertion fails closed. The effective triage profile and
its operator-attested versus asset-verified signals are recorded in the
receipt.

Optional policy and bound objects may be supplied under `triage_policy` and
`staged_config`. The implementation rejects unknown fields and invalid types.
Important defaults are:

- only `eligible` paper and candidate decisions are admitted;
- at least one closed workflow is required;
- unresolved synthesis findings are rejected;
- only the trusted `generic` family is permitted for general protocols;
- provider context, findings, reductions, workflows, and candidates all have
  explicit count and character bounds.

`staged_config.max_concurrency` is an opt-in map/reduce parallelism control. It
defaults to `1` and accepts values through `64`. Values above `1` require a
thread-safe provider adapter. Requests may finish out of order, but Paper2ALE
restores deterministic evidence-unit and reduction-batch order before emitting
stage results and receipts.

## Source and asset resolution

`sources` are paper/text inputs with exact project provenance. PDF extraction
uses page locators; UTF-8 text uses deterministic line/character locators.
Malformed, encrypted, image-only, binary-looking, empty, and over-limit source
documents fail closed rather than being silently truncated.

Every resolved source also receives a path-free
`paper2ale.source-extraction/v1` lock. It binds raw SHA-256, media type, byte
count, extractor identity, aggregate extraction hash, and each chunk's locator,
text hash, and character count. These locks enter the final synthesis context
and orchestration receipt, so replay and review can distinguish exact source
bytes and extraction output even though they do not expose local paths.

`assets` cover individual files, local repositories, and datasets. Resolution:

- rejects symlinks and special files;
- excludes version-control and common cache directories;
- sorts paths deterministically;
- enforces file, total-byte, depth, page, and extracted-text bounds;
- hashes raw bytes and the relative-path file tree;
- optionally writes verified blobs to a local content-addressed cache;
- records binary or over-limit extraction status instead of inventing text.

No public code or dataset is mandatory if the task can use a trusted analytic
oracle or a deterministic synthetic generator. Workflow artifacts declare
real file dependencies with `asset_ref`; the orchestrator requires the asset ID
and relative path to exist in the resolved snapshot. An input or reference
artifact that directly cites asset-derived evidence must declare the exact
`asset_ref` implied by that evidence; a missing or different asset ID or
relative path fails workflow synthesis.

The three generic v1 templates do not yet materialize arbitrary asset files
into participant packages. An asset-backed workflow therefore fails the
generic capability gate and needs a reviewed asset materializer or custom
family. Asset text can still ground workflow evidence. This is a deliberate
fail-closed limitation, not an inference that snapshotted bytes automatically
became task inputs.

`--asset-cache PATH` stores resolved raw bytes in a content-addressed cache and
reuses that cache for orchestration's trusted audit and release build. Portable
project JSON contains only snapshots. Later `audit`, `build`, or `publish`
commands that use an asset-aware reviewed family must receive the same cache;
a read-only `BuildContext` retrieves only an exact `(asset_id, relative_path)`
and rechecks size and SHA-256. The cache's local location does not affect build
identity.

## Stages and trust transitions

1. **Resolve inputs** pins source and asset bytes, records source-extraction
   locks, and removes local paths from provider-visible data.
2. **Evidence-backed paper triage** reconciles public code/data/license claims
   against those resolved assets, then applies the deterministic policy. The
   default admits only an `eligible` profile. This still runs before any
   provider call.
3. **Map** extracts bounded findings from each untrusted evidence unit.
   Finding IDs are derived locally from the unit and response content.
4. **Reduce** consolidates deterministic batches. Every reduced fact must cite
   finding IDs from its own batch.
5. **Synthesize** emits declarative Workflow IR v2 artifact/operation graphs.
   Artifacts declare `asset`, `trusted_generator`, `participant`,
   `trusted_evaluator`, or `external` origin. Asset origins require exact
   `asset_ref`; trusted generators require registered `capability_ref`.
   Unknown citations, invalid producer authority, cycles, missing producers,
   external participant inputs, or executable fields fail validation.
6. **Mine candidates** takes a backward slice from each participant output and
   locates an independent trusted-evaluator plan.
7. **Finalize and bind** constrains the provider to the exact source bundle,
   source-extraction and asset locks, admitted candidates, capability catalog,
   project ID, and difficulty. Provider-authored `workflow_binding` is
   forbidden; trusted local code attaches a canonical content-derived binding
   over the closed workflow, mined candidate, and family.
8. **Task triage** runs after the generated task has passed trusted-family,
   protocol, binding, and candidate semantic validation. It then checks
   self-contained inputs, machine-checkable output, bounded resources, evidence
   coverage, evaluator implementation, and compiler availability.
9. **Audit/publish** compiles only allowlisted protocols and applies all hard
   publication gates.

Authority labels in a generated workflow are descriptive. They do not install
or register evaluator code. A candidate becomes trusted only when it maps to a
reviewed compiler capability such as one of the generic templates, and its
persisted workflow binding is rechecked by that family's candidate validator.

## Candidate versus release mode

With `"release": false`, the CLI still supplies the trusted audit callback. It
atomically writes a validated project candidate and reports either
`validated_candidate` or `publication_ready_candidate`; candidate mode does not
package a release. The project can then be inspected and released explicitly:

```powershell
paper2ale inspect projects/example-paper-suite.json
paper2ale audit projects/example-paper-suite.json `
  --difficulty hard `
  --asset-cache .paper2ale/assets
paper2ale publish projects/example-paper-suite.json `
  --difficulty hard `
  --out dist `
  --jobs 4 `
  --asset-cache .paper2ale/assets
```

With `"release": true`, the CLI supplies a trusted audit callback to the
orchestrator. The callback must report `publication_ready: true` before the
orchestrator atomically commits the project. The CLI then invokes fail-closed
`publish_project` packaging under `--build-out`:

```powershell
paper2ale orchestrate manifests/example-paper-suite.release.json `
  --replay replays/example-paper-suite.jsonl `
  --build-out dist `
  --jobs 4 `
  --asset-cache .paper2ale/assets
```

Release mode never permits unresolved synthesis findings, even when a
candidate-mode override would allow them. If deterministic audit fails, the
final project is not committed. If subsequent packaging fails, no
publication-ready package is reported.

Candidate mode prints `{"orchestration": ...}`. Release mode prints one JSON
envelope containing both `{"orchestration": ..., "build": ...}` so reviewers
can inspect the exact triage/extraction receipt and the content-addressed
publication result together.

The orchestration receipt records source metadata, source-extraction locks,
asset locks, evidence-backed paper/candidate triage, map/reduce artifacts,
closed workflows, mined candidates, provider request IDs and response digests,
project hash, and publication state. The binding itself is persisted inside
each generated project task, not duplicated in the receipt. Provider errors are
sanitized so adapter stderr and credentials do not enter receipts.

## Replay files

Orchestration makes multiple completion requests. A replay JSON maps every
normalized request idempotency key to its response object. JSONL uses one
record per request. The response `data` below is abbreviated; a real map
response must also contain its bound `unit_id` and complete `findings` array:

```json
{"idempotency_key":"map-request_<digest>","data":{"schema_version":"paper2ale.evidence-map/v1"}}
```

A changed extracted locator or text, prompt, schema, parameter, workflow batch,
or capability catalog changes the relevant request key. Changing only an
extractor version does not necessarily change a key when its normalized
locators and text are byte-identical. Replays therefore cannot silently
substitute responses for changed stage inputs.

## Scope

Orchestration ends at deterministic ALE-compatible task packaging and release
evidence. v0.3 does not execute `cua_bench`, interactive computer-use tasks,
or cloud deployment.
