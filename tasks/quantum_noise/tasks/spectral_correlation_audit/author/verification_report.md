# Verification report: spectral-correlation-audit-v1

## Decision

- Status: `needs_agent_calibration`; all local gates pass and the task is ready for collaborator scientific review
- Provisional difficulty: `structurally_hard_candidate`
- Frontier-agent calibration: not run
- Blocking issue for release as a calibrated hard task: no pinned frontier-agent run
- Exact task build: `sha256:0bba762f4be56c68c2b20c5147c99d37b716f47ae74a8cff88f7f2271e796a1b`
- Participant projection: `sha256:eaeef52ee4dc8f7c97ef26d0bb2070a42feb3d50ec21da9499be2dbe817fa1d2`
- Full verifier: pass in `79.21037350000188` seconds; final command recorded in section 14

## 1. Source and provenance

- Paper/version: arXiv 1907.13022v2, 16 April 2021
- Paper SHA-256: `4867308d9d0033d9d0cbe1cf723cb00d569c4b8cd22588b4c1ba611af93c7684`
- Source archive SHA-256: `3536360ef4a538e77d4ef7677e796fa34bb0de6a14414894a441f93f2f00602c`
- Extracted TeX SHA-256: `77bf5189ecb0cb9f56486ef520fc4a68ae5a8737d3cf249beffe02b63e2525bd`
- Official analysis repository: Juqst.jl commit `533d0c46f29638e0a235ab58ce2cd86591a4e966`, MIT
- Official dataset repository: commit `11624f8cb32f81fca4e2f8c7a570d8e09672f659`, CC0; incomplete local checkout and not used
- Acquisition/XOR evidence: query_ibmq commit `d73e1002f5f0ec35f54bf47c338f8c28eaaaa954`, MIT, remotely inspected and not retained in the package
- Source execution: no provider command, notebook, pickle, or proprietary Wolfram workflow was executed
- Grounding: paper TeX lines 157-168 (five-stage workflow), 1362-1391 (transform), 1497-1510 (nuisance decay), 1069-1113 (dependence), 1118-1142 (JS/TV), and 2081 (nearest simplex)
- Conflicts resolved publicly: paper Methods versus Juqst log base and JSD square root; benchmark uses natural-log information and square-root JS distance
- Grounded benchmark choices: all-length bounded least squares replaces the source tail cutoff; small synthetic XOR-convolution cases replace incomplete device data; clique-tree factorization is a disclosed decomposable local-model specialization

## 2. Target leaf and workflow boundary

- Target leaf: `claim-leaf-long-range-correlations-and-local-model-mismatch`
- Scientific target: determine whether a distribution recovered from randomized count decays contains interactions outside a supplied local model and quantify the mismatch
- Included operations: XOR correction/pooled aggregation; unnormalized WHT; `A*lambda^m` fits; inverse WHT; Euclidean simplex projection; MI/CMI/Pearson; junction-tree reconstruction; JS/TV; nonlocal CMI ranking
- Meaningful operations: 7
- Dependency depth: 7 in the task package; shared workflow graph records the same coherent backward slice
- Public boundary: neutral manifest, retired synthetic counts, complete mathematics, schemas, valid-input envelope, environment, and validator
- Private boundary: hidden inputs/seeds, latent truth, exact thresholds/weights, runner, references, and mutants
- Derivation: reported workflow slice with grounded hidden generalization and local-model extension

## 3. Specification closure

| Solution-critical decision | Disclosed | Inferable | Method-agnostic | Invalid hidden dependency | Evidence |
| --- | ---: | ---: | ---: | ---: | --- |
| XOR and pooled weighting | yes |  |  | no | `participant/TASK.md` section 1 |
| Mask order and transform normalization | yes |  |  | no | section 2 gives the exact kernel |
| Fit objective, bounds, powers and tie rule | yes |  | optimizer | no | section 3 and valid-input envelope |
| Inverse and simplex projection | yes |  |  | no | section 4 |
| MI/CMI/Pearson variables, zero terms and log base | yes |  |  | no | section 5 |
| Clique-tree scopes, separators and state indexing | yes |  |  | no | section 6 |
| JS distance and TV definitions | yes |  |  | no | section 6 |
| Ranking eligibility, metric and ties | yes |  |  | no | section 6 |
| Input sizes, validity, outputs and security | yes |  |  | no | valid-input envelope and runtime sections |

All rows closed: yes.

### Paper-blind specification review

