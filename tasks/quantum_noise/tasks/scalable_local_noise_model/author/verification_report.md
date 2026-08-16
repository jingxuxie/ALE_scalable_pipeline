# Verification report: local-junction-noise-model-v1

## Decision

- Status: `needs_agent_calibration`
- Provisional difficulty: `structurally_hard_candidate`
- Frontier-agent calibration: not run
- Blocking issues: pinned frontier-agent trials and collaborator review of both the synthetic validation-intervention model and the generic-classical/nonphysical `q*` abstraction
- Exact task build: `sha256:9716962c4c4f3338ef2b66a7aea69e10289c8575db33edd64cbadb81e8a62573` (all task files except this report and `task_spec.yaml`)
- Exact participant projection: tree SHA-256 `f095d644815187489501b6a83567f01888b929b47164156f140b9bc6f0841834`

## 1. Source and provenance

- Paper/version: *Efficient learning of quantum noise*, arXiv:1907.13022v2, 16 April 2021
- Pinned paper SHA-256: `4867308d9d0033d9d0cbe1cf723cb00d569c4b8cd22588b4c1ba611af93c7684`
- Official code: `rharper2/Juqst.jl` commit `533d0c46f29638e0a235ab58ce2cd86591a4e966`, MIT
- Official data evidence: `rharper2/EfficientLearningDataSet` commit `11624f8cb32f81fca4e2f8c7a570d8e09672f659`, CC0; incomplete local worktree and not used
- Participant data: newly generated neutral synthetic JSON/JSONL only
- Paper/code conflicts relevant here: the paper claims scalable bounded-degree GRF learning, while the inspected source reconstruction helper hard-codes enumeration over `2**14`; source zero-support handling also uses an undisclosed `1e-8`/mean-fill heuristic. Neither behavior is copied into the task.
- Grounding: the paper's strictly positive GRF factorization and marginalization scalability claim; source marginal fitting/reconstruction is evidence only. The disclosed junction-tree model, independent count noise, generic DP queries, and validation audit are a labeled grounded extension.
- The latent q* is a generic classical binary junction-tree law over abstract error indicators. It is not asserted to be an observed-error-rate distribution of a locally Clifford-twirled Pauli channel, and no inverse 2/3 visibility/Pauli-support nonnegativity constraint is imposed. The task evaluates the paper-motivated bounded-local inference workflow, not physical channel realizability.

## 2. Target leaf and workflow boundary

- Target leaf: `claim-leaf-bounded-local-grf-scalability`
- Scientific meaning: a correlated binary noise law with bounded local structure can be learned and used without storing or traversing all `2**n` states.
- Participant operations: parse arbitrary local axes/layouts; smooth and reconcile overlapping counts; construct normalized root/conditional factors; implement sum-product evidence queries; predict parity interactions; compute uncertainty-aware ranks; produce recomputable diagnostics.
- Private rubrics: latent factors and clique marginals, fresh partial queries, injected validation labels, category scores, exact tolerances and weights.
- Public boundary: one retired 47-variable synthetic review instance, complete schemas, model equations, qualitative metrics, hidden size ranges, and a structural validator.
- Private boundary: six regenerated review cases with 55-88 variables, opaque instance IDs, hidden seeds/truth/queries/labels, exact score contract, oracle outputs, and 11 mutants.
- Derivation: grounded extension of a reported workflow and scalability claim.

## 3. Specification closure

| Solution-critical decision | Disclosed | Inferable | Method-agnostic | Invalid hidden dependency | Evidence |
| --- | ---: | ---: | ---: | ---: | --- |
| Binary/table-axis convention | yes | no | no | no | `TASK.md` table rule and example |
| Tree, separator, and joint-factor semantics | yes | no | no | no | `TASK.md` model section |
| Finite-shot reconciliation estimator | no | no | yes | no | predictive scoring; disclosed baseline |
| Query event and marginalization meaning | yes | no | no | no | `TASK.md` queries |
| Validation event, z score, ties, and top-k | yes | no | no | no | `TASK.md` validation/audit |
| Output schemas and diagnostics | yes | no | no | no | `TASK.md` outputs |
| DP implementation/data structures | no | no | yes | no | behavior and resources are evaluated |
| Environment and hidden bounds | yes | no | no | no | `TASK.md` limits |

All rows closed: yes.

### Paper-blind specification review

