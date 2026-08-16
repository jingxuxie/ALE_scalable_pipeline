# Verification report: reusable-chebyshev-spectral-cache-v1

## Decision

- Status: `needs_agent_calibration`
- Provisional difficulty: `structurally_hard_candidate`
- Exact build: `sha256:439d24074b7efc721570f33b64e0433427dfa6488945274a4aedbd78ee4b3f54`
- Frontier-agent calibration: not run
- Blocking issues: independent scientific review, ALE publication integration and production resource measurement, a downstream participant-asset license, and pinned-agent calibration remain pending.

## 1. Source and provenance

- Paper/version: arXiv:1910.05194v2, revised 2020-03-13, 38 pages; pinned PDF SHA-256 `df4bea7b0fb8d4059bc16e0a20357912450cfaf63799cc2ac8ada97453dd3e82`.
- Official code repository and commit: KITE v1.0 Zenodo archive, commit `7bb1fc44d2b5a67ef65524fe33702e9c2cdef416`; archive SHA-256 `09c45bd2b4ac7f4bcb6a0bb7b4a51ed00e1c4ac017424ece38196ba0ee34fefd`.
- Dataset/version: independently authored deterministic synthetic Hermitian systems; no paper or official-source data bytes are redistributed.
- Licenses: the archive's `LICENSE.md` says LGPL-3.0 while its README and Zenodo metadata say GPL-3.0. The participant bytes are independently authored, but their downstream distribution license must still be selected.
- Paper/code/data conflicts: printed Eqs. 2.7 and 2.17 invert the moment normalization required by the orthogonality/reconstruction equations and official postprocessor. The public task therefore defines raw probe moments and the entire finite contraction explicitly.
- Grounded workflow evidence: Sec. 2(a), Eqs. 2.9-2.20, and Fig. 1 separate the expensive, energy-independent Chebyshev moment calculation from later many-energy/many-resolution reconstruction. The benchmark uses new finite synthetic systems and makes no claim to reproduce Fig. 1 numerically.
- Source handling: provider code was inspected but not executed. Archive members were traversal-audited before author-only extraction.

## 2. Target leaf and workflow boundary

- Target claim/result leaf: one energy- and broadening-independent Chebyshev cache can answer new retarded, advanced, density, broadening, and prefix queries without rerunning the sparse recurrence (`leaf-spectral-cache`).
- Why it is scientifically meaningful: it tests the reusable numerical object that enables many-energy response calculations, not a single plotted value.
- Included participant operations: assemble three complex Hermitian systems; validate affine scaling; run four probe recurrences through 384 orders; preserve probe-resolved raw moments; reconstruct several response branches and prefixes; produce recomputable diagnostics.
- Intermediate private-rubric artifacts: the submitted moment tensor is scored directly and contracted by the evaluator at 18 unseen tuples.
- Public boundary: all synthetic system/probe files, conservative bounds, formulas, branch conventions, units, output schemas, limits, and qualitative criteria.
- Private evaluation boundary: exact hidden tuples, reference arrays, tolerances, weights, pass gates, seeds, mutants, oracle, and grader.
- Derivation type: reported workflow slice with grounded synthetic instances.

## 3. Specification closure

| Solution-critical decision | Disclosed | Inferable | Method-agnostic | Invalid hidden dependency | Evidence |
| --- | ---: | ---: | ---: | ---: | --- |
| Hermitian edge orientation/conjugation and affine scaling | yes | no | no | no | `participant/TASK.md` |
| Probe normalization, conjugate inner product, `/N`, recurrence, order, and prefix | yes | no | no | no | `participant/TASK.md` |
| Complex root branch, physical eta, order-zero factor, and `1/a` Jacobian | yes | no | no | no | `participant/TASK.md` |
| Numerical algorithm and sparse data structure | no | no | yes | no | outcome-based evaluator |
| Output schemas, resource limits, and success criteria | yes | no | no | no | `participant/TASK.md` |

All rows closed: yes.

### Paper-blind specification review

- Reviewer/context: a fresh agent received only the participant package.
- Source access confirmed absent: yes.
- Task restatement: correct, including raw moment and finite-prefix semantics.
- Missing definitions or files identified: none after resolving a minor probe-axis wording ambiguity.
- Intended method freedom understood: yes; sparse recurrence and dense spectral decomposition are both valid.
- Material ambiguities resolved: yes.
- Status: pass; see `author/spec_review.md`.