- Reviewer/context: fresh `fork_turns=none` agent restricted to `participant/`
- First result: fail; it identified non-unique decay edge cases, undefined `0^0`, an incomplete hidden validity envelope, missing exponential size bounds, and an overstated public-validator claim
- Resolution: added canonical fit ties, `lambda^0=1`, positive identifiability, full schema/topology/count guarantees, `n<=8` and row/length/clique limits, authoritative `count_file`, explicit information formulas, integer serialization, public simplex tolerances, and stronger validation
- Final re-review: unconditional pass after the byte/identifier, clique-count, strict-type, ranking, separator-floor, quantitative fit-conditioning, source-policy, live-limit, atomic-rename, and UTF-8 BOM edits; reviewed validator SHA-256 `97188585dcef4bce2e7f89ff12505ac945af731e0674c74cb8e0d58f5df24ef3`

## 4. Intrinsic difficulty audit

- Required submission: one reusable executable that produces six linked artifacts on unseen instances
- Independent challenge sources: randomized-mask/index conventions; nuisance nonlinear fitting without length zero; simplex geometry; information diagnostics; graphical-model reconstruction; hidden dimension/topology/correlation shift
- Expected expert effort: 8-16 hours
- Not a leaf question: the concrete nonlocal-correlation leaf is reached only after the seven-operation backward workflow slice
- Not clone-and-run: participant interface and synthetic cases do not occur in official sources
- Not one formula: thirteen independent linked/schema-valid stage mutants fail mandatory scientific checks, while one well-formed ascending-ranking mutant fails the exact global-top-k linkage gate; the suite includes a branched-topology hard-coding probe
- Not hidden-trivia difficulty: all scientific conventions and input bounds are public

## 5. Privileged oracle run

- Command: the `privileged-truth-oracle-and-evaluator-self-consistency` gate in `python scripts/verify.py`
- Environment: CPython 3.12.13, NumPy 2.3.5, CPU only
- Privilege boundary: this gate reads the generator's latent distribution, nuisance law, eigenvalues, amplitudes, and hidden inputs directly; it is not a participant-style analyzer
- Checks: independently recomputes both character transforms, every supplied-length XOR-convolution law, probability validity, physical support-to-observed visibility, truth-linked dependence/local/ranking values, and an ideal in-memory evaluator record for all four cases
- Evaluator result: total score `1.0`; pipeline, spectral, distribution, local-model, and ranking components `1.0`, dependence `0.9999999999999999`; maximum generator/truth consistency error `4.440892098500626e-15`
- Physical latent-truth result: minimum Pauli-support probability `5.715357517013917e-08`; maximum support/visibility inverse round-trip error `3.3306690738754696e-16`
- The latent truth record has one expected participant-contract exception, `bounded-decay-global-minimum`, because latent parameters need not minimize a finite-shot noisy-count objective; the canonical executable below exercises that gate
- Separately, `private/reference/canonical_submission/analyze.py` is run twice through the executable parser/evaluator and scores `0.996904859452196`; it is explicitly a canonical behavioral reference, not the privileged oracle
- Privileged gate runtime: `0.9042129999979807` seconds; canonical two-grade runtime: `3.1235209000005852` seconds
- Status: pass

## 6. Clean-room public-input reference run

- Construction: temporary directory containing only `participant/`, the reference solver, and declared runtime; submission construction has no private files or network
- Solver command: `python -I -B author/reference_solver/solve.py --participant participant --submission submission`
- Analyzer interface: `python analyze.py --input INPUT_DIR --output OUTPUT_DIR`
- Public validator: pass
- Private evaluator score: `0.996904859452196`
- Hidden access audit: solver source contains no private/hidden/network marker; participant hashes are checked before/after
- Analyzer construction runtime: `0.050333600000158185` seconds
- Public validator runtime: `0.3220379000013054` seconds
- Two deterministic private grades: `2.9397456999977294` seconds

## 7. Alternative valid implementation

- Algorithmic independence: multi-start damped Gauss-Newton in amplitude/log-decay coordinates and bisection simplex threshold; reference uses profiled lambda grid/golden search and sort-threshold projection
- Score: `0.996904859477264`
- Component agreement: aggregate score difference from reference `2.5068e-11`
- Analyzer construction runtime: `0.07006809999802499` seconds; two deterministic private grades: `8.759107800000493` seconds
- Status: pass

## 8. Tolerance calibration

