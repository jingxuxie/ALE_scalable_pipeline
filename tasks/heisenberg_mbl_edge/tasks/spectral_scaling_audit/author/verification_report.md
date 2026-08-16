# Verification report: finite-size spectral crossover audit

## 1. Decision summary

- Task ID: `spectral-scaling-audit-v1`
- Verification schema: `spectral-scaling-verification-results/v1`
- Authoritative build identity: `sha256:42c4b45503175b7bfce961de20a9fa5ab40f63a374ee8114ca25ddafbce7a8eb`
- Build file count: 126
- Authoritative ledger SHA-256: `b6b53838fb5d2ae27825ea2e09b0c2d695a831dc679784f97f44eeebc6fded45`
- Generated at: `2026-08-16T05:33:58.516920+00:00`
- Total verifier duration: `310.83801350000067` seconds
- Required gates: 14/14 passed; required failures: none
- Verification status: `pass`
- Release disposition: `accepted_for_collaborator_review`
- Provisional difficulty: `structurally_hard_candidate`
- Frontier-agent calibration: `not_run`

The package is accepted for collaborator review. This is not a frontier-hard
claim. The participant claim remains finite-size crossover evidence and does
not establish a thermodynamic phase boundary or mobility edge.

The verified participant snapshot is:

- `participant/TASK.md`: `9e578bff82c161fb5a6effa9b35417f26e53e9ba3ac503cf0ae4708fa29762c2`
- `participant/software/validate_submission.py`: `2079a06958294cf580cc707d230cc6acd583b1b03d6c8c45c573460a8478e99b`
- `participant/software/README.md`: `0980bf232343a1b6814f3b96e745e82d2d31a8a2a7c2762691d41d68cfe9d5c8`

This authoritative rerun follows the final identifier and selected-subgraph
closure corrections. The verifier ledger, author task specification, private
evaluation contract, checklist, and this report now use the single canonical
task ID `spectral-scaling-audit-v1`. The selected seven-operation workflow no
longer lists the downstream private score as one of its rubric artifacts; the
evaluator and score remain documented outside the participant workflow slice.
No scientific score, threshold, mutant, probe, metamorphic relation, or case
changed as part of these closure corrections.

## 2. Gate ledger

| Gate | Duration (s) | Result |
| --- | ---: | --- |
| Inventory | 0.009961200001271209 | pass |
| Participant/private separation | 0.027484499998536194 | pass |
| Package sizes and imports | 2.25755879999997 | pass |
| Oracle generation determinism | 65.6112549999998 | pass |
| Exact-diagonalization realism determinism | 0.6613972999984981 | pass |
| Oracle scientific invariants | 0.8946976000006543 | pass |
| Clean-room public validation | 18.920876000000135 | pass |
| Private evaluator determinism | 50.98174690000087 | pass |
| Scientific mutant sensitivity | 108.2780915000003 | pass |
| Hard-coded retired-case shortcut | 8.499999239575118e-06 | pass |
| Malformed/nonfinite/partial/oversize/security probes | 17.229116200000135 | pass |
| Hard-link rejection | 0.15682700000252225 | pass |
| Metamorphic covariance | 45.57500110000183 | pass |
| Package unchanged during verification | 0.02586860000155866 | pass |

The final package hash and all 126 build files were unchanged after the run.
The verifier ran on CPython 3.12.13, NumPy 2.3.5, and
Windows 11 (`10.0.26200`); cases declare the public Python `3.11+` contract.

## 3. Target claim and included workflow

The target leaf is `leaf-gap-ratio-fss-audit`. A reusable analyzer must begin
with shuffled raw spectral packets, reconstruct the true normalized-energy
target, select and order levels, calculate adjacent-gap ratios, and aggregate
at the realization level. It then infers a target-dependent finite-size
crossover, audits minimum-size/window sensitivity, bootstraps realization
clusters, predicts held-out coordinates, and emits six mutually constrained
evidence artifacts.

The seven-operation subgraph has dependency depth six. Its difficulty comes
from the coupled scientific workflow—raw reconstruction, hierarchical
statistics, nonlinear scaling, stability, uncertainty, prediction, and
cross-artifact evidence—not from paper trivia, missing conventions, exact
answer formatting, excessive output, or production-scale diagonalization.

## 4. Participant/private boundary and paper-blind review