- Reviewer/context: two independent paper-blind reviews, including a fresh literal audit of the finalized public package
- Source access confirmed absent: yes
- Initial gaps: identifiability/objective, table axes, query semantics, validation-interaction definition, malformed behavior, and public metric directions
- Resolution: latent disclosed-family predictive target, root/conditional representation, worked index example, exact event/z/rank definitions, strict schemas, ranges, and qualitative behavioral metrics added
- Intended method freedom understood: statistical estimator and DP data structures are free; induced behavior is scored
- Second-pass literal findings: clarified validation/diagnostic isolation, exact decimal byte caps, source encoding/size, `audit_top_k`, count/validation invariants, positive smoothing, binary64 ties, induced separator TV, and exact declared bounds
- Remaining material ambiguities: none after revision
- Final restricted-package verdict after validator amendments: `PASS`
- Status: pass; details in `author/spec_review.md`

## 4. Intrinsic difficulty audit

- Meaningful operations: 7
- Dependency depth: 6
- Branches: model recovery, generic queries, validation audit, and diagnostics
- Tools: Python standard library and NumPy
- Required artifacts: submitted program plus four linked per-instance outputs
- Independent challenges: noisy overlap reconciliation; arbitrary layouts and bit axes; normalized bounded-width inference; higher-order parity prediction; statistical anomaly ranking; distribution shift
- Expected expert effort: 8-16 hours for a robust implementation and adversarial tests
- Not a leaf-node question: the target claim anchors a backward workflow from noisy local observations through a reusable model, queries, and model-mismatch diagnosis.
- Not clone-and-run: source identifiers/code are absent, source helper is size-specific, and hidden instances use a new neutral contract.
- Resource enforcement: public `n=47` makes a float64 global table exceed 1 PiB; hidden `n` reaches 88. Junction-tree factors stay below 128 cells each.

### Shortcut attempts

| Shortcut/baseline | Result | Why it fails |
| --- | --- | --- |
| Reverse local-axis significance convention | rejected, score 0.369930 | latent marginals and queries are wrong |
| Ignore separator context | rejected, score about 0.50 | destroys local conditional correlations |
| Uniform root marginal | rejected, score about 0.81 | root and downstream event behavior shift |
| Multiply singleton answers for cross-clique evidence | rejected, score about 0.83 | mandatory model/sidecar consistency fails |
| Remove smoothing | rejected, score about 0.92 | sparse OOD category floors fail |
| Rank residuals ascending | rejected, score 0.75 | exact audit consistency and anomaly metric fail |
| Over-shrink one three-way-junction case | rejected, score 0.863345 | clears aggregate/category/topology gates but fails the per-case query floor |
| Fit from validation outcomes | hard-gate rejection, score 0 | paired validation-only intervention changes the model |
| Depend on randomized string hash | hard-gate rejection, score 0 | same input differs across hash seeds and working directories |
| Stale or partial model | hard-gate rejection, score 0 | IDs/inventory do not match hidden input |

## 5. Privileged oracle run

- Command: `python -B tasks/quantum_noise/tasks/scalable_local_noise_model/author/oracle/generate.py`
- Environment: Python 3.11+, NumPy 2.3.5, CPU, network unused
- Source-only information used: private seeds, latent factors, private queries, and anomaly labels; no official provider command executed
- Runtime: 3.629 seconds for two clean isolated regenerations, fixture comparison, truth loading, and perfect-score validation in the final unified verification
- Output: public and six hidden exact model/query/audit/diagnostic artifact sets plus truth manifests
- Evaluator score: 1.0
- Status: pass and byte-deterministic across clean regeneration; two concurrent targeted oracle checks also passed without touching the live task tree

## 6. Clean-room public-input reference run

- Construction: temporary directory with only copied `participant/`, one copied solver file, Python/NumPy, and an empty output directory
- Solver: `python -B solution.py --input participant/input --output output`
- Network/path policy: safe-path/no-user-site child with minimal environment and closed descriptors; captured audit policy denies sockets, process control, ctypes/registry/_winapi, descriptor and relative-low-level access, reads outside input/source/runtime, and every mutation outside output
- Public runtime: under 1 second after signed-parity and two-pass-belief optimization
- Latest measured public runtime: 0.206-0.213 seconds; hidden grader runtime: 5.730-5.846 seconds for six primary, same-input-repeat, and validation-paired cases
- Peak memory: not portably measured; artifacts and local tables are below 2.5 MiB and 128 cells per clique
- Output: `model.json`, `query_results.jsonl`, `audit.json`, `diagnostics.json`
- Metrics: model recovery `0.8644995327`; held-out queries `0.9017814591`; all consistency metrics `1.0`; anomaly ranking `1.0`
- Total score: `0.9260558304`
- Hidden access audit: pass
- Status: pass