## 4. Intrinsic difficulty audit

- Meaningful operation count: 6.
- Dependency depth: 5.
- Branch count: 3.
- Tools: Python standard library and NumPy.
- Required artifacts: three linked artifacts (`moments.npz`, `public_response.csv`, `diagnostics.json`).
- Independent challenge sources: heterogeneous sparse Hermitian assembly; long probe-resolved recurrence; normalization-sensitive reusable caching; complex branch/unit/prefix semantics; and cross-artifact evidence consistency.
- Expected human workflow and effort: 6-12 expert hours.
- Why this is not a one-formula, clone-and-run, or formatting task: no official implementation contains the synthetic systems or answers; the evaluator grades an intermediate cache and unseen contractions; and multiple independently coupled artifacts must agree numerically.

### Shortcut attempts

| Shortcut/baseline | Command | Result | Why it passes/fails |
| --- | --- | --- | --- |
| Exact visible response rows with dummy cache | `public_grid_hardcode` mutant | rejected, score 0.05 | unseen contractions and moment rubric fail |
| Kernelized or probe-averaged cache | `kernelized_cache` / `probe_collapse` | rejected, score 0.15 | raw per-probe cache is required |
| Short recurrence followed by zero padding | `truncated_zero_pad` | rejected, score 0.15 | high-order moments and hidden prefixes fail |
| Dense Hermitian eigendecomposition | `author/alternative_solver/solve.py` | accepted, score 1.0 | method-independent but still completes scaling, probes, cache, contractions, and diagnostics |

## 5. Privileged oracle run

- Command: `python -B tasks/kite/tasks/reusable_spectral_cache/author/oracle/generate.py --task-root tasks/kite/tasks/reusable_spectral_cache --check`
- Environment: Windows 11; Python 3.12.13; NumPy 2.3.5; one BLAS thread; CPU only.
- Source-only information used: author-only generation seeds and hidden queries; the numerical contract itself is public.
- Runtime: 0.697 s generation on a recorded successful sample; two generations were byte-deterministic and host timings vary across verifier reruns.
- Peak memory: not measured on this host; pending production resource profiling.
- Output inventory: three public system families, 18 hidden query rows, oracle submission, hidden response references, and reference summary; all are private/author-only except the disclosed public inputs.
- Evaluator score: 1.0.
- Status: pass.

## 6. Clean-room public-input reference run

- Clean-room construction: each run used a fresh temporary directory containing only `participant/`, a copied reference solver, and an audit wrapper. Author/private/source trees were absent by construction.
- Solver command: `python -B author/reference_solver/solve.py --participant participant --output output` inside the temporary tree.
- Network policy: off; audit hooks denied sockets, subprocesses, and source-task reads.
- Runtime: 0.236 s and 0.238 s for two identical solves in a recorded successful sample; host timings vary.
- Peak memory: not measured; the 75,744-byte NPZ and bounded `(3,4,384)` cache are well inside the 8 GiB public limit, but production peak-RSS measurement remains pending.
- Output inventory: `moments.npz` 75,744 bytes (SHA-256 `8e2cfe889c0cb91524e40097a9a7017ba96de1ecfc3c52b2b88496413543ac5d`), `public_response.csv` 2,172 bytes (`557baa16f88fbe75025896cdb3a6f0b972a5a09ee88858eefaca9d7a67cb6b85`), and `diagnostics.json` 894 bytes (`e3db0969b7af8ac72732f80d19aa3afcfb091f2f0af7ea320a4598f995a8ec22`).
- Evaluator metrics: normalized-by-tolerance RMSE `2.7201e-6` for raw moments, `2.5367e-8` for hidden contractions, and `1.7393e-7` for public responses; diagnostics score 1.0.
- Total score: 1.0 on both runs.
- Status: pass.
- Hidden access audit: source-path, socket, and subprocess denial self-tests all passed. The audit hook is an accidental-dependency guard, not an adversarial OS sandbox.

## 7. Alternative valid implementation

- Algorithmic independence: dense Hermitian spectral decomposition plus scalar Chebyshev polynomials replaces the sparse vector recurrence; only artifact serialization/contraction helpers are shared.
- Command: `python -B tasks/kite/tasks/reusable_spectral_cache/author/alternative_solver/solve.py --participant tasks/kite/tasks/reusable_spectral_cache/participant --output OUTPUT`.
- Metrics and score: normalized-by-tolerance RMSE `6.3175e-5` for raw moments, `9.6650e-8` hidden, `1.7477e-7` public; diagnostics 1.0; total score 1.0; runtime 0.588 s in a recorded successful sample.
- Status: pass.