| Metric | Valid-solver variation | Absolute tolerance/floor | Relative tolerance | Justification |
| --- | ---: | ---: | ---: | --- |
| Aggregate/WHT consistency | worst valid ratio `2.54e-7` | `2e-10` | `2e-9` | direct integer aggregation and dense character transform |
| Fit residual consistency | valid ratio `0.0` | `2e-9` | `2e-7` | canonical global optimum, independent optimizer, and serialization |
| Raw inverse/simplex consistency | worst valid ratio `3.02e-9` | `5e-9` | `5e-7` | transform conditioning and two projection algorithms |
| Dependence/local/summary consistency | worst valid ratio `3.80e-10` | `5e-8` | `5e-6` | recomputation from submitted distribution |
| Latent distribution TV | reference worst `0.01033` | excellent `0.025` | not applicable | finite-shot variation across hidden cases |
| Eigenvalue RMSE | reference worst `0.00355` | excellent `0.010` | not applicable | private latent truth and alternative agreement |

Deterministic consistency uses `max(abs_tol, rel_tol * abs(reference))`. Sampling-sensitive scientific scores use piecewise continuous errors calibrated above the worse of the two valid solvers and separated from realistic mutants. Four fixed authoring seeds are aggregated as `0.75*mean + 0.25*minimum`; server-secret regeneration is required for scored release.

## 9. Mutant results

Thirteen mutants execute, pass parsing and cross-artifact hard gates, and fail a
mandatory scientific check. The `ascending-cmi-ranking` mutant emits well-formed
artifacts but deliberately violates the exact global-top-k cross-artifact
contract, so it is rejected by that hard gate before scientific scoring.

| Mutant | Category | Score | Result |
| --- | --- | ---: | --- |
| ignore-target-mask | XOR correction | `0.3071359334167724` | fail mandatory contract |
| normalized-forward-transform | transform normalization | `0.4723322308077341` | fail mandatory contract |
| ordinal-length-fit | length semantics | `0.6232598957529517` | fail mandatory fit |
| unit-nuisance-amplitude | nuisance model | `0.9569048594521959` | fail mandatory fit |
| unnormalized-inverse | inverse normalization | `0.6785222296265495` | fail mandatory inverse |
| independent-bit-collapse | omitted correlations | `0.8611590952159185` | fail mandatory projection |
| omit-clique-separators | local factorization | `0.8473465233556567` | fail mandatory local |
| mi-reported-as-cmi | wrong dependence metric | `0.96` | fail mandatory dependence |
| covariance-as-correlation | correlation normalization | `0.9511824110553024` | fail mandatory dependence |
| ascending-cmi-ranking | ranking direction | `0.0` | fail hard global-top-k gate |
| js-divergence-not-distance | wrong distance | `0.959404859452196` | fail mandatory summary |
| uniform-stale-analysis | stale/hard-coded behavior | `0.45491127039796103` | fail mandatory linked artifacts |
| reversed-unit-significance | bit convention | `0.9354812372378294` | fail mandatory dependence |
| chain-topology-assumption | topology hard-coding | `0.9275068445271316` | fail mandatory dependence/local/summary |

Displayed scores are rounded; `verify.py` records exact values.

## 10. Metamorphic and invariant tests

| Test | Expected relation | Status |
| --- | --- | --- |
| Common target/observed XOR | every semantic artifact unchanged | pass; max difference `0.0` |
| Row split and reversal | every artifact unchanged | pass; max difference `0.0` |
| Uniform count scaling | counts scale; probabilities/downstream unchanged | pass; max semantic difference `0.0` |
| WHT involution | `H(H(v)) = 2^n v` | pass; max error `2.842170943040401e-14` |
| Physical visibility roundtrip | support law survives thinning and inverse | pass; max error `3.469446951953614e-17` |
| Clique marginal preservation | local reconstruction preserves every clique marginal | pass; max error `4.440892098500626e-16` |
| Local Markov CMI | non-co-clique all-rest CMI is zero under local reconstruction | pass; max `2.3004794429676218e-17` |

## 11. Evaluator robustness