## 7. Alternative valid implementation

- Independence: uses empirical-Bayes shrinkage of each separator-context conditional toward the pooled new-variable marginal, rather than the direct half-count conditional estimator. It has its own inference/output implementation and is not byte-identical.
- Metrics: model recovery `0.8699753092`; held-out queries `0.8997810592`; all consistency/ranking metrics `1.0`
- Latest runtime: 0.181 seconds public solve and 5.752 seconds for the six-case hidden grader with repeated and paired executions
- Total score: `0.9274322442`
- Status: pass

## 8. Tolerance calibration

| Metric | Reference variation | Absolute tolerance | Relative tolerance | Justification |
| --- | ---: | ---: | ---: | --- |
| Model recovery | sampling/statistical, Hellinger 0.017-0.099 for direct reference | quality band 0.045 excellent, 0.160 minimum | n/a | separates ordinary and sparse-count estimation quality without requiring exact estimator |
| Held-out query recovery | log-RMSE 0.026-0.150 across cases | probability floor 1e-14; band 0.055-0.260 | n/a | log scale treats rare conjunctions fairly; category floors preserve OOD behavior |
| Query/model consistency | float64 roundoff below 1e-13 | 3e-10 | 3e-8 | over 100x independent evaluator/solver disagreement |
| Audit numeric consistency | signed-message/enumeration disagreement below 1e-13 | 8e-9 | 3e-7 | covers accumulated parity and z arithmetic; ranks/IDs remain exact discrete checks |
| Diagnostics | two-pass/direct marginal disagreement below 1e-13 | 5e-9 | 2e-7 | recomputation order may differ while scientific values agree |

- Hidden instance count: 6 fixed review seeds; public and hidden scored seeds are distinct
- Aggregation: macro mean plus category, topology, and per-case floors. The private per-case model/query floors are 0.40/0.40; topology floors are 0.50/0.45. Reference per-case minima are 0.532690/0.536666 and alternative minima are 0.557435/0.520594, leaving statistical margin while preventing one failed case from being averaged away.
- Baseline-relative rule: none
- Reference distribution: two ordinary, two anomaly, low-shot OOD, and wider/larger OOD

## 9. Mutant results

| Mutant | Category | Expected | Observed score | Pass/fail |
| --- | --- | --- | ---: | --- |
| wrong_endian | coordinate convention | fail | 0.369930 | fail |
| ignore_context | omitted interaction | fail | 0.498388 | fail |
| uniform_root | omitted marginal | fail | 0.814758 | fail |
| no_smoothing | sparse-support error | fail | 0.915114 | fail |
| query_product | cross-clique independence | fail | 0.826056 | fail |
| ascending_audit | wrong ranking direction | fail | 0.751371 | fail |
| single_topology_failure | concealed case failure | fail | 0.863345 | per-case floor fail |
| validation_contamination | validation leakage | fail | 0.00 | paired-isolation hard-gate fail |
| hash_nondeterminism | nondeterministic output | fail | 0.00 | same-input hard-gate fail |
| stale_identity | stale cache | fail | 0.00 | hard-gate fail |
| truncate_tree | partial model | fail | 0.00 | hard-gate fail |

Covered categories: axis convention, context/interaction omission, marginal omission, zero-support handling, query semantics, ranking direction, concealed case failure, validation leakage, nondeterminism, stale output, and incompleteness.

## 10. Metamorphic and invariant tests

| Test | Expected relation | Status |
| --- | --- | --- |
| Evidence partition | `q(E)=q(E,X=0)+q(E,X=1)` | pass |
| Parity complement | even plus odd probability equals one | pass |
| Signed parity message | agrees with explicit parity assignment sum | pass |
| Two-pass clique belief | agrees with direct evidence DP | pass |
| Clique/count record reorder | semantic probabilities unchanged | pass |
| Validation isolation | model/query bytes unchanged; audit changes | pass |
| Arbitrary-submission validation pair | model/query/non-audit diagnostics semantically identical; audit changes | pass on all hidden cases |
| Same-input determinism | all four parsed artifacts identical across hash seeds and working directories | pass on all hidden cases |
| Small explicit joint | DP agrees with enumerated 8-variable joint | pass |

Maximum observed numerical errors were `1.39e-17` for evidence partition,
`2.78e-16` for signed parity, `1.67e-16` for two-pass clique marginals, and
`4.44e-16` for DP versus the explicit small joint. Record-order error was zero.

