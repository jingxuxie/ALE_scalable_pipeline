# Difficulty v2 and empirical calibration

Difficulty is a resolved experimental configuration, not a display label.
Paper2ALE keeps the familiar `easy`, `medium`, `hard`, and `frontier` names,
but v2 separates three purposes that should not be conflated.

## Three axes

| Axis | Meaning | Core controls |
| --- | --- | --- |
| `challenge` | What makes one participant episode harder | input complexity, noise, masked fraction, constraint count |
| `evaluation_power` | How strongly hidden evaluation distinguishes correct from weak solutions | hidden cases, threshold scale, rollout horizon, required pass fraction, adversarial cases |
| `benchmark_sampling` | How much of the task distribution is measured | instance count |

Challenge and evaluation power have separate monotonicity checks. Increasing
only the number of sampled instances cannot justify a harder label; a profile
whose adjacent levels differ only in sampling is rejected as cosmetic.

## Identities and invalidation

A resolved v2 level records:

- `profile_semantic_id`: identity of the versioned profile semantics;
- `semantic_id`: challenge plus evaluation-power semantics, independent of
  benchmark sampling and any particular compiled task;
- `sampling_id`: benchmark population and replication settings;
- `resolution_id`: the complete resolution.

Persisted calibration uses a stricter task-bound identity. Call
`derive_task_calibration_id(resolved, task_id=..., task_build_id=...)` and store
its `task_calibration_<digest>` result as each trial's `semantic_id`. The exact
`task_build_id` comes from a verified build catalog. Any task, protocol,
compiler, generator, evaluator, or frozen-data change that changes that build
ID invalidates the calibration.

Changing only `benchmark_sampling.instance_count` changes `sampling_id` and
`resolution_id`, but preserves `semantic_id`. Existing calibration remains
applicable to the same abstract difficulty semantics. It is not accepted for a
different compiled task build: if resampling changes `task_build_id`, it also
changes the task-bound calibration ID. Changing challenge or evaluation power
always changes the resolved `semantic_id` and therefore the task-bound ID.
Reports state which override caused invalidation.

Randomness is also purpose-separated. Public instances, hidden evaluation,
and mutations derive independent seeds from a master seed, purpose label, and
coordinates. Reusing an instance coordinate under a different purpose does
not reuse its random stream.

## Pinned agent systems

Solve rate is a property of a complete agent system, not merely a model name.
A calibration descriptor pins:

- a required nonempty provider and an operator-pinned immutable model revision;
- an exact harness commit as 40 or 64 lowercase hexadecimal characters;
- tool policy;
- token, time, and other budgets;
- network policy with a required Boolean `enabled` value and any applicable
  allowlist;
- evaluation date.

Use `pin_agent_system()` to derive `agent_system_id`. The hash covers the
versioned wrapper containing both `schema_version` and the complete descriptor,
not just the descriptor object. The implementation requires a nonempty
`model_revision`; choosing a genuinely immutable provider revision is an
operator responsibility. Trials from different IDs are never pooled.

A v2 trial file has this shape:

```json
{
  "schema_version": "paper2ale.calibration-trials/v2",
  "agent_systems": [
    {
      "schema_version": "paper2ale.agent-system/v1",
      "agent_system_id": "agent_system_<derived digest>",
      "descriptor": {
        "provider": "example",
        "model_revision": "frontier-model@exact-revision",
        "harness_commit": "0123456789abcdef0123456789abcdef01234567",
        "tool_policy": {"shell": true, "browser": false},
        "budgets": {"tokens": 100000, "wall_seconds": 3600},
        "network_policy": {"enabled": false, "allowlist": []},
        "evaluation_date": "2026-08-13"
      }
    }
  ],
  "trials": [
    {
      "trial_id": "trial-001",
      "task_id": "hnn-hard-variable-nbody",
      "task_build_id": "task-build_6ba782515180c229d82492f61f16c4f85f16e1b2152aa8ce8dae3c66e590d431",
      "level": "hard",
      "agent_system_id": "agent_system_<derived digest>",
      "semantic_id": "task_calibration_<derived digest>",
      "passed": false,
      "score": 0.31,
      "seed": 17,
      "attempt": 1
    }
  ]
}
```

The envelope and IDs are strict: `agent_system_id` must equal the canonical hash
returned by `pin_agent_system()`, and a trial's `semantic_id` must equal
`derive_task_calibration_id` for its level, `task_id`, and `task_build_id`.
In verified-catalog mode, invented or cross-build task-build claims are
rejected. Without a catalog, Paper2ALE can validate only ID syntax and internal
derivation; it cannot prove that a claimed task build exists.

Every v2 trial has exactly ten fields and no extras: `trial_id`, `task_id`,
`task_build_id`, `level`, `agent_system_id`, `semantic_id`, `passed`, `score`,
`seed`, and `attempt`. `trial_id` must be globally unique, at most 128
characters, one portable path component, and not a Windows device name.
`seed` and `attempt` are nonnegative integers. The complete run coordinate
`(task_id, task_build_id, level, agent_system_id, seed, attempt)` must also be
unique. `passed` is Boolean and `score` is a mandatory finite number in
`[0, 1]`.

