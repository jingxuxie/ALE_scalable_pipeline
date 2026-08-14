# Generating a project from local sources

`paper2ale generate` is the probabilistic front end to the deterministic
compiler. It ingests local source bytes, constructs one provider-neutral
structured-completion request, validates the untrusted response, and atomically
publishes `paper2ale.project/v1` JSON. It does not compile task assets unless
the operator explicitly adds `--build`.

## 1. Pin source metadata

Each local source requires a separate strict JSON metadata object. The object
is the exact `source_bundle` record that the provider must return. Required
fields are `id`, `kind`, `uri`, `version`, `license`, and `visibility`.
`citation`, `retrieved_at`, and an expected `sha256` are optional. Unknown
fields, duplicate JSON keys, non-finite numbers, and empty required strings are
rejected.

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

When `sha256` is present, ingestion verifies it before invoking a provider. If
it is omitted, Paper2ALE computes and records the digest, so the generated
project still pins the exact bytes. Paper2ALE never invents a retrieval time or
source version.

For multiple sources, paths and `--metadata` options pair positionally. The
normalized request sorts the resulting sources by source ID, making input order
irrelevant after duplicate IDs are rejected.

## 2. Choose a completion provider

The command adapter is an argv vector, never a shell command string:

```powershell
paper2ale generate .\Hamiltonian-Neural-Networks.pdf `
  --metadata .\hnn-paper.source.json `
  --project-id hnn-generated `
  --out .\projects\hnn.generated.json `
  --command python `
  --command-arg .\provider_adapter.py `
  --command-arg=--model `
  --command-arg example-model
```

The adapter receives normalized request JSON on standard input. It must emit
one bounded JSON envelope on standard output:

```json
{
  "data": {"schema_version": "paper2ale.project/v1"},
  "finish_reason": "stop",
  "usage": {"input_tokens": 1000, "output_tokens": 500}
}
```

`data` must contain the complete project, not the abbreviated example above.
Use `--parameters provider-parameters.json` for provider-neutral model
parameters. `--command-cwd` sets the adapter working directory. Adapter
arguments beginning with a dash use the `--command-arg=--flag` form.

For deterministic offline replay, point the same command at a replay JSON or
JSONL file:

```powershell
paper2ale generate .\Hamiltonian-Neural-Networks.pdf `
  --metadata .\hnn-paper.source.json `
  --project-id hnn-generated `
  --out .\projects\hnn.generated.json `
  --replay .\replays\hnn.jsonl
```

A JSON replay maps request idempotency keys to response data. A JSONL replay
contains records of this exact form:

```json
{"idempotency_key":"r-...","data":{"schema_version":"paper2ale.project/v1"}}
```

A recording command adapter can persist the normalized request's
`idempotency_key` and successful response in this format. Replays are keyed, so
a changed source byte, extractor version, prompt, schema, project ID,
difficulty, or provider parameter cannot accidentally reuse an old response.

## 3. PDF and text ingestion

Non-PDF files must be nonempty UTF-8 text without NUL bytes. Text receives
deterministic `lines:start-end` locators. PDF detection uses both the suffix and
PDF header. PDF extraction uses the required `pypdf` runtime dependency, which
is installed with Paper2ALE. If that installation is damaged, repair it with:

```powershell
python -m pip install pypdf
```

Each extracted PDF page receives a `page:number` locator, and the installed
`pypdf` version becomes part of the request evidence. Text extraction does not
preserve visual layout and is not a fidelity check for equations, figures, or
tables. Encrypted, malformed, over-limit, and image-only PDFs fail. Paper2ALE
does not silently OCR or truncate them; for layout-critical sources, run a
reviewed OCR/vision extraction separately and ingest its UTF-8 text as another
pinned source.

Defaults are 64 MiB per source, 128 MiB for all source bytes, 2,000,000
extracted characters per source, 4,000,000 extracted characters total, 1,000
PDF pages, and 20,000 characters per evidence chunk. The corresponding CLI
options are:

```text
--max-source-mb
--max-total-source-mb
--max-evidence-chars
--max-total-evidence-chars
--max-pdf-pages
--chunk-chars
```

All limits are rejecting bounds, not truncation targets.

## 4. Validation and atomic publication

Before writing the destination, generation requires all of the following:

- a successful provider finish reason;
- strict `paper2ale.project/v1` validation and reference integrity;
- an exact match for the requested project ID;
- a byte-canonical match for every pinned `source_bundle` record;
- at least one task;
- a registered trusted task-family implementation for every task.

The structured request uses one self-contained schema assembled from the
project, evidence, task, and difficulty schemas. Local schema references are
rewritten into namespaced `$defs`, so a remote adapter does not need filesystem
access.

Provider, schema, provenance, and family failures create no destination. An
existing destination prevents provider invocation unless `--overwrite` is
explicit. With `--overwrite`, the old file remains intact until the new project
has validated and a same-directory temporary file has been flushed. Local
source paths are never included in provider messages. Provider exceptions are
reported with request and exception types while adapter stderr is suppressed.

On success, the CLI prints a receipt containing the project ID, canonical file
digest, provider-neutral response-data digest, request ID, finish reason, usage,
and output path. The status is `validated_candidate`: generation alone does not
claim that runtime, mutation, resource, or reproducibility publication gates
have passed.

## 5. Optional deterministic compilation

Add `--build` to invoke the compiler only after the validated project has been
published:

```powershell
paper2ale generate paper.pdf `
  --metadata paper.source.json `
  --project-id generated-suite `
  --out projects\generated-suite.json `
  --replay replays\generated-suite.jsonl `
  --build `
  --build-out dist `
  --jobs 4
```

Build controls are `--seed`, `--instances`, `--build-no-resume`, and
`--build-force`. A compiler failure does not remove the validated project; it
can be inspected, audited, or rebuilt independently.

Difficulty is an enforceable profile, not a display label:

```powershell
paper2ale generate paper.pdf ... --difficulty hard --build
paper2ale build projects\generated-suite.json --difficulty hard
paper2ale audit projects\generated-suite.json --difficulty hard
```

The choices are `easy`, `medium`, `hard`, and `frontier`. A requested level is
resolved to versioned generator/evaluator controls. Generation and compilation
fail if any selected family does not declare support or does not emit proof
that it consumed those controls. `generate --build` passes the same override to
the compiler.

## 6. Calibration summaries

`calibrate` groups trial rows by task and level and compares Wilson confidence
intervals with the resolved target band:

```json
[
  {
    "task_id": "hnn-mass-spring",
    "level": "hard",
    "passed": true,
    "score": 0.91,
    "model": "example-model",
    "agent": "example-agent"
  }
]
```

```powershell
paper2ale calibrate trials.json
paper2ale calibrate trials.json --project projects\custom-profile-project.json
```

Without `--project`, calibration uses the built-in `core` profile. With a
project, task-specific custom profiles are resolved from that project. Exit
status is zero only when every task/level group is calibrated; insufficient,
too-easy, too-hard, or inconclusive groups return status 2 with a complete JSON
report.

## Installation integration

The source checkout locates schemas at the repository-level `schemas/`
directory. Installed distributions discover the four schemas from the
packaged data-files location. `--schema-dir` remains available for relocated or
standalone deployments. PDF ingestion uses the declared `pypdf` runtime
dependency. Schema availability does not affect compilation of an already
generated project JSON.
