# Verification report: disordered-sector-audit-v1

## Decision

- Status: `needs_agent_calibration`
- Provisional difficulty: `structurally_hard_candidate`
- Exact build: `sha256:9dc29e54c250afdb07aa10391431147535ece606b2f4eee3cd9fcd0c00cc6b73`
- Frontier-agent calibration: not run
- Collaborator-review disposition: accepted as a locally verified candidate.
- Hardened evaluator re-audit: pass; no remaining collaborator-review blocker.
- Blocking issues for scored/public release: pinned-agent calibration, independent scientific expert review, production OS sandboxing/peak-RSS measurement, secret-seed rotation, and ALE publication integration remain pending.

## 1. Source and provenance

- Paper/version: arXiv:1411.0660v2, revised 2014-12-23; exact source bytes and hash are recorded in the parent `authoring/source_manifest.yaml`.
- Official code repository and dataset: none used or redistributed for this task.
- Instances: independently generated finite periodic spin sectors from `private/trusted/generate_instances.py`; retired and three hidden suites use independent `SeedSequence` children.
- Licenses: task code and generated numeric inputs are independently authored repository assets; source-paper bytes remain author-only.
- Source conflicts/limitations: the source reports finite-size MBL-edge evidence, but this benchmark deliberately targets only a supplied-ensemble joint-signature claim and forbids a thermodynamic transition or mobility-edge conclusion.
- Grounding: the source workflow combines fixed-magnetization exact diagonalization, reversed extremal-energy normalization, energy packets, adjacent-gap ratios, real-space EE, participation entropy, subsystem magnetization fluctuations, disorder-realization binning, and evidence comparison.
- Source handling: no provider command or official executable was run.

## 2. Target leaf and workflow boundary

- Target leaf: `leaf-joint-finite-size-signatures` — on the generated finite ensembles, weak-disorder packets have more GOE-like/larger adjacent-gap ratios and larger real-space entanglement and participation entropies than paired strong-disorder packets.
- Scientific scope: finite supplied ensembles only; no thermodynamic phase boundary is inferred.
- Included operations: fixed-sector basis; periodic spin-one-half Hamiltonian; reusable full dense eigensystem; reversed normalized-energy packet; gap/EE/S1/S2/magnetization observables; realization-first means and SEM; evidence-linked conclusions.
- Public boundary: one retired experiment, complete formulas/conventions, executable/result schemas, qualitative criteria, and resource limits.
- Private boundary: fresh fields/sectors/queries, oracle rows, exact tolerances/weights, mutants, and security probes.
- Derivation type: reported workflow slice with grounded independently generated instances and an explicitly defined realization-balanced extension.

## 3. Specification closure

| Solution-critical decision | Disclosed | Inferable | Method-agnostic | Invalid hidden dependency | Evidence |
| --- | ---: | ---: | ---: | ---: | --- |
| Bit/site/spin convention and fixed-sector basis order | yes | no | no | no | `participant/TASK.md` sections 1-2 |
| Field sign, spin-one-half coefficients, and periodic bond | yes | no | no | no | section 2 |
| Reversed energy target, eligibility, tie break, and zero-based rank | yes | no | no | no | section 3 |
| Wraparound contiguous partition and natural-log EE/S1/S2 | yes | no | no | no | section 4 |
| Magnetization mean and centered variance | yes | no | no | no | section 4 |
| Equal-realization means and `ddof=1` realization SEM | yes | no | no | no | section 5 |
| Dense/vectorized implementation details | no | no | yes | no | behavioral evaluator |
| Exact output IDs, fields, ordering, safety, and limits | yes | no | no | no | sections 6-8 |

All rows closed: yes.

### Paper-blind specification review

