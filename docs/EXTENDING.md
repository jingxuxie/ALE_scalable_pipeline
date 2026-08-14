# Extending Paper2ALE

Start with the narrowest trusted extension. A new paper does not automatically
require a new Python task family.

## Use an existing generic template

The `generic` family accepts bounded declarative protocols for:

- `numeric-affine-v1`;
- `table-filter-sort-v1`;
- `json-group-aggregate-v1`.

A protocol selects only allowlisted generators, reference solvers, output
contracts, metrics, and gates. The strict provider schema and runtime validator
reject unknown fields, arbitrary primitives, excessive shapes, non-finite
values, unsafe paths, missing hard gates, and mismatches between the outer task
blueprint and protocol evaluation.

Prefer this path when the task can be expressed by an existing template. The
same reviewed compiler code can serve many papers without importing generated
code or adding a paper-specific plugin.

The v1 templates do not materialize arbitrary files. If a workflow input has
an `asset_ref`, add a reviewed asset-backed generic capability or use a custom
family; the default generic gate rejects it. Project files contain snapshots,
not raw bytes. Asset-aware trusted code must use the read-only `BuildContext`
and an operator-supplied `--asset-cache` to request one exact
`(asset_id, relative_path)` whose size and SHA-256 are rechecked.

## Add a generic capability

Add a primitive or template only when its semantics are general, bounded, and
independently testable. A reviewed extension must provide:

- one exact strict-JSON protocol branch;
- bounded shape/range validation;
- a deterministic public-instance generator;
- an independent evaluator-owned reference solver;
- a fixed participant output format;
- recomputed metrics and mandatory hard gates;
- a successful golden artifact and realistic mutant artifacts;
- difficulty consumption for every declared supported level;
- syntax, leakage, reproducibility, and package tests.

All executable bytes must remain module-owned constants or reviewed source.
Protocol values are data. Never evaluate, import, format into a shell command,
or write provider-generated Python from a protocol.

Update the registered capability catalog and provider-facing schema together.
The orchestrator binds final proposals to that exact catalog, so a replay from
an older catalog cannot silently authorize a new primitive.

## Add a custom task family

Use a custom family when the workflow needs domain-specific simulation,
training, theorem proving, a specialized safe model format, or evaluation that
cannot be represented by the generic virtual machine.

A task-family module exposes a deterministic builder:

```python
def build_task_files(
    project: dict,
    task: dict,
    *,
    master_seed: int,
    instances: int | None = None,
    build_context: BuildContext | None = None,
) -> list[BuildFile]:
    ...
```

Register reviewed code explicitly:

```python
register_task_family(
    "my_family",
    build_task_files,
    compiler_id="example.my-family/v1",
    supported_difficulty_levels=("easy", "medium", "hard", "frontier"),
    supported_templates=("my-template-v1",),
    protocol_validator=validate_protocol,
    protocol_schema_factory=protocol_json_schema,
    candidate_validator=validate_candidate,
    capabilities={
        "generators": ("my-generator-v1",),
        "reference_solvers": ("my-reference-v1",),
        "output_contracts": ("my-output-v1",),
        "metrics": ("my-metric-v1",),
        "gates": ("my-hard-gate-v1",),
    },
)
```

`compiler_id` is always required and must be a stable versioned name. A family
that accepts declarative protocols must register a strict protocol validator,
a defensive provider-facing `protocol_schema_factory`, supported templates,
and its capability catalog. To accept candidates produced by orchestration it
must also register a reviewed `candidate_validator` that checks the final task
against the mined workflow. A fixed authored-project family may omit these
hooks, but then providers cannot select it and it cannot accept a persisted
workflow binding. Such an authored family should register a
`project_task_validator` that binds the exact reviewed source bundle, evidence
graph, and task semantic contract instead of trusting a familiar task ID alone.
Source/model content can never call registration APIs.

The compiler registry identity includes `compiler_id`, declared capabilities,
and implementation identities for the builder, protocol validator/schema
factory, candidate validator, and project/task validator. Changing trusted
implementation code changes the build/resume identity; bump the semantic
version in `compiler_id` whenever the compiler contract changes.