## 8. Tolerance calibration

Every element uses `allowed_error = max(abs_tolerance, rel_tolerance * abs(reference))`; normalized RMSE is computed from these per-element scales. The task is deterministic, and reference repeats are byte-identical.

| Metric | Reference variation | Absolute tolerance | Relative tolerance | Justification |
| --- | ---: | ---: | ---: | --- |
| raw moments | sparse/dense recurrence max `3.13e-16`; eigensolver max `6.86e-15` | `2.0e-11` | `4.0e-10` | large cross-platform/BLAS margin while rejecting float32, order, factor-two, and normalization errors |
| finite contracted responses | independent disagreement max `1.56e-15` | `4.0e-10` | `4.0e-9` | covers cancellation and low-eta conditioning without accepting branch, eta, or Jacobian errors |
| diagnostics | exact recomputation | field-dependent numeric checks plus exact identities | field-dependent | diagnostics are derived from trusted public inputs and submitted moments rather than self-reported |

The disclosed target is the finite-prefix contraction, not the infinite exact resolvent. In the current metamorphic check, finite-versus-direct error is `3.42183e-4`, safely below the analytic omitted-tail bound `3.63381e-2`; this truncation error is not used as the submission tolerance.

## 9. Mutant results

| Mutant | Category | Expected | Observed score | Pass/fail | Notes |
| --- | --- | --- | ---: | --- | --- |
| `advanced_branch_swap` | complex branch | reject | 0.900000 | rejected | public branch response fails |
| `diagnostics_inconsistent` | fabricated evidence | reject | 0.976923 | rejected | mandatory diagnostics gate fails despite high aggregate score |
| `double_order_zero` | normalization | reject | 0.900000 | rejected | public contraction fails |
| `eta_not_scaled` | affine units | reject | 0.900000 | rejected | public contraction fails |
| `extra_probe_normalization` | probe normalization | reject | 0.150000 | rejected | moments and hidden contractions fail |
| `kernelized_cache` | lossy intermediate | reject | 0.150000 | rejected | raw cache rubric fails |
| `omit_response_jacobian` | physical units | reject | 0.900000 | rejected | public contraction fails |
| `prefix_ignored` | cache reuse | reject | 0.900000 | rejected | prefix queries fail |
| `probe_collapse` | lossy intermediate | reject | 0.150000 | rejected | probe-resolved cache fails |
| `public_grid_hardcode` | answer lookup | reject | 0.050000 | rejected | hidden queries and cache fail |
| `recurrence_missing_two` | recurrence | reject | 0.150000 | rejected | raw moment rubric fails |
| `shifted_order` | indexing | reject | 0.150000 | rejected | raw moment rubric fails |
| `stale_system_swap` | stale binding | reject | 0.150000 | rejected | per-system cache fails |
| `truncated_zero_pad` | truncation | reject | 0.150000 | rejected | long-prefix cache fails |
| `wrong_affine_halfwidth` | scaling | reject | 0.150000 | rejected | recurrence/cache fails |

Mutation categories covered: scaling, recurrence, normalization, complex branches, units, indexing/prefixes, lossy cache shortcuts, stale binding, visible-answer hard-coding, and fabricated diagnostics. All 15 complete schema-valid scientific mutants were rejected without crashes or timeouts.

## 10. Metamorphic and invariant tests

| Test | Expected relation | Observed | Status |
| --- | --- | --- | --- |
| Basis permutation | cache and responses invariant | max error `7.77156e-16` | pass |
| Positive affine energy transform | moments invariant; response scales by `1/alpha` | moment `3.35230e-16`; response `1.11239e-16` | pass |
| Global probe phase | diagonal moments invariant | max error `1.11471e-16` | pass |
| Retarded/advanced causality | `GA=conj(GR)` and density identity | both errors `0`; density `0.2487660` | pass |
| Prefix/suffix independence | shorter prefix ignores suffix | error `0` | pass |
| Moment invariants | `|tau|<=1`, real, `tau_0=1` | max `1`; imag `1.26283e-16`; tau0 error `0` | pass |
| Finite contraction/direct resolvent | error below analytic tail bound | `3.42183e-4 < 3.63381e-2` | pass |
| DOS mass/global convergence | mass near 1; longer prefix lower L2 | mass `0.99681584`; long `5.68555e-7` vs short `7.76664e-3` | pass |