The participant sees the complete reference workflow, exact input/output
schemas, one retired generated case, the public validator, numeric/resource
validity bounds, and qualitative success/metamorphic criteria. Hidden cases,
generator parameters, analytic truth, oracle outputs, author solvers, scoring
weights and knots, mandatory floors, mutant implementations, and probe payloads
remain author/private.

Two independent participant-only reviews passed the exact three-file snapshot
above without a material ambiguity or task-conforming false rejection. The
automated separation audit scanned all 8 participant files, including 7 text
files and 426,334 text bytes, against 18 hidden identifiers. It found zero
symlinks and zero hard links and no private/source leakage.

## 5. Privileged oracle and deterministic packaging

Command:

```text
python -B author/oracle/generate.py --output-root <fresh-task-root>
```

Repeated generation matched 63 semantic files with digest
`8d46007e2b1589cfc08f8bb12e2a6cac9f0fa02e26cab0d2a7392aad4fe65029`.
The four hidden inputs matched 20 packaged files with digest
`ca7490d363a3bd43090f1e2847c33b9ac61afb54bd1d01e35a23e4fe37dfa971`;
34 reference files matched; the retired five-file case matched digest
`9e89c210e77f67c25a51e11ec904d58116a627771927f49d54c46e5cb2dd724f`;
and the four-file realism fixture matched digest
`ee30c5e264fca4b946c56658298a6ba7ffe73bddcfc1b8d2177a49bd9088748a`.

All four scoring families preserved bounded ratios, a resolved common
finite-size crossover, realization-cluster sampling, weak-control ratios above
strong-control ratios, and conditioned affine-energy invariance:

| Case | Packets | Groups | Critical-curve span | Minimum weak-minus-strong |
| --- | ---: | ---: | ---: | ---: |
| `case_amber` | 3,132 | 108 | 0.7450624000000001 | 0.14486137322948833 |
| `case_indigo` | 2,914 | 108 | 0.7403031999999996 | 0.14065556086987213 |
| `case_sable` | 3,060 | 102 | 0.5587584000000003 | 0.14486148025792922 |
| `case_verdant` | 2,806 | 108 | 0.6562175999999997 | 0.14409450592857553 |

The visible `retired_cedar` case is absent from hidden scoring.

## 6. Clean-room public-input reference

The verifier constructed fresh rooms containing only the participant
projection, copied solver/analyzer bytes, Python, and NumPy. Source, author,
private, truth, and oracle paths were not supplied to the solver process.

Reference commands:

```text
python -B author/reference_solver/solve.py --participant participant --output <clean-submission>
python -B participant/software/validate_submission.py --submission <clean-submission> --run-public
python -B private/grader/grade.py --submission <clean-submission>
```

The submission inventory was exactly `output/analyze.py`, the participant
projection remained unchanged, and two public repetitions were byte-identical.
The retired public invocation produced 3,024 realization rows, 108 grouped
rows, 3 targets, 27 queries, and 223,195 output bytes. Reference analyzer source
SHA-256 was `9b153a2b2ac7f561f40f321c1f74eb649d725642f8a9152788ce66ea7a1e8ee8`.

Across four hidden cases and two private repetitions in different working
directories and hash seeds, the reference scored exactly:

| Component | Score |
| --- | ---: |
| Realization statistics | 1.0 |
| Grouped statistics | 1.0 |
| Held-out prediction | 0.9264977680056898 |
| Critical curve and exponent | 0.5791808745280645 |
| Stability sweep | 1.0 |
| Uncertainty | 0.8948481481481482 |
| Evidence consistency | 1.0 |
| **Total** | **0.8996699182281552** |

Every aggregate and per-case mandatory floor passed.

## 7. Independent alternative implementation

The alternative uses monotone regression by size, robust pairwise crossings,
finite-size drift, leave-one-size-out non-parametric collapse selection, and
monotone interpolation rather than the reference estimator. Source-line
similarity to the reference was 0.23735670937289277.

Its submission inventory was also exactly `output/analyze.py`; two public
repetitions were byte-identical and left the participant projection unchanged.
The public invocation produced the same 3,024 realizations, 108 groups, 3
targets, and 27 queries in 223,165 bytes. Alternative analyzer source SHA-256
was `b4e0d1cf5896757bef8e3864e7290aede310b319d93d7e6229d2e3be4de532b5`.

Its exact private result was:

| Component | Score |
| --- | ---: |
| Realization statistics | 1.0 |
| Grouped statistics | 1.0 |
| Held-out prediction | 0.9773965697360711 |
| Critical curve and exponent | 0.707702083967269 |
| Stability sweep | 0.5005509014379065 |
| Uncertainty | 0.8732186698144256 |
| Evidence consistency | 1.0 |
| **Total** | **0.8723372222137469** |

It passed every aggregate and per-case floor. This independent pass confirms
that evaluation is behavioral and does not require source identity or exact
fitted artifacts.

## 8. Tolerance and score calibration

Direct packet/group statistics and claims are deterministic recomputations and
therefore receive only serialization allowance. Fitted crossover behavior,
stability, prediction, and uncertainty receive continuous credit because
finite sampling and valid estimator choice make exact equality scientifically
inappropriate.

| Metric | Excellent knot | Minimum-credit knot | Rationale |
| --- | ---: | ---: | --- |
| Realization mean error | `2e-7` | `0.012` | Direct bounded-ratio recomputation; catches target/order/ratio errors |
| Group mean error | `3e-7` | `0.012` | Direct realization-first recomputation |
| Group SEM error | `3e-7` | `0.006` | Separates cluster SEM from pooled-gap pseudoreplication |
| Held-out mean prediction error | `0.010` | `0.065` | Allows smooth independent estimators while rejecting wrong coordinates |
| Crossover coordinate error | `0.10` | `0.52` | Native control scale with finite-size corrections |
| Exponent error | `0.18` | `0.95` | Dimensionless exponent is less identifiable than direct statistics |
| Stability coordinate / exponent / RMSE | `0.035 / 0.08 / 0.002` | `0.42 / 0.75 / 0.045` | Admits independent refits but rejects copied or omitted sweeps |
| Query coverage slack | `0.004` | coverage rule | Guards against underconfident prediction intervals |
| Transition/query log width error | `0.08 / 0.08` | `2.2 / 1.8` | Symmetric multiplicative calibration for over/under-width |
| Claim summary error | `5e-7` | exact categorical checks | Claims summarize recomputed evidence |

The private score threshold is 0.76. Per component, four-case aggregation is
`0.80*mean + 0.20*minimum`, followed by aggregate and per-case mandatory floors.
This guards against one family hiding a scientific failure on another. The two
valid scores above remain separated from every calibrated mutant.

## 9. Scientific mutant results

All 15 mutants were schema-valid, reached behavioral scoring with zero
hard-gate failures, and were rejected across 14 categories:

| Mutant | Category | Score | Mandatory reason for rejection |
| --- | --- | ---: | --- |
| `target_mirror` | energy-window semantics | 0.6247764199111627 | realization, grouping, evidence |
| `use_shift_energy` | acquisition-shift semantics | 0.7522688410977463 | realization, evidence |
| `unsorted` | spectral ordering | 0.24525477202395646 | realization, grouping, prediction, curve, stability, evidence |
| `raw_ratio` | observable definition | 0.3020180727683548 | realization, grouping, prediction, evidence |
| `pool_gaps` | realization aggregation | 0.8473686984239975 | grouping, evidence |
| `gap_sem` | clustered uncertainty | 0.857521032255433 | grouping |
| `no_size_scaling` | finite-size coordinate | 0.6958701096817309 | curve/exponent, stability |
| `wrong_l_exponent` | finite-size coordinate | 0.6896277073796685 | curve/exponent, stability |
| `largest_size_only` | finite-size shortcut | 0.7383250198739754 | stability |
| `constant_edge` | critical-curve model | 0.8493440215802439 | curve/exponent |
| `hardcoded_public` | anti-hardcoding | 0.7231143594521261 | curve/exponent |
| `no_stability` | stability analysis | 0.7735891336230301 | stability |
| `skip_bootstrap` | uncertainty propagation | 0.8629296853404083 | uncertainty |
| `stale` | provenance integrity | 0.8926699182281552 | evidence consistency |
| `fabricated_claims` | evidence consistency | 0.8856699182281552 | evidence consistency |

The `use_shift_energy` mutant is important: the bounded diagnostic acquisition
shift is deliberately not the requested normalized-energy target. Its
behavioral rejection confirms the leaf depends on reconstructing the true
target from `target`, `e_min`, and `e_max`.

## 10. Metamorphic and conditioned-affine results