- Reviewer: fresh subagent instructed to read only `participant/` and not inspect the source or private/author trees.
- Initial result: fail, correctly identifying zero-based rank, input-domain, degeneracy, identifier, order, count, and comparison-alignment gaps.
- Resolution: all material gaps were added to `participant/TASK.md` and enforced by the trusted loader; abs-and-rel tolerance semantics are public while exact evaluator thresholds correctly remain private.
- Final result: **pass**, with no material ambiguity and no residual statistical-support semantics.
- Full record: `author/paper_blind_review.md`.

## 4. Intrinsic difficulty audit

- Meaningful operations: 9; dependency depth: 9; branch count: 4. The operation IDs, four required participant artifact IDs, and private-rubric artifact IDs exactly match the parent workflow graph and selected candidate record.
- Tools: Python standard library and NumPy 2.3.5.
- Required participant artifacts: exactly one submitted reusable executable `solution.py`; each evaluation execution produces the other three parent-linked artifacts as the `state_rows`, `aggregate_rows`, and `conclusions` sections of its requested `RESULT_JSON`.
- Independent challenges: many-body symmetry-sector construction; dense spectral caching and target semantics; sector-to-tensor Schmidt reconstruction; several normalization-sensitive eigenvector observables; clustered statistics with unequal packet sizes; hidden-sector/query generalization; evidence provenance.
- Expected human expert effort: 8-20 hours.
- Not a leaf question: computing one entropy or one gap ratio cannot pass the state, aggregate, hidden-query, and evidence rubrics.
- Not clone-and-run: no source implementation contains the generated instances or benchmark interface, and network access is off.
- Difficulty label remains provisional because no pinned frontier-agent trial has run.

### Shortcut results

| Shortcut | Result | Evidence |
| --- | --- | --- |
| Hard-code/copy retired result | rejected at stale experiment identity | robustness probe |
| Hard-code `exchange=1` | rejected, score 0.333 | `unit_exchange` mutant on nonunit hidden cases |
| Computational-basis Shannon entropy as EE | rejected, score 0.40 | `shannon_entanglement` mutant |
| Natural-log/base-2 confusion | rejected, score 0.40 | `log2_entanglement` mutant |
| Treat states as independent realizations | rejected, scores 0.70/0.80 | grouping and SEM mutants |
| Fabricate internally consistent aggregate evidence | rejected, score 0.70 | `stale_evidence` mutant |

## 5. Privileged oracle run

- Command: `python -B tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/author/oracle/generate.py --task-root tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit --check`
- Environment: Python 3.12.13, NumPy 2.3.5, one BLAS thread, CPU only.
- Runtime: 1.778 s and 1.788 s on two byte-deterministic generations in the current independent repeat.
- Outputs: one retired input/reference, three hidden inputs/references, and `oracle_summary.json`; nine generated files total.
- Signal validity: all 36 weak-minus-strong target effects across retired/hidden query-metric pairs are positive. Hidden minimum gap-ratio effect is approximately 0.05273; entropy and participation effects are materially larger. `positive_effect` means only `effect > 0`, not statistical significance.
- Status: pass.

## 6. Clean-room public-input reference run

- Construction: each run used a fresh temporary tree containing only copied `solution.py`, copied retired experiment input, an initially empty output directory, and the copied defense-in-depth guard; author/private trees and references were outside the child.
- Command shape: `python -I -B guard.py source/solution.py input output/result.json STAGE_ROOT`.
- Network/process/link policy: audit-denied; the child received a host-environment allowlist and console/result growth was bounded live.
- Runtime: 0.160 s and 0.161 s in two byte-identical runs in the current independent repeat.
- Output: one 79,873-byte result JSON; SHA-256 `2cbebda0376a7772bce7e3be2279784f0d94e1820e73460271383e9044a1f54b` in the recorded run.
- Public oracle-normalized RMSE: spectral `3.08e-7`, entanglement/participation `1.06e-6`, magnetization `4.78e-7`, aggregation `1.03e-7`, evidence `1.02e-7`; these are errors measured in units of the much larger allowed tolerance.
- Hidden private evaluator: score 1.0 and pass on two deterministic runs; every per-experiment mandatory score is 1.0; grader runtimes 1.813 s and 1.722 s in the current independent repeat.
- Hidden access audit: pass.

