# Verification report: spinful-packet-dynamics

## Decision

- Status: `needs_agent_calibration`
- Provisional difficulty: `structurally_hard_candidate`
- Frontier-agent calibration: not run on this exact build
- Exact build: `sha256:1723af0f244159dee47f96d153123e6e6e8b80bb02509ad75c765360f6163ca1`
- Blocking issues: pinned agent calibration, independent scientific review, ALE publication/resource integration, and a resolved distribution license for benchmark-authored assets remain pending

## 1. Source and provenance

- Paper/version: arXiv:1910.05194 v2, revised 2020-03-13; local SHA-256 `df4bea7b0fb8d4059bc16e0a20357912450cfaf63799cc2ac8ada97453dd3e82`.
- Official code: KITE v1.0 archive, commit `7bb1fc44d2b5a67ef65524fe33702e9c2cdef416`; archive SHA-256 `09c45bd2b4ac7f4bcb6a0bb7b4a51ed00e1c4ac017424ece38196ba0ee34fefd`.
- Upstream license conflict: the archived `LICENSE.md` is LGPL-3.0, while the archived README and Zenodo metadata say GPL-3.0. No official code or paper bytes appear in `participant/`; its inputs and helper are independently benchmark-authored synthetic material. A distribution license for those assets still must be selected before release.
- Grounded evidence: paper PDF pp. 23-26, Sec. 4(e), Eqs. 4.12-4.15 and Fig. 10; archived `Src/SimulationGaussianWavePacket.cpp` line 138.
- Paper/code conflict: Eq. 4.13 prints `(-1)^n J_n`, while the implementation and standard expansion use `(-i)^n J_n`.  The public task discloses the operationally correct `(-i)^n` convention.
- Paper typography conflict: Eq. 4.15's printed Gaussian is dimensionally malformed.  The source constructs and globally normalizes a centered Gaussian.  The task discloses its own `1/(4 sigma^2)` amplitude convention, making `sigma` the probability-density width.
- Deliberate grounded extension: square open lattice, explicit dense continuous Ising fields, constant physical-spin spinor, arbitrary energy units with `hbar=1`, Peierls phases, and one reusable 52-vector basis.  These are not claimed to reproduce the graphene/TMD geometry, sparse resonant impurities, or sequential 70-moment-per-step Fig. 10 calculation.

## 2. Target leaf and workflow boundary

- Target leaf: a controlled scalar-versus-site-dependent-Ising comparison produces quantitatively different time-resolved spin trajectories and spatial spreading under spin-orbit dynamics; determine the direction and magnitude from computed evidence.
- Scientific meaning: it preserves Fig. 10's defensible qualitative leaf that an additional out-of-plane Ising field changes spin dynamics, without claiming that Ising disorder monotonically increases dephasing.
- Included operations: parse the open graph; assemble six spin-block Hamiltonians; verify Hermiticity; compute and validate spectral enclosures; rescale; build and normalize a Gaussian plane-wave spinor; generate 52 Chebyshev vectors; contract seven public times; compute nine observables; aggregate paired model ensembles; derive contrasts and literal final-polarization/spreading categories.
- Public boundary: explicit sites, bonds, phases, onsite fields, scaling values, packet parameters, public times, and a Bessel helper.
- Private boundary: spectral oracle basis, six private contraction times, hidden trajectories, exact tolerances/weights, and adversarial suite.
- Derivation: reported workflow slice with a clearly labeled synthetic reduced-model extension.

## 3. Specification closure

| Decision | Disclosed | Inferable | Method-agnostic | Hidden dependency | Evidence |
| --- | ---: | ---: | ---: | ---: | --- |
| Site/spin order and bond orientation | yes | no | no | no | `TASK.md` indexing and block equations |
| Onsite, hopping, phase, and SOC signs | yes | no | no | no | explicit Pauli/block definitions |
| Open boundary and Hermitian completion | yes | no | no | no | explicit graph rule |
| Scaling and spectral validation | yes | no | no | no | `realizations.csv` plus formula |
| Initial packet, normalization, and units | yes | no | no | no | complete formula and `hbar=1` statement |
| Recurrence and Bessel contraction | yes | no | no | no | complete recurrence and coefficient formula |
| Observables, aggregation, and comparison | yes | no | no | no | formulas, `ddof=0`, deltas, and categories |
| Numerical implementation details | no | no | yes | no | outcome-based tolerances accept independent implementations |

