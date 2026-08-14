# Threat model and publication gates

Scientific task generation fails quietly when it confuses plausible artifacts
with trustworthy evaluation. Paper2ALE treats source provenance, evaluator
validity, and release evidence as hard constraints.

## Trust assumptions

- The operator controls local source acquisition, license interpretation, and
  the truthfulness of scientific-quality, evidence-coverage, conflict, and
  workflow-feasibility attestations in the manifest's paper profile.
- Papers, repositories, notebooks, datasets, provider responses, participant
  artifacts, and generated workflow authority labels are untrusted.
- Reviewed Paper2ALE code, registered compiler capabilities, verification
  hooks, and operator-supplied audit/publish callbacks are trusted.
- A release claim covers deterministic generation and package gates. It does
  not cover `cua_bench`, live cloud infrastructure, or interactive
  computer-use execution.

## Threats and mitigations

### Biased or fabricated discovery metadata

An upstream discovery service may overstate quality, licenses, artifact
availability, or verifiability. Discovery has no direct authority. It must
materialize local bytes and emit an explicit manifest. Paper2ALE hashes those
bytes before triage. Positive public-code/public-data claims require a resolved
public repository/dataset snapshot, and known-license claims require concrete
non-unknown metadata on all corresponding public assets; unsupported positive
availability/license combinations fail closed.
Scientific quality and evidence judgments remain explicit operator
attestations to which the pinned triage policy is deterministically applied.

### Malicious local paths and cache objects

Repositories or datasets may contain traversal names, links, special files,
cache directories, huge files, or corrupt blobs. Asset resolution rejects
unsafe relative paths, symlinks, special files, depth/file/byte overflows, and
hash mismatches. Project JSON stores only snapshots. Cache reads and writes
verify SHA-256, and the read-only `BuildContext` releases bytes only for an
exact snapshot `(asset_id, relative_path)` after rechecking size and digest.
Cache locations do not enter build identity. Portable project data and provider
requests omit operator-local absolute paths.

### Untrusted source instructions

Papers, HTML, issue text, code comments, and data may instruct an extractor to
ignore policy or reveal secrets. Provider requests delimit all source content
as untrusted evidence. Map output is rebound to one source unit; reduce output
can cite only findings from its own batch. Neither is executable.

Each source also has a path-free extraction lock binding its raw digest, media
type, size, extractor identity, aggregate extraction digest, and each chunk's
locator/text digest/character count. Changed extraction cannot be silently
presented as the same receipt even if a replay key remains reusable when the
normalized locators and text are identical.

### Citation laundering and hallucinated workflow closure

A provider may cite nonexistent findings, silently merge disagreements, or
invent inputs and outputs. Finding IDs are derived locally. Reductions and
workflows reject out-of-scope citations. Closure validation rejects unknown
artifacts, missing/multiple producers, cycles, undeclared outputs, and external
participant dependencies. Workflow IR v2 additionally requires every artifact
to declare an origin. Asset origins require an exact snapshot `asset_ref`,
trusted generators require a registered `capability_ref`, and participant or
trusted-evaluator outputs require matching producer authority. Direct
asset-derived citations must agree with the declared asset reference.
Unresolved synthesis findings block release.

### Paper/code disagreement

A paper is not assumed to dominate code, and code is not assumed to dominate a
paper. Conflicting records retain exact sources and locators. Tasks cannot use
an unresolved high-impact conflict; a selected interpretation must be recorded
and cited.

### Executable-authority smuggling

A provider may place commands, scripts, code, executors, imports, or invented
grader names in a workflow or protocol. Workflow IR rejects executable fields.
The generic family accepts only strict allowlisted primitives and bounded JSON.
Generated content cannot call registration APIs. Only reviewed compiler code
can create executable files or trusted evaluators. The final provider is also
forbidden from supplying `workflow_binding`; local trusted code derives the
canonical workflow/candidate/family binding, and the reviewed candidate
validator rechecks it before compilation.

### Self-reported metrics and fabricated truth

Participant metrics, plots, prose, and claimed ground truth are untrusted.
Graders recompute scores from evaluator-owned targets. Safe declarative outputs
are preferred. If participant code is unavoidable, it must run offline under
time, memory, output, filesystem, and process isolation.

### Degraded comparators and weak baselines

Improvement ratios can be gamed by worsening a baseline. Evaluators must gate
absolute accuracy before using relative improvement. Required metric and gate
sets are bound between the outer task blueprint and trusted protocol.

### Reference leakage

Every `BuildFile` has agent, evaluator, or author visibility. Agent projections
are scanned for private paths and configured sentinel bytes. Evaluator
references are withheld until evaluation. ZIP validation rejects traversal,
absolute/drive paths, duplicate or case-colliding members, links, special
files, and excessive expansion.

