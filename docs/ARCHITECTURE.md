# Paper2ALE architecture

Paper2ALE treats a paper and its associated artifacts as a hidden
specification for a compiler. The compiler produces paper-blind,
specification-complete, executable task workflows with trusted evaluation.
The target is the paper's **reported evidence-production workflow**, not a
claim to reconstruct every undocumented step of the human research process.

## Trust boundary

The pipeline has two deliberately different zones.

1. The **evidence zone** resolves sources and may use probabilistic models to
   extract claims, equations, protocols, artifacts, and candidate tasks. Paper
   and repository content is untrusted input. Model output is an untrusted
   proposal until it passes the project schema and evidence checks.
2. The **compiler zone** is deterministic. It validates references, chooses a
   task-family implementation, generates seeded instances, audits visibility,
   writes checksum manifests, and creates byte-reproducible archives.

An LLM may propose an evaluator plan. It does not become a grading authority:
task-family code owns trusted target construction and metric recomputation.

## Data flow

```mermaid
flowchart LR
    S["Pinned source bundle"] --> X["Evidence extraction"]
    X --> G["Evidence and workflow graph"]
    G --> C["Candidate tasks"]
    C --> V["Schema and conflict gates"]
    V --> F["Task-family compiler"]
    F --> I["Seeded instance families"]
    I --> A["Leakage and syntax audit"]
    A --> P["Visibility projections"]
    P --> Z["Deterministic archives"]
    Z --> Q["QA report and catalog"]
```

The long-term stage DAG is:

1. `resolve_source`: pin bytes, versions, repository commits, licenses, and
   retrieval metadata.
2. `extract_source`: obtain page- or file-addressable evidence.
3. `build_evidence_graph`: normalize claims, equations, protocols, metrics,
   limitations, and conflict sets.
4. `propose_candidates`: create structured task ideas, never free-form task
   folders.
5. `feasibility_and_dedup`: reject unverifiable, unbounded, inaccessible, or
   redundant candidates.
6. `compile_protocol`: fix visible inputs, hidden references, output schema,
   metrics, gates, resources, and instance policy.
7. `materialize_assets`: invoke the deterministic task-family compiler.
8. `run_reference_trials`: execute independent successful implementations.
9. `calibrate`: choose thresholds from distributions and meaningful baselines.
10. `adversarial_validate`: require golden passes and realistic mutant
    failures.
11. `score_and_gate`: apply hard publication gates before soft quality scores.
12. `package`: derive agent, evaluator, and author projections from one file
    inventory.

The current implementation makes local byte pinning and bounded PDF/text
extraction (1-2), provider/replay project proposal with strict validation
(3-4), deterministic protocol/materialization (6-7), reference and mutant
trials (8 and 10), difficulty calibration summaries (9), publication gates
(11), and packaging (12) directly executable. Deduplication and quality-scoring
primitives exist for stage 5; selecting candidates across a large persistent
corpus remains an operator/orchestrator concern.

## Canonical project

`paper2ale.project/v1` is the single source of truth. It contains:

- an exact source bundle;
- evidence records with status, confidence, provenance, conflict sets, and
  interpretations;
- a workflow graph of operations, artifacts, edges, and supported claims;
- task blueprints with an explicit disclosure mode;
- resource budgets, instance counts, output contracts, gates, score metrics,
  and evidence references.
- optional versioned difficulty selections and profiles that resolve to
  concrete generator/evaluator controls and calibration bands.

The disclosure modes are kept separate:

- `specification_preserving`: the method is fully specified but source identity
  and irrelevant narrative are removed;
- `masked_workflow_completion`: a supplied workflow has one or more meaningful
  missing or faulty stages;
- `method_masked_rediscovery`: the outcome is graded while the originating
  method remains hidden.

Unresolved high-impact source conflicts cannot be used by a task. A task may
proceed only after its protocol records an explicit interpretation and pins the
chosen evidence.

## Identity and reproducibility

All semantic identities use SHA-256 over canonical JSON:

- project identity is a human-stable slug plus a schema version;
- `build_id` covers the fully resolved project, compiler and verification-plan
  identities, seed, difficulty, and instance overrides;
- `task_build_id` covers the raw family inventory, executable modes,
  visibility, and verification-plan identity before the self-referential QA
  report is appended;
- `stage_key` covers stage name/version, relevant inputs, and relevant config;
- content-store objects are addressed directly by their byte digest.

Timestamps and wall-clock measurements are operational metadata only and never
enter canonical QA or a content identity.
ZIP entries are sorted, use a fixed 1980 timestamp, normalized permissions, and
fixed compression settings. Reproducibility QA rebuilds both inventories and
full projected archives and compares their hashes.

The complete 256-bit build ID remains in catalogs, locks, manifests, and stage
state. Its physical directory uses a 96-bit prefix (`b-<24 hex>`) to keep ALE's
deep per-variant layout compatible with legacy Windows path limits; an existing
prefix directory is accepted only when its catalog contains the exact full ID.

`StageStateStore` uses SQLite WAL mode and expiring leases. Independent workers
can claim a stage, renew a lease, atomically commit outputs, and reclaim work
after a worker dies. `ContentStore` commits bytes atomically under their digest.

## Package projections

Every generated file has exactly one base visibility:

- `agent`: description, task card, ALE module, participant input, and starter
  software;
- `evaluator`: hidden references, grader, and example solution;
- `author`: evidence graph, provenance, QA, calibration records, and notes.

Profiles are monotonic projections:

| Profile | Included visibility |
| --- | --- |
| agent | agent |
| evaluator | agent + evaluator |
| author | agent + evaluator + author |

No profile is hand-maintained. The same immutable `BuildFile` inventory creates
all three, their manifests, modern profile ZIPs, and compatibility-named ALE
archives.

For current ALE deployment, the compiler additionally derives a deterministic
operator layout from that same inventory:

```text
tasks/<domain>/<task>/{main.py,task_card.json,README.md}
task-data/<domain>/<task>/<variant>/{input,software,reference}
```

This `ale-local` bundle targets ALE's `task_data_source: local:...` provider.
The provider stages `input/` and `software/` before the agent, then
`reference/` only for evaluation. Common software and the trusted grader are
duplicated per variant; each variant receives only its own generated input and
reference targets. `DEPLOYMENT.json` records every source-to-destination map.

## ALE adapter

Each HNN task includes a current-style `task_card.json` and `main.py` using an
ALE `TaskConfig`, `tasks_config`, `setup_task`, and `evaluate_task`. Inputs are
under `input/`, references are under `reference/`, and the grader returns a
score in `[0, 1]`. The complete package is author/debug material; an ALE runner
must preserve its normal rule of staging `reference/` only after the agent
finishes.