## 7. Independent alternative

- Independence: vectorized basis-bit arrays, vectorized Hamiltonian diagonal/off-diagonal assembly, reduced-density-matrix `eigvalsh` for EE, and independent aggregation replace bit loops, coefficient-matrix SVD, and the reference organization.
- Command: `python -B author/alternative_solver/solution.py --experiment EXPERIMENT --output RESULT`.
- Hidden evaluator: score 1.0 and pass in two byte-deterministic grader runs; runtimes 1.354 s and 1.325 s in the current independent repeat.
- Mean normalized-by-tolerance RMSE: spectral `1.63e-6`, EE/participation `8.30e-7`, magnetization `1.08e-6`, aggregation `3.11e-7`, evidence `5.70e-7`.
- Raw participant-format determinism: two fresh guarded public-case runs emitted byte-identical 79,890-byte `result.json` files (SHA-256 `48fb3ff685fd72b8373adec3972790af1ebe9dd4e9c9a2a354d9a5b6d17cab66`) in 0.133 s and 0.132 s in the current independent repeat; the public truth score was 1.0.

## 8. Tolerance calibration

The grader uses `allowed_error=max(abs_tol,rel_tol*abs(reference))` elementwise and normalized RMSE. Exact values remain private as required.

| Metric | Independent/repeat disagreement | Abs tolerance | Rel tolerance | Justification |
| --- | ---: | ---: | ---: | --- |
| eigenvalue, normalized energy, gap ratio | below `2e-12` on current suites | `2e-8` | `1e-7` | wide cross-platform eigensolver margin; exact eigenvector bytes/signs ungraded |
| EE, S1, S2 | SVD versus reduced-density route below `2e-12` | `2e-8` | `1e-7` | protects near-zero values while decisively rejecting log/observable substitutions |
| magnetization mean/variance | below `2e-12` | `2e-8` | `1e-7` | diagonal moments are well-conditioned; absolute term handles means near zero |
| realization means/SEM | below `1e-12` | `5e-8` | `2e-7` | propagates state tolerance and reduction order while rejecting packet weighting |
| conclusion effects | below `1e-12` | `5e-8` | `2e-7` | effects are differences of tolerant aggregate means; IDs/flags are exact |

Correct and alternative implementations are many orders inside tolerance. Independent projected-Kronecker Hamiltonian, product-state, and Bell-state fixtures have maximum errors of `1.11e-16`, `0`, and `4.44e-16`. Every realistic scientific mutation remains far outside its mandatory metric.

## 9. Scientific mutant results

All programs were complete, schema-valid, executable on all hidden experiments, and rejected scientifically.

| Mutant | Category | Score | Result |
| --- | --- | ---: | --- |
| `pauli_scale` | operator normalization | 0.00 | rejected |
| `unit_exchange` | ignored input exchange | 0.333 | rejected; only the unit-exchange hidden case remains correct |
| `open_boundary` | Hamiltonian topology | 0.00 | rejected |
| `wrong_energy_normalization` | energy convention | 0.00 | rejected |
| `one_sided_packet` | packet selection | 0.00 | rejected |
| `shannon_entanglement` | observable substitution | 0.40 | rejected |
| `log2_entanglement` | logarithm convention | 0.40 | rejected |
| `s2_ipr` | participation definition | 0.40 | rejected |
| `mz_second_moment` | centered moment | 0.65 | rejected |
| `naive_aggregation` | realization weighting | 0.70 | rejected |
| `sem_over_states` | cluster uncertainty | 0.80 | rejected |
| `stale_evidence` | fabricated but relationally consistent evidence | 0.70 | rejected by aggregation/evidence metrics |

All twelve mutants emit the complete schema and cross the structural/execution gates. Each fails its declared scientific metric below 0.92, and every total score is at most 0.80, leaving margin below the 0.95 pass threshold.