All rows closed: yes.

### Paper-blind specification review

- Reviewer: fresh delegated context restricted to `participant/`.
- Restatement: correctly identified 72 sites, 127 bonds, six 144-dimensional Hamiltonians, 52 basis vectors, 42 trajectory rows, 14 ensemble rows, four outputs, and hidden in-range contraction.
- Initial minor issues: unused metadata, interval notation, and JSON array/exact-field wording.
- Resolution: unused field removed and all wording made explicit before final verification.
- Missing information after resolution: none.
- Status: pass; see `author/paper_blind_review.md`.

## 4. Intrinsic difficulty audit

- Meaningful operations: 8; dependency depth: 6 operation-to-operation transitions; branch count: 4 (reusable basis/private-time contraction, public trajectories, ensemble aggregation, and evidence-linked analysis), spanning two disorder models and six realizations.
- Required artifacts: reusable complex basis, realization trajectories, ensemble statistics, and evidence-linked analysis.
- Challenge sources: complex spin/bond sign conventions; spectral validation; a long coupled recurrence; time-domain special-function contraction; multiple observables; controlled aggregation; hidden-time reuse.
- Expected expert effort: 8-16 hours including implementation, sign/index validation, recurrence/contraction diagnosis, and aggregation audit.
- Compute is deliberately modest: 72 sites, 144 spin-orbitals, 52 vectors, six realizations, CPU only.
- One-formula and clone-and-run shortcuts fail because the new synthetic instance requires a linked workflow and has no source-compatible configuration.

### Shortcut results

| Shortcut | Result | Reason |
| --- | --- | --- |
| Public rows plus zero higher-order basis | rejected | private-time contraction and direct basis metric fail |
| One-step power recurrence | rejected | basis and trajectory behavior diverge |
| Omit site-dependent Ising field | rejected | controlled branch and hidden behavior diverge |
| Correct numerics plus fabricated comparison | rejected | evaluator recomputes evidence; exact categories are mandatory |
| Infer eigenvalues from scaling metadata | rejected by design | asymmetric conservative padding no longer encodes either extremum |

## 5. Privileged oracle

- Command: `python author/oracle.py participant private/reference private/hidden_inputs/private_times.json private/reference_hidden/hidden_trajectories.csv`
- Method: dense Hermitian construction, spectral eigendecomposition, `cos(n arccos(E))` Chebyshev evaluation, and independent 320-point Gauss-Legendre Bessel integral.
- Source-only information used: author generation seeds, six private contraction times, and private reference locations; no undisclosed paper value enters the public numerical contract.
- Outputs: `basis.npz`, `trajectories.csv`, `ensemble.csv`, `analysis.json`, plus separately stored `hidden_trajectories.csv`.
- Generation runtime: `0.19774400000005699` s on Python 3.12.13/NumPy 2.3.5; grade runtimes `0.14900160000070173` s and `0.1403444000006857` s (recorded successful sample; host timings vary across verifier reruns).
- Peak memory: not measured on this host.
- Score: `0.9999997412138324`.
- Status: pass.

## 6. Clean-room public-input reference

- Construction: temporary directory with only copied `participant/`, copied solver, and declared runtime.  `scripts/isolated_runner.py` denies file access outside the temporary/runtime roots, all socket events, and child processes; explicit private-file and socket probes pass.
- Command: `python isolated_runner.py CLEAN_ROOT CLEAN_ROOT/solve.py CLEAN_ROOT/participant CLEAN_ROOT/output`, where `CLEAN_ROOT` is the temporary clean-room directory.
- Method: dense block assembly and vector Chebyshev recurrence using the participant Bessel helper.
- Solver runtime: `0.18488570000045002` s; grade runtimes `0.15037730000040028` s and `0.15418249999947875` s (recorded successful sample; host timings vary across verifier reruns).
- Peak memory: not measured on this host.
- Output inventory: `basis.npz` 689,721 bytes; `trajectories.csv` 8,706 bytes; `ensemble.csv` 5,318 bytes; `analysis.json` 3,917 bytes; total 707,662 bytes.
- Metric scores: recurrence basis `0.999998700276409`; hidden contraction `0.999999496607805`; public trajectories `0.9999992992954307`; ensemble aggregation `0.9999992482663136`; evidence consistency `0.9999997724311158`.
- Score: `0.9999992243019628`; all mandatory metrics pass.
- Repeated grading: canonical JSON and process status identical.
- Hidden access: denied by audit hook and verified by probe; network denied.
- Status: pass.