## 11. Evaluator robustness

- Repeated evaluator runs: required byte-identical JSON and parsed result under different hash seeds/cwds
- Arbitrary-submission determinism: every hidden case is executed twice with different `PYTHONHASHSEED` and cwd; all four parsed artifacts must match
- Arbitrary-submission validation isolation: every hidden case is also executed on complemented validation outcomes; model, queries, and non-audit diagnostics must match while audit values change
- Malformed, partial, NaN/Inf, oversized, stale output: rejected safely
- Fabricated self-reported values: recomputed; consistency score fails
- Public hard-coding: hidden IDs/layouts/queries and stale-identity gate defeat it
- Private-file access, network, subprocess/exec/fork/kill, ctypes, registry/_winapi, fd/dir_fd, chdir, output traversal, unknown/pathlike audit paths, all mutation families, and monkeypatched policy helpers/flags: audit-guard self-test denies all applicable events
- Output capture: text and binary stdout/stderr paths reject output beyond 65,536 bytes; production isolation must also enforce the cap at the pipe/process boundary before host buffering
- Host integrity backstop: SHA-256 snapshots verify the source tree, input tree, and case root outside output are unchanged after every candidate execution; sensitivity tests mutate and detect all three regions
- Verifier idempotence: oracle and mutant regeneration occur only in isolated temporary task copies, regenerated inventories match checked fixtures byte-for-byte, and a 92-file whole-task content snapshot is unchanged across the unified run
- Checkout stability: all 92 task files are UTF-8/LF, every committed generator writes LF bytes explicitly, and preflight rejects any carriage-return byte or invalid UTF-8 text
- Symlink and hardlink artifacts: rejected when platform creation is available; parser implements both checks on every platform
- Output/source inventories: exact; extra and missing files fail
- Execution isolation: `-P -B -s`, minimal environment, closed inherited descriptors, timeout, captured audit policy, and post-run integrity checks; production ALE still needs an OS sandbox for hard memory/process isolation

## 12. Hidden-instance validity

- Generator: `private/generator/generate.py`, independently inspected Python/NumPy
- Varies: 47-88 variables in review build, width 4-7, chain/fork/branch topology, depth, root/clique/variable order, table axes, shots, sparse cells, query scopes, audit probes, and anomaly direction; hidden instance IDs are opaque and input files contain no class/category field
- Preserves: running intersection, exactly-once introduction, strictly normalized positive latent factors, independent multinomial clique tables, and query target `q*`
- Validation anomaly semantics: separate held-out interaction experiments may receive injected process interventions; training counts and latent query target remain `q*`
- References: oracle perfect; direct and shrunken estimators pass ordinary/OOD/anomaly categories
- Public review instance: marked retired
- Seed policy: fixed author seeds only for review; replace with server-secret seeds before scored release

## 13. Participant package audit

- Paper/source identifiers: removed; automated scan includes title, arXiv ID, author names, and repository identifiers
- Semantics: complete after paper-blind review
- Inputs/output schemas/resources: explicit and validator-backed
- Private artifacts in participant projection: none
- Public source lookup does not solve the new synthetic, size-generic workflow

## 14. Commands to reproduce verification

```text
python tasks/quantum_noise/tasks/scalable_local_noise_model/scripts/verify.py
```

The final integration run, including explicit task-root provenance resolution,
arbitrary-submission repeated/paired execution, and hardened security probes,
passed all nine required check groups in 69.290 seconds.

Direct clean-room-style public solve (run from the task root, substituting real
empty output-directory paths for the placeholders):

```text
python -B author/reference_solver/solve.py --input participant/input --output <empty-output>
python -B participant/software/validate_submission.py --input participant/input --output <output>
```

## 15. Remaining risks and next actions

- Scientific: collaborator should confirm that independent validation interventions are a suitable operational model for missed nonlocal interactions.
- Scientific abstraction: collaborators should explicitly judge whether a generic classical binary, nonphysical `q*` is an appropriate benchmark abstraction for the paper-motivated workflow; no inverse Pauli-visibility physicality is claimed or scored.
- Engineering: local audit hooks are defense-in-depth and cannot prove containment against unaudited native extensions or hostile code-object/runtime manipulation. ALE's OS sandbox must enforce process, memory, filesystem, network, and pre-buffer pipe-output limits.
- Calibration: no pinned frontier agent has attempted this exact build, so no frontier-hard claim is made.
- Release: regenerate scored instances from server-secret seeds and record the final content hash after collaborator changes.