Both valid analyzers passed all six transformations. Numerical comparisons used
`atol=5e-9` and `rtol=5e-8`.

| Relation | Reference max error / comparisons | Alternative max error / comparisons | Result |
| --- | ---: | ---: | --- |
| Affine control | `8.881784197001252e-16` / 23,071 | `1.021405182655144e-14` / 23,071 | pass / pass |
| Positive affine energy | `1.8096635301390052e-14` / 23,071 | `2.353672812205332e-14` / 23,071 | pass / pass |
| Realization-ID bijection | `0` / 23,032 | `0` / 23,032 | pass / pass |
| Packet/row permutation | `4.440892098500626e-16` / 23,071 | `4.440892098500626e-15` / 23,071 | pass / pass |
| Shard split/rejoin | `4.440892098500626e-16` / 23,071 | `2.4313884239290928e-14` / 23,071 | pass / pass |
| Target/energy mirror | `4.440892098500626e-16` / 23,032 | `7.993605777301127e-15` / 23,032 | pass / pass |

Realization-ID and target-mirror comparisons each relaxed exactly 30
finite-replicate bootstrap-interval checks, as permitted publicly; all other
relations had zero relaxed checks. The alternative affine-control result above
is the corrected post-fix measurement.

The energy map was `E'=1.625*E-4.75`, within the allowed scale interval
`[0.5,2.0]`. For all 3,132 packets in `case_amber`, the stable selected prefix,
energy-sorted retained sequence, and full selected-index sequence were exactly
preserved. The largest retained-ratio perturbation was
`7.69717622972621e-13`, below `1e-10`; maximum shift/span fraction was
`0.003806063444693458`, below `0.005`. Baseline/transformed minimum cutoff
requirement ratios were `334.4194435527209` and `334.41944355272096`; selected
gap requirement ratios were `58.07525925239322` and `58.075259246016614`.

Two negative controls also passed. Scale 3.0 was rejected with `ValueError`
before destination creation or transformed analysis. The malformed CLI case
returned exit 1, empty stderr, and byte-identical stdout/report:

```json
{"schema_version":"spectral-scaling-metamorphic-report/v1","passed":false,"fatal_error":"metamorphic_suite_exception"}
```

## 11. Numeric-domain and archive evidence

The independent verifier checked the complete public numeric proof. Across the
retired and four hidden packaged cases, observed maxima were far inside the
published caps:

| Quantity | Observed envelope | Public cap |
| --- | ---: | ---: |
| Absolute training `x` | 189.15406546310444 | `2.1e36` |
| Absolute training `z` | 1.0 | `1+8*eps` |
| Absolute query `z` | 0.968303682506674 | 2.0 |
| Weighted-design condition | 109.73856236946209 | `1e12` |
| Absolute cubic coefficient | 0.8937352935232065 | `1e6` |
| Weighted residual-square sum | 150.09756059770916 | `1e35` |
| Absolute raw pre-clip query polynomial | 0.5546395978395277 | `2e7` |
| Shift/span fraction | 0.003810879609185012 | 0.005 |
| Retained-ratio affine perturbation | `7.87370169064161e-13` | `1e-10` |
| Minimum cutoff requirement ratio | 157.335246114524 | at least 1 |
| Minimum selected-gap requirement ratio | 10.779245543209647 | at least 1 |

The largest derived target bootstrap seed was 909,146; the contract maximum is
18,446,744,073,709,544,552, chosen so every `seed+1009*t` remains below the
uint64 maximum 18,446,744,073,709,551,615. The maximum actual CSV field occupied
23 bytes under the 128-byte cap.

Every case used exactly two physical NPZ members. Maximum uncompressed archive
payload was 1,127,900 bytes under the 40,020,000-byte limit; the largest whole
case occupied 1,447,319 bytes under the 256 MiB limit. Physical preflight occurs
before `np.load`, and six hostile archive self-tests each recorded zero eager
NumPy loads while both public preflight and semantic hashing rejected them:

| Archive probe | Physical bytes | Result |
| --- | ---: | --- |
| Duplicate physical member | 605 | rejected before load |
| Header-declared oversize | 431 | rejected before load |
| Negative dimensions | 431 | rejected before load |
| NUL-truncated member name | 434 | rejected before load |
| Oversized zero-length itemsize | 435 | rejected before load |
| Zero itemsize with huge shape | 430 | rejected before load |