The builder must be deterministic and side-effect free: return `BuildFile`
objects rather than writing arbitrary paths. Use these visibility roots:

- agent: `description.md`, `task_card.json`, `main.py`, `input/...`,
  `software/...`;
- evaluator: `reference/...`, `example/...`;
- author: `author/...`.

The family owns:

- purpose-separated seeded input/reference generation;
- a robust grader that fails closed on malformed output;
- at least one independent successful example;
- task-specific leakage sentinels where useful;
- protocol and evaluator provenance;
- realistic mutant fixtures or mutation descriptions.

Register every publishable task’s golden/mutant preparation hook with
`paper2ale.verification.register_task_verification`. An unregistered task can
be inspected, but cannot become publication-ready.

Verifier identity covers the publication verifier, bounded subprocess/grader
runner, score contract, and every registered preparation hook. Publication
reruns the builder and compares the complete `BuildFile` inventory and
deterministic projected archive bytes. It also executes each golden and mutant
grader twice and requires identical stdout, stderr, process summary, and parsed
score payload. Add tests that demonstrate both deterministic repetition and
useful mutant rejection.

## Implement difficulty v2

Keep these purposes separate:

- `challenge` changes one participant episode;
- `evaluation_power` changes hidden discriminative strength;
- `benchmark_sampling` changes distribution coverage and replication.

Do not claim a harder level because only instance count increased. Challenge
and evaluation-power controls require independent monotonic checks. Derive
randomness with separate purpose labels for public instances, hidden
evaluation, and mutation.

Resolve task difficulty, consume the concrete values, and emit the exact
content-bound consumption manifest at
`author/difficulty_manifest.json`. Family-specific physical parameters belong
in a separate author file. Missing, cosmetic, or tampered consumption evidence
blocks release.

For declarative generic templates, declare exactly which controls each template
can consume and emit `author/difficulty_control_audit.json`. An explicit
non-default override for an unsupported or conditionally unavailable control
must fail compilation. These checks establish structural effects only; model
solve-rate claims require external pinned calibration trials.

Changing challenge or evaluation semantics changes the semantic ID and
invalidates prior calibration. Sampling-only changes have a separate profile
ID and preserve abstract difficulty semantics, but persisted trials are also
bound to the exact compiled `task_build_id`. Any new build ID requires a new
task-bound calibration ID. See [DIFFICULTY.md](DIFFICULTY.md).

## Add a completion provider

Implement `CompletionProvider.complete(request)`. Responses contain one
structured object. An adapter must preserve:

- normalized messages and strict output schema;
- provider parameters and timeout;
- idempotency key;
- usage and finish reason;
- raw-response digest;
- secret redaction in errors and provenance.

`CommandProvider` is the general bridge. It runs an argv vector with
`shell=False`, writes one normalized JSON request to standard input, and reads
a bounded JSON envelope from standard output. It can wrap a local model or any
hosted API. `ReplayProvider` reproduces exact request-keyed responses offline;
`MockProvider` is for tests.

Orchestration uses multiple provider calls. Record every map, reduce,
synthesis, and final-project response under its exact idempotency key.

## Integrate paper discovery

Discovery is optional upstream software, not a trusted Paper2ALE stage. Its
handoff must be an orchestration manifest containing:

- an operator-attested paper suitability profile;
- local source paths and exact public provenance metadata;
- local code/data asset paths and license/version metadata;
- explicit output, family, difficulty, bounds, and release policy.

Discovery must not bypass local byte hashing, deterministic triage, or release
gates. See [ORCHESTRATION.md](ORCHESTRATION.md).

## Evolve a schema

Do not mutate an existing schema version’s semantics in place. Add a new
version and a deterministic migration. Preserve source metadata and extraction
locks, asset/evidence/workflow/candidate identities, persisted workflow
bindings, difficulty identities, and compiler/verifier implementation
identities. Record lossy conversions and add canonical-ID, stale-replay, and
stale-build tests.

## Add a projection

Profiles are allowed visibility sets in `packaging.py`. Add a profile only when
it is a true projection of the canonical `BuildFile` inventory. Never create a
separately maintained task directory; that reintroduces drift between
participant and evaluator packages.