The final verifier rejects all 28 hard malformed/security cases. These cover
malformed and oversized source, forbidden import/link/process/native-code
capabilities, private and parent-path reads, relative low-level file access,
audit-policy monkeypatch attempts, protected-input/case-root mutation,
truncate/ftruncate, aliased dynamic evaluation/import, partial/extra/nonfinite/
duplicate/oversized artifacts, fabricated ranking values, signed-64-bit
overflow, zero-mass held-out prediction, oversized CSV fields, and live console
overflow. A schema-valid fabricated summary scores `0.959404859452196` but fails
its mandatory summary gate. Six valid variants covering strict output-root
creation, benign `str.replace`, ordinary instance state, ordinary `setattr` and
dunder use, inside-output rename/truncate/remove, and UTF-8 BOM source all pass at
`0.996904859452196`.
Three high-scoring contract-bypass probes are rejected: corrupted counts
`0.9945924989611246`, shifted amplitudes `0.9468969703763492`, and a zero raw
inverse `0.929404859452196`. Source and runtime hardlinks are rejected by both
applicable parsers; root-symlink creation was unavailable on this Windows host.
The public runner rejects both live console and live artifact-growth probes and
executes an immutable copy of its checked source bytes. Deterministic repeats,
participant leakage, stale behavior, protected-tree snapshots, and package
non-mutation also pass. The local Python audit-hook harness is defense in depth,
not a hostile-code sandbox; real ALE container isolation remains required before
scored deployment.

## 12. Hidden-instance validity

- Generator: `author/oracle/generate.py`
- Checkout stability: generator-controlled JSON and CSV use explicit LF endings; the final task-tree CRLF scan found zero files
- Model: `q_m = r *_xor p^(*_xor m)` so `WHT(q_m)=A*lambda^m`
- Hidden cases: four; bit counts 6-8; irregular grids; two omit length zero; three chain clique trees and one degree-three branched running-intersection tree
- Varying factors: target masks, pooled shots, nuisance flips, topology, local log-linear potentials, and injected nonlocal interactions
- Checked invariants: strict positive observed truth; minimum eigenvalue `0.47616738149091875`; normalized nonnegative Pauli-support truth under the two-thirds visibility map; detectable local mismatch; stable positive top-k gains; canonical separator marginals at least `0.001726755740890`; and minimum profiled-SSE gap `2.067167705572545e-09` at a `1e-4` displacement
- Scope caveat: physical support is a latent-generator invariant only. Finite-shot fitted/simplex participant estimates are required to be valid observed binary distributions, not valid full Pauli-channel distributions.
- Public review seed is retired. Fixed hidden seeds are review-only.

## 13. Participant package audit

- Visible files: `TASK.md`, `input/manifest.json`, `input/raw_counts.csv`, `software/README.md`, and `software/validate_submission.py`
- Paper/source identifiers: removed
- Complete task semantics: yes after closure edits
- Private artifacts included: none
- Public input rows: 23,474 data rows; 114 distinct randomized targets and high-bit targets exercised
- Declared runtime: CPython 3.12, NumPy 2.3.5, CPU, network off, 45 seconds per case, 8 GB, 8 MB runtime output
- Exact participant projection: `sha256:eaeef52ee4dc8f7c97ef26d0bb2070a42feb3d50ec21da9499be2dbe817fa1d2`

## 14. Commands to reproduce verification

The final unified run completed in `79.21037350000188` seconds with no required
failures and emitted exact build ID
`sha256:0bba762f4be56c68c2b20c5147c99d37b716f47ae74a8cff88f7f2271e796a1b`.

```text
python tasks/quantum_noise/tasks/spectral_correlation_audit/scripts/verify.py
```

Direct diagnostic commands:

```text
python tasks/quantum_noise/tasks/spectral_correlation_audit/private/grader/grade.py tasks/quantum_noise/tasks/spectral_correlation_audit/private/reference/canonical_submission
python tasks/quantum_noise/tasks/spectral_correlation_audit/participant/software/validate_submission.py tasks/quantum_noise/tasks/spectral_correlation_audit/private/reference/canonical_submission
```

## 15. Remaining risks and next actions

- Scientific: collaborator should confirm that the grounded clique-tree specialization and all-length fit are appropriate extensions of the reported workflow
- Engineering: real ALE OS/container network/filesystem/memory isolation is not exercised by this local Windows audit-hook harness
- Measurement: peak resident memory was not instrumented; no out-of-memory event occurred, but the declared 8 GB ceiling still requires production-container enforcement
- Reproducibility: exact Julia runtime and complete empirical notebook checkout are unavailable but not dependencies of the synthetic task
- Calibration: no pinned frontier-agent trials; the only warranted label is `structurally_hard_candidate`
- Deployment: replace fixed review seeds, retire all exposed instances, update exact task build hash, and run ALE integration