These tests cover duplicate/normalized names, NUL ambiguity, NPY header/shape,
itemsize, payload-length, dtype, and allocation hazards rather than trusting
logical `np.load` membership alone.

## 12. Exact-diagonalization realism evidence

The optional fixed-sector Heisenberg realism fixture generated twice with
byte-identical outputs and matched its packaged four-file copy. It contains 48
complete spectra represented by 144 target/control packets and 23,184 raw
eigenvalues. Sector dimensions were 70 at size 8 and 252 at size 10, matching
the binomial dimensions.

All eight invariants passed: real-symmetric Hamiltonians, finite complete
sector spectra, correct sector dimensions, normalized target selection,
bounded ratios, weak-field mean above strong-field mean, and weak-above-strong
ordering in every size-target group. Mean ratios were
`0.5031222903864401` weak versus `0.3967747341652005` strong, a margin of
`0.10634755622123959`; the minimum group margin was
`0.07309571411437954`. Observed realization means ranged from
`0.25316171807023113` to `0.6401027249147097`.

This fixture supports scientific realism but is not a hidden scoring target.

## 13. Evaluator robustness and security probes

All 14 manifest-defined malformed/security probes were safely rejected with
score zero:

| Category | Probe IDs |
| --- | --- |
| Malformed | `malformed_source`, `malformed_csv` |
| Nonfinite | `nan_statistic`, `infinite_statistic` |
| Partial/inventory | `partial_artifacts`, `extra_artifact` |
| Oversize | `oversized_source`, `oversized_output` |
| Security | `private_path_read`, `input_mutation`, `output_parent_escape`, `network_import`, `process_import`, `dynamic_exec` |

The filesystem supported hard links. Separate hard-link checks rejected a
hard-linked analyzer (`analyzer is hard-linked`) and a hard-linked produced
`claims.json` artifact. Submission/output inventory also enforces symlink,
junction/reparse, special-file, path traversal, and single-link regular-file
rules.

Trusted case and suite preflight failures raise
`EvaluatorConfigurationError` and abort evaluation; they are not converted to
a participant hard-gate failure or score zero. Participant execution stages one
validated flat case with copied analyzer/guard files in a fresh root. Child
argv, cwd, and environment expose no truth, oracle, author, or repository path;
reads/writes/imports/process/network/dynamic-code are guarded and output streams
are concurrently bounded.

The Python audit hook is defense in depth, not a complete hostile-code security
boundary. Production ALE must also enforce OS-level isolation.

## 14. Reproduction commands

From the task root:

```text
python -B scripts/verify.py --results author/verification_results.json --jobs 2 --command-timeout 600
```

Additional task-root commands:

```text
python -B author/oracle/generate.py --output-root <fresh-task-root>
python -B author/reference_solver/solve.py --participant participant --output <clean-submission>
python -B participant/software/validate_submission.py --submission <clean-submission> --run-public
python -B private/grader/grade.py --submission <clean-submission>
python -B author/alternative_solver/solve.py --participant participant --output <alternative-submission>
python -B private/grader/grade.py --submission <alternative-submission>
python -B private/mutants/build_mutants.py --source author/reference_solver/analyze.py --cases-root <fresh-root>/cases
python -B private/metamorphic/run.py --analyzer author/reference_solver/analyze.py --case private/hidden_inputs/case_amber --report <metamorphic-report.json>
```

## 15. Residual risks and next actions

- Peak memory was not instrumented by this verifier. Production ALE must
  measure and enforce the declared 8 GB limit as well as CPU and wall time.
- Production execution must use OS-level filesystem, process, resource, and
  network isolation rather than relying only on CPython audit hooks.
- The verifier mechanics are cross-platform, but exact byte/hash regeneration
  of numerically generated fixtures can remain sensitive to OS, NumPy, or BLAS
  behavior. A release executor should pin the declared environment and treat a
  cross-platform digest change as a review event rather than silently accepting
  it.
- Scientific collaborators should review whether the clustered-gamma-gap
  generated families are a fair grounded extension and retain the
  finite-size-only claim language.
- Pinned frontier-agent trials have not run. The package must remain labeled
  `structurally_hard_candidate` until such calibration is performed.
- Success on finite generated cases must not be interpreted as a thermodynamic
  localization-edge determination.

Subject to those explicitly scoped review and deployment items, the verified
package is **accepted for collaborator review**.