## 10. Metamorphic and invariant tests

| Test | Expected relation | Maximum observed error | Status |
| --- | --- | ---: | --- |
| cyclic site relabeling | relabel fields and cut together; graded observables invariant | oracle `1.69e-13`; solvers `1.64e-13` | pass |
| uniform field shift | fixed-sector eigenvectors/normalized outputs invariant; known energy constant | oracle `2.14e-13`; solvers `1.48e-13` | pass |
| common Hamiltonian scaling | eigenvalues scale; ratios/eigenvectors/normalized outputs invariant | oracle `2.43e-13`; solvers `6.91e-14` | pass |
| global spin flip in nonzero sector | `n_up -> L-n_up`, fields negate, subsystem mean flips sign | oracle `1.58e-13`; solvers `9.73e-14` | pass |
| record permutation | canonical result unchanged | `0` | pass |

The solver-level layer materializes fresh synthetic experiments and runs both participant-facing implementations through the same staged guard; it then truth-scores every transformed result and relationally compares state rows, aggregates, and conclusions. The largest solver aggregate and conclusion discrepancies are `2.86e-14` and `2.13e-14`; the `2e-10` metamorphic ceiling is over 800 times the largest oracle or solver discrepancy.

## 11. Evaluator robustness

- Contract identity: the ledger carries canonical task ID `disordered-sector-audit-v1`; evaluator metric IDs and mandatory keys exactly match the grader ledger and mutant manifest underscore IDs.
- Determinism: reference and alternative grader runs from different CWDs and hash seeds produce byte-identical JSON and process status.
- Malformed JSON, partial schema, NaN constant, stale retired result, oversized result, syntax error, and extra submission file: hard-gate rejection.
- Private-file and normalized traversal reads, network sockets, subprocesses, `os.startfile`, link/symlink creation, rename, frame inspection, and a builtins-global-tamper oracle-theft attempt: audit-denied. POSIX-only spawn/fork/forkpty probes are explicitly `platform_unavailable` on this Windows host.
- Explicit hard-coded retired-reference program: stale hidden identity rejection.
- Hard-linked `solution.py` and hard-linked result JSON: live rejection; link multiplicity must persist across repeated `lstat` checks to avoid transient Windows metadata false positives.
- Cross-platform hardlink probing: `OSError`/unsupported creation is recorded as structured `platform_unavailable:<exception-type>` rather than aborting verification; when creation succeeds, rejection remains mandatory. A simulated `PermissionError` branch confirms the structured status contract.
- File/root symlink submission tests: attempted and recorded `platform_unavailable:OSError` because this Windows account lacks link privilege; in-child `os.symlink` creation is separately audit-denied.
- Oversized `solution.py`: live rejection.
- Context corruption: wrong state condition, aggregate epsilon, and conclusion/aggregate relation are live hard-gate rejections.
- Combined stdout/stderr and result growth are polled and terminated before unbounded buffering. A mandatory post-exit combined console-size check closes the fast-exit race; separate fast `os.write` stdout and stderr floods are live rejected. Staged source/input hashes and the exact output inventory are checked after execution.
- Runtime contract: each of the three hidden cases receives at most 300 seconds, leaving 300 seconds for evaluator orchestration and validation inside the disclosed 20-minute total budget.
- Execution isolation caveat: closure-backed Python audit hooks, resolved path confinement, environment allowlisting, and fresh projections are defense in depth, not a complete security boundary. Production ALE must provide OS/container isolation, filesystem mounts, process-tree/memory quotas, and network policy.

## 12. Hidden-instance validity