### Hard-coded public instances

One public fixture can be memorized. Task families generate multiple
purpose-separated deterministic variants. Participant inputs may be visible;
hidden targets and adversarial cases remain evaluator-only. The same grader
must work across the family.

### Cosmetic difficulty

A level label or larger instance count may be presented as harder without
changing an episode. Difficulty v2 checks `challenge` and `evaluation_power`
independently and treats `benchmark_sampling` separately. Builders must emit a
content-bound consumption manifest. Sampling-only changes cannot justify a
harder level.

### Stale or pooled calibration

Solve rates can change with model revision, harness, tools, budget, network
policy, difficulty semantics, or task bytes. Calibration pins these under
agent-system and task-bound calibration IDs. Different systems or task builds
are never pooled. A sampling-only profile change preserves the abstract
difficulty semantic ID, but prior evidence is not accepted for a different
`task_build_id`; challenge/evaluation changes always invalidate it. Confidence
intervals and minimum trial counts prevent point estimates from masquerading
as robust calibration. A v2 result is release-usable only when
`verified_claim_ready` confirms both the statistical/monotonicity targets and
the exact catalog/project-lock provenance. No-catalog summaries remain
exploratory and cannot return CLI success.

### Golden-only overfitting

A grader may accept its reference while failing to reject plausible wrong
answers. Publication requires registered realistic mutants to fail. Generic
templates include template-specific mutants; custom families must register
their own preparation hooks.

### Nondeterministic or partial builds

Concurrent workers, stale state, timestamps, modes, or compression can produce
different packages under the same name. Stage leases, canonical JSON,
content-addressed objects, exact full build IDs, timing-free QA, deterministic
ZIP metadata, and full archive reproduction make drift observable. Compiler
identity includes stable family IDs, capabilities, and builder/protocol/
candidate/project-validator implementation hashes; verifier identity includes
the grader runtime and registered preparation hooks. Publication rebuilds and
compares the complete inventory and projected archive bytes, then runs each
golden and mutant grader twice and compares process results, stdout, stderr,
and parsed score payload. Resume occurs only after identities, catalogs,
manifests, hashes, and ZIP structure validate.

## Deterministic triage decisions

The default policy distinguishes why a source does not proceed:

- `rejected`: unreadable, incompatible license, or quality below policy;
- `no_viable_task`: no closed workflow, independent verifier, or bounded
  execution route;
- `missing_artifacts`: necessary code/data bytes are unavailable and cannot be
  constructed analytically or synthetically;
- `manual_review`: licenses, provenance, coverage, conflicts, evaluator
  implementation, or family support need human resolution;
- `eligible`: all admission requirements pass.

No public code or dataset is an automatic rejection. An independent analytic
oracle or synthetic generator can be stronger than a repository’s self-reported
metric. Conversely, public artifacts do not rescue an unverifiable task.

By default, orchestration admits only `eligible`. Candidate-mode overrides are
explicit manifest policy. They do not weaken release mode’s unresolved-evidence
or publication gates.

## Hard publication gates

A task is publishable only when all applicable gates pass:

1. source metadata, byte hashes, source-extraction locks, licenses, and asset
   locks validate;
2. paper and task triage decisions are explicitly admissible;
3. map/reduce identities and citation subsets validate;
4. workflow references, artifact origins, capabilities, asset references,
   producers, outputs, closure, and acyclicity validate;
5. every requirement, protocol choice, metric, and gate maps to evidence;
6. no unresolved high-impact source conflict affects the task;
7. a canonical local workflow/candidate/family binding exists and its reviewed
   candidate validator confirms semantic alignment;
8. family, compiler ID, template, generator, solver, output, metric, and gate
   capabilities are registered and strictly validated;
9. compiler and verifier implementation identities are content-bound;
10. challenge/evaluation controls are consumed and hash-bound;
11. the agent projection contains no evaluator/reference material;
12. the trusted grader recomputes metrics and handles malformed submissions as
    structured failures;
13. an independent successful reference passes;
14. registered realistic mutants fail;
15. clean offline smoke execution stays within the declared bounds measured by
    the gate;
16. rebuilding reproduces inventory, build ID, manifests, and projected ZIP
    bytes, and repeated golden/mutant grader runs reproduce their outputs;
17. every emitted directory and archive passes path, type, size, checksum,
    mode, and visibility validation;
18. the release audit or publisher reports `publication_ready: true`.

A soft quality score may rank tasks that pass. It never overrides a hard gate.
Candidate generation success is not publication readiness.