## Run calibration

```powershell
paper2ale resolve-difficulty hard
paper2ale resolve-difficulty hard --challenge-overrides challenge.json --evaluation-overrides evaluation.json --sampling-overrides sampling.json
paper2ale resolve-difficulty hard `
  --task-id hnn-hard-variable-nbody `
  --task-build-id task-build_<64-hex-digest> `
  --calibrated-semantic-id task_calibration_<derived-digest>
paper2ale calibrate calibration-trials-v2.json
paper2ale calibrate calibration-trials-v2.json `
  --project dist/hnn-hard-grounded-suite/b-<build-prefix>/project.lock.json `
  --catalog dist/hnn-hard-grounded-suite/b-<build-prefix>/catalog.json
```

Without `--task-id` and `--task-build-id`, `resolve-difficulty` reports the
abstract difficulty resolution with `calibration_identity_scope` set to
`difficulty_only`; it will not validate a persisted calibration ID. A
`--calibrated-semantic-id` is accepted only with both task-binding flags.

For each exact task build, level, and agent system, the report includes:

- trial count, passed count, pass rate, and Wilson confidence interval;
- target band and minimum trial count;
- `calibrated`, `too_easy`, `too_hard`, `inconclusive`, or
  `insufficient_trials` status;
- finite score mean, median, range, standard deviation, and confidence
  interval;
- cross-level behavioral monotonicity with uncertainty.

Schema, agent-system, task-calibration semantic-ID, catalog, and identity
errors are hard pre-report gates; the CLI exits with status 2 instead of
emitting a partial calibration report.

For v2, `--project` and `--catalog` are inseparable. The project must be the
exact canonical `project.lock.json` beside a literal, current-compiler
`catalog.json` in a complete manifest-valid candidate or release build. The
verified pair checks the build's project/task set, nested task-build and QA
identities, each trial's exact `task_build_id`, supported family level, and
level selected by the build. `--catalog` is rejected for legacy v1 trials.

Running v2 without either flag remains useful for strict-format checks and
summaries, but the result records `build_catalog_verified: false`; claimed
task-build provenance remains unverified. `all_calibrated` describes only the
statistical and monotonicity result. A release-usable claim additionally
requires `verified_claim_ready: true`, which is possible only when those
targets pass under a verified catalog/project-lock pair. The CLI exits with
status 2 for every no-catalog v2 report, including one with
`all_calibrated: true`.

One verified catalog binds one selected build and level for each task, so the
current CLI cannot perform a verified cross-level comparison across distinct
task builds. Such cross-level comparisons are available only in the no-catalog
exploratory summary mode.

Cross-level checks remain agent-system specific. Overlapping uncertainty
intervals are inconclusive, not proof of monotonic difficulty.

## Builder consumption

Task builders receive resolved controls, consume them in deterministic data
and evaluation generation, and emit a content-bound difficulty consumption
manifest. Compilation fails when a family claims support but omits, alters,
or merely relabels the controls.

Benchmark sampling controls how many variants are emitted. Challenge controls
must materially change an episode. Evaluation-power controls must materially
change hidden evaluation. These roles should remain separate in custom
profiles and task-family implementations.

The generic compiler records per-template control consumption in
`author/difficulty_control_audit.json`:

| Template | Challenge/sampling controls | Evaluation-power controls |
| --- | --- | --- |
| `numeric-affine-v1` | instance count, input-complexity scale, masked fraction, constraint count; noise scale only when public noise is enabled | hidden-case count, threshold scale, rollout-horizon scale, adversarial-case count; required-pass fraction only with multiple metrics |
| `table-filter-sort-v1` | instance count, input-complexity scale, constraint count | hidden-case count, adversarial-case count |
| `json-group-aggregate-v1` | instance count, input-complexity scale, constraint count | hidden-case count, adversarial-case count |

An explicit non-default override for a control that the chosen template cannot
consume is a compilation error. This proves deterministic structural effects;
it does not empirically establish a frontier-model solve rate.

### v0.3 compatibility boundary

The shipped HNN and generic project files still use the v1 task-selection
shape because those builders predate the three-axis schema. The compiler maps
the core v1 controls to an aligned v2 view during audit, verifies that
instance count is sampling-only, and records the v2 semantic, sampling, and
resolution IDs. `resolve-difficulty` is the native v2 API for independent
axis overrides and custom v2 profiles.

V2 calibration currently resolves the built-in v2 profile. Its optional exact
build verification uses the required `--project`/`--catalog` pair described
above; it does not consume custom v1 project controls or target bands. Legacy
v1 calibration can consume those profiles but is deprecated and does not
provide publication-grade pinned-system or exact-task-build semantics.
Native v2 selections embedded directly in project task blueprints are a
future schema migration, not a v0.3 claim.

## Interpretation

The built-in levels are structural starting points. “Hard” does not mean hard
for every frontier model or agent. That claim requires enough trials from
explicitly pinned agent systems, current task-bound calibration IDs,
uncertainty-aware target fit, and supported cross-level behavior.