## 11. Evaluator robustness

- Repeated deterministic runs: oracle, reference, alternative, and every mutant were graded twice with identical exit state, stdout, stderr, parsed payload, and score contract.
- Malformed/partial/NaN/Inf/oversized output: 14 hard-gate cases were rejected safely; object arrays, archive expansion bombs, duplicate JSON keys, nonstandard numeric constants, wrong shapes, missing/extra files, and stale IDs are covered.
- Valid edge controls: byte-string identifiers and a valid compressed NPZ with maximum member compression ratio 272 both scored 1.0; a near-tolerance non-byte-equal submission scored 1.0.
- Fabricated self-reported metrics: recomputation and mandatory diagnostics reject the mutant.
- Hard-coded public examples: score 0.05 and reject.
- Private-file/network access: clean solver source-read and socket denial probes pass.
- Symlink/path traversal: regular-file, traversal, reparse, directory, and hard-link gates are implemented; Windows lacked privilege to create both dynamic symlink test cases, so those paths were code-audited but not executed on this host.
- Executable submission isolation: evaluation is data-only and executes no participant code.

## 12. Hidden-instance validity

- Generator: `author/oracle/generate.py`.
- Varying factors: dimensions, topology, onsite disorder, complex hopping, probes, energy, broadening, response sector, and non-power-of-two prefixes.
- Scientific invariants preserved: Hermiticity, strict scaled spectral containment, unit-modulus probes, and the disclosed finite Chebyshev contraction.
- Reference behavior over generated instances: recurrence and eigensolver routes both pass all three systems and all visible/hidden queries.
- Public review instances retired: yes.
- Private seed policy: separate fixed author seeds for this retired review build; regenerate from server-secret seeds before scored release.

## 13. Participant package audit

- Paper/source identifiers removed: yes; recursive identifier scan found zero leaks.
- Task semantics remain complete: yes; the public task discloses every solution-critical convention.
- Inputs sufficient: yes; 14 files, 298,034 bytes, with hashes and complete system/probe tables.
- Output contract clear: yes; exact files, keys, shapes, types, and row schemas are public.
- Public success criteria clear: yes.
- Environment reproducible: Python 3.11+, NumPy `==2.3.5`, CPU only, network off.
- No private artifacts included: verified by participant allowlist and projection audit.

## 14. Commands to reproduce verification

Run from the repository root:

```text
python tasks/kite/tasks/reusable_spectral_cache/scripts/verify.py
```

Additional author-only commands:

```text
python -B tasks/kite/tasks/reusable_spectral_cache/author/oracle/generate.py --task-root tasks/kite/tasks/reusable_spectral_cache --check
python -B tasks/kite/tasks/reusable_spectral_cache/author/reference_solver/solve.py --participant tasks/kite/tasks/reusable_spectral_cache/participant --output OUTPUT
python -B tasks/kite/tasks/reusable_spectral_cache/author/alternative_solver/solve.py --participant tasks/kite/tasks/reusable_spectral_cache/participant --output OUTPUT
python -B tasks/kite/tasks/reusable_spectral_cache/private/grader/grade.py --participant tasks/kite/tasks/reusable_spectral_cache/participant --submission OUTPUT
```

A recorded release verifier sample passed in 15.313 s with build identity `sha256:439d24074b7efc721570f33b64e0433427dfa6488945274a4aedbd78ee4b3f54`; the persisted results file records the most recent host timing.

## 15. Remaining risks and next actions

- Scientific review: independently review the explicit raw-moment normalization and finite-resolvent branch convention.
- Engineering review: run production peak-RSS measurement and dynamic symlink/junction tests on a capable cross-platform CI host; replace the audit hook with actual filesystem/network isolation for scored execution.
- Evaluation scope: hidden queries test reuse of submitted moments, not execution of participant code on unseen Hamiltonians, because submission is intentionally data-only.
- ALE integration: compiler/publication projection and target-infrastructure execution remain pending; rotate checked-in review seeds before release.
- Frontier-agent calibration: no pinned-agent trials exist for this exact build, so no frontier-hard claim is supported.
- Licensing: select an explicit downstream license for independently authored participant assets while preserving the recorded upstream LGPL/GPL metadata conflict.

Recommended action: accept as a locally verified `structurally_hard_candidate` for collaborator review only; retain `needs_agent_calibration` until every blocking item is resolved.