## 7. Alternative implementation

- Method: accumulate onsite and oriented bond actions directly from the edge list; no dense Hamiltonian is used by propagation.  Dense columns are built only for independent bound validation.  Oracle additionally supplies a third, spectral polynomial route.
- Solver runtime: `0.5921001999995497` s; grade runtimes `0.14827059999970515` s and `0.14749440000014147` s (recorded successful sample; host timings vary). Score: `0.9999992285440962`.
- Status: pass.

## 8. Tolerance calibration

Every numeric comparison uses the implemented scale
`max(abs_tolerance, rel_tolerance * abs(reference))`; normalized RMS is then
formed from those pointwise scaled residuals. This gives an absolute floor near
zero without loosening large-magnitude values by adding both allowances.

| Metric | Three-implementation disagreement | Abs tolerance | Rel tolerance | Justification |
| --- | ---: | ---: | ---: | --- |
| Chebyshev basis | below `2e-14` raw | `2e-10` | `2e-8` | recurrence versus spectral polynomial rounding |
| Hidden/public observables | below `5e-13` raw | `2e-8` | `1e-7` | Bessel series versus quadrature and contractions near zero |
| Ensemble statistics | below `6e-13` raw | `3e-8` | `2e-7` | propagated observable and population-variance rounding |
| Bounds/contrasts | below `2e-12` raw | `5e-8` | `3e-7` | independent Hermitian eigensolvers and nonlinear spread |

The task has explicit deterministic realizations rather than solver stochasticity.  Three paired realizations per model are aggregated with population standard deviation.  Exact hidden times and score thresholds remain private.

## 9. Mutants

All eight scientific mutants are structurally valid and rejected on scientific
metrics:

| Mutant | Category | Score |
| --- | --- | ---: |
| `wrong_soc_sign` | wrong sign | `0.022750131990781745` |
| `conjugate_peierls_phase` | wrong phase | `0.02600062072059458` |
| `swap_soc_axes` | coordinate order | `0.022750257428460947` |
| `omit_ising_disorder` | omitted interaction | `0.01950150544193843` |
| `swap_initial_spin` | spin index | `0.026000095034295307` |
| `unnormalized_packet` | normalization | `0.026000026300395322` |
| `first_order_recurrence` | recurrence | `0.019500208732849654` |
| `real_bessel_coefficients` | propagation phase | `0.575999625981493` |

Structural and adversarial results:

| Mutant | Score | Result |
| --- | ---: | --- |
| `malformed` | `0.0` | hard-gate reject |
| `malformed_json` | `0.0` | hard-gate reject |
| `partial` | `0.0` | hard-gate reject |
| `nan` | `0.0` | hard-gate reject |
| `huge_finite` | `0.5760002469520052` | mandatory-metric reject without overflow or traceback |
| `oversized` | `0.0` | hard-gate reject |
| `stale` | `0.0` | hard-gate reject |
| `fabricated` | `0.8894997452556337` | evidence-consistency reject |
| `wrong_conclusions` | `0.9934997412138324` | mandatory exact-category reject |
| `wrong_numeric_type` | `0.0` | hard-gate reject |
| `wrong_category_type` | `0.0` | hard-gate reject |
| `hardcoded_public` | `0.2500000559956184` | hidden-time/basis reject |
| `unexpected_executable` | `0.0` | artifact-allowlist reject |

## 10. Metamorphic and invariant tests