- Generator: `private/trusted/generate_instances.py` with one root entropy and four independent child streams.
- Retired: `L=8,n_up=4`, two energy/cut queries, ten records.
- Hidden alpha/beta/gamma: `L=9,10,12`; half and non-half sectors; exchange values `1.0,1.35,0.8`; new amplitudes, fields, query IDs, reversed targets, wraparound cuts, and unequal packet sizes.
- Identifier audit: condition, record, comparison, and query IDs are opaque, disjoint from the retired public IDs, and disjoint across hidden suites; no hidden ID contains the public `weak`/`strong` role template.
- Query-specific packet audit: packet size varies across queries in all 28 hidden records, and 86 retired/hidden record-query reference row counts were checked against their individual `packet_size` values. Trusted loading independently enforces the public two-to-four-queries-per-record domain.
- Every generated review suite has a deterministic shuffled record order; hidden condition records are interleaved and private grading therefore exercises canonical record-order handling.
- Gamma is a grounded-generalization case (`L=12,n_up=5`) with three simultaneous queries and packet sizes exercising the disclosed bounds 2 and 15; it is not claimed as paper reproduction.
- Reference behavior: generator check requires every target conclusion to have positive weak-minus-strong effect, full comparison-descriptor matching, simple float64 spectra, and conditioned packet cutoffs. The measured minimum scaled eigengap is `3.15e-8`; minimum scaled cutoff margin is `1.04e-7`.
- Metamorphic nonzero-sector validity: separately confirmed by global spin-flip test.
- Public review instance: permanently retired.
- Production action: replace checked-in review streams with server-secret streams before scored release.

## 13. Participant package audit

- Inventory: four files, 21,092 bytes.
- Source title, authors, arXiv identifier, and journal citation: zero participant hits.
- Input sufficient and output contract explicit: yes after reviewer-driven closure.
- Artifact traceability: all four parent output IDs resolve; the verifier confirms one submitted source artifact and three runtime result sections.
- Environment and resource limits: explicit.
- Private/reference artifacts in participant package: none.
- Filesystem inventory: no bytecode cache, symlink/reparse point, hard-linked file, or special entry is present; these are now explicit package-audit failures.
- Public validator: executed on valid and extra-file submissions; it is structural only and contains no scientific answer.

## 14. Resource measurement

- Hidden maximum in this build: `L=12,n_up=5`, sector dimension 792, three queries per record; both participant-facing solvers execute it during every hidden grade.
- Separate bounded probe: `L=12,n_up=6`, dimension 924, dense matrix 6,830,208 bytes, two queries and 14 state rows.
- L=12 trusted half-sector probe runtime: 0.196 s in the current independent repeat.
- Full hardened local verification runtime: 49.126 s in the current independent repeat. The immediately preceding same-build pass took 47.0335 s; deterministic output hashes, scores, and build identity are unchanged.
- Peak RSS: not measured on this Windows host; production measurement remains pending.
- No L=14 scoring instance is included.

## 15. Reproduction commands

From repository root:

```text
python tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/scripts/verify.py
```

Author-only components:

```text
python -B tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/author/oracle/generate.py --task-root tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit --check
python -B tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/author/reference_solver/solution.py --experiment tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/participant/input/retired_experiment --output RESULT.json
python -B tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/private/grader/grade.py --participant tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/participant --submission SUBMISSION_DIR
```

## 16. Remaining risks and next actions

- Scientific: finite sizes diagnose a supplied-ensemble crossover only; they do not establish asymptotic localization or a mobility edge.
- Numerical: accidental degeneracy is excluded by generator validation; a future broader generator must preserve that contract or add subspace-aware evaluation.
- Statistical: four or five realizations per condition are enough for deterministic benchmark discrimination but not precision physics; `positive_effect` is intentionally a directional finite-ensemble flag, not uncertainty-aware significance.
- Security: replace audit-hook execution with ALE OS isolation before public scoring.
- Engineering: measure peak RSS and run symlink/junction probes on CI hosts with privileges.
- Release: rotate fixed review seeds, run ALE integration, obtain scientific expert review, and calibrate pinned frontier agents.

Recommended action: accept as a locally verified `structurally_hard_candidate` for collaborator review only. Retain `needs_agent_calibration`; do not claim public-release readiness, a thermodynamic mobility edge, or frontier difficulty.