| Test | Expected | Observed maximum error | Status |
| --- | --- | ---: | --- |
| Global packet phase | basis covariant; observables invariant | `8.881784197001252e-16` | pass |
| Uniform energy shift | basis and observables invariant with shifted center | `7.105427357601002e-15` | pass |
| Hamiltonian scaling/time reciprocity | `sH` at `t/s` matches `H` at `t` | `7.105427357601002e-15` | pass |
| Coordinate translation | spin invariant; moments transform analytically | `1.4210854715202004e-14` | pass |
| Norm and zero SOC | norm one; pure up spin remains up | `1.1213252548714081e-14` | pass |
| Hermiticity | `H = H dagger` | `0` | pass |

## 11. Evaluator robustness

- Malformed/partial/NaN/oversized/stale: safe hard failures.
- Huge finite values: finite sentinel scoring prevents overflow or non-JSON output.
- Fabricated metrics and wrong categories: rejected; numeric evidence is recomputed from submitted trajectories and categories must match exactly.
- Hard-coded public rows: rejected by basis and private-time contraction.
- Symlinks/reparse points and extra paths: rejected before parsing. The static root-link gate is present, but the live root-symlink test was `platform_unavailable` on this Windows host because symlink creation lacked privilege.
- NPZ: exact member allowlist, no pickle/object arrays, bounded compressed and expanded size.
- Submission execution: none.  Only four data files are parsed.
- Grader determinism: repeated parsed result and process status identical.

## 12. Hidden-instance validity

- Generator: `author/generate_instance.py`, with separate scalar and Ising seed domains; current instance `spd-d8891b6fae09a0e09103273b` regenerated in `0.20778799999970943` s.
- Canonicalization: each computed spectral center and half-width is formatted to exactly nine decimal places and parsed back before it enters both the public input and canonical instance payload. This makes the instance ID and every downstream calculation refer to the disclosed scaling values, not hidden higher-precision bounds.
- Regeneration check: the verifier creates inputs and oracle references in a temporary tree, requires exact participant-input structure and values, and compares regenerated NPZ/CSV/JSON references semantically with the same numerical tolerance rule used for scientific validation. The checked artifacts matched.
- Hidden variation: six unpublished off-grid contraction times in the disclosed `[0,2.5]` interval plus metamorphic transformations.
- Preserved invariants: Hermiticity, open boundary, radius at most `rho_limit=0.975`, unitary finite-system dynamics, and paired scalar backgrounds.
- Public review policy: this exact instance must be retired if private files are exposed.

## 13. Participant audit

- Exactly eight visible files: task, six input files, and one Bessel helper.
- No paper title, acronym, repository, figure label, source code, reference value, hidden time, threshold, weight, or mutant leaks.
- Input completeness, paired realization coverage, positive scaling, and public-time range are verified.
- Paper/source lookup cannot directly solve the new synthetic system.

## 14. Reproduction

```text
python tasks/kite/tasks/spinful_packet_dynamics/scripts/verify.py
```

Direct clean reference and grading (author context only):

```text
python tasks/kite/tasks/spinful_packet_dynamics/author/reference_solver/solve.py tasks/kite/tasks/spinful_packet_dynamics/participant output/spinful-reference
python tasks/kite/tasks/spinful_packet_dynamics/private/grader/grade.py output/spinful-reference --pretty
```

## 15. Remaining risks and next actions

- Scientific: a domain expert should review whether the reduced square-lattice, dense-Ising analogue is an appropriate benchmark abstraction.  It must not be used to infer physical graphene/TMD relaxation lifetimes or monotonic dephasing.
- Engineering: Python audit hooks validate the trusted clean solver but are not a hostile-code OS sandbox; this is sufficient here because participant executables are not accepted.
- Resource evidence: wall time and output bytes are measured, but peak RSS was not measured on this host.
- Licensing: upstream LGPL/GPL metadata conflict is recorded; although participant assets are independently authored, their distribution license is not yet selected.
- ALE integration: compiler/publication projection and production resource-policy runs are pending.
- Difficulty: no pinned frontier-agent trials have been run; do not label the task frontier-hard.
- Decision: verified local candidate requiring agent calibration and manual scientific review, not yet accepted for benchmark release.
