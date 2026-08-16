# Paper2ALE extraction report: arXiv:1411.0660v2

Report date: 2026-08-15

## Session result

- Shared disposition: `accepted_for_collaborator_review`.
- Selected candidates: `spectral-scaling-audit-v1` and `disordered-sector-audit-v1`.
- Rejected candidates: `entanglement-ridge-table-v1` (too shallow) and `l22-shiftinvert-reproduction-v1` (resource- and missing-implementation-dominated).
- Finalized task dispositions: both selected tasks are `accepted_for_collaborator_review`, with status `needs_agent_calibration` and provisional difficulty `structurally_hard_candidate`.
- Verification: both exact builds pass their root verifiers, clean-room references, independent alternatives, private evaluators, mutants, metamorphic tests, projection checks, and paper-blind reviews.
- Production release: false. No frontier-difficulty claim is made for either task.

## Source and provenance

- Primary paper: arXiv:1411.0660v2, submitted 2014-11-03 and revised 2014-12-23. The exact v2 PDF is 1,940,511 bytes with SHA-256 `16bb369799942361d5af23e245bd9b09e05d93638a792128ba09cdd97a58c86e`.
- Exact arXiv v2 source archive: 1,662,089 bytes with SHA-256 `56eace8e902ef42aabd3e6674b6ca8027c01e50c10ff11ee9ab6c27fe92e33ca`.
- Supplement: bundled in PDF pages 6-7 and source `mbl.tex:359-436`; no distinct APS supplement byte stream was obtainable.
- Version comparison: v1 PDF/source and the APS article are separately identified and hashed in `source_manifest.yaml`. Task semantics use the qualified v2 wording where v1 and v2 differ.
- Official 2015 code or raw data: none found. No provider-generated numerical command, author executable, or source software was run.
- Later author repository: the 2018 method-adjacent Bitbucket repository is pinned at commit `706838f3e656f4792c170aa723067c2ae3111491`, is GPLv3, and is neither the 2015 workflow implementation nor used by either task.
- Recorded source issues include the v1/v2 wording change, odd-chain `S^z=1` notation ambiguity, standard-deviation/variance conflict for entanglement fluctuations, disjoint KL descriptions at `mbl.tex:162-168` and `mbl.tex:242`, absent raw figure data, and missing historical optimizer/bootstrap details.
- Paper and arXiv source bytes remain author-only. Generated-asset and runtime-dependency licensing still require final manual release review; redistribution approval is not claimed.

## Claim tree and selected workflow slices

The paper-level root is finite-size evidence for an energy-dependent localization crossover in the random-field Heisenberg chain. The claim tree separates model/sector setup, normalized energy targeting, spectral statistics, eigenstate diagnostics, realization-level statistics, scaling and uncertainty, finite-size evidence consistency, and resource-heavy production reproduction.

### Spectral task: verified

- Target leaf: `leaf-gap-ratio-fss-audit`.
- Included operation subgraph: `op-ssa-parse -> op-ssa-gap -> op-ssa-bin -> op-ssa-fit -> op-ssa-stability -> op-ssa-uncertainty -> op-ssa-report`.
- Scientific boundary: realization-aware adjacent-gap statistics, finite-size crossover fitting, held-out prediction, stability analysis, clustered uncertainty, and evidence-consistent finite-size claims. It does not reproduce a reported critical field or establish a thermodynamic mobility edge.
- Why structurally hard: the participant must combine robust packet/energy interpretation, nested spectral statistics, nonlinear scaling, sensitivity analysis, correlated uncertainty, prediction, and scientific reconciliation on fresh generated cases.
- Verification status: the hardened 126-file build passes all 14 required gates twice. Two independently organized solvers pass behavioral hidden scoring, all 15 scientific mutants are rejected, both solvers pass six metamorphic relations, the deterministic Heisenberg exact-diagonalization realism fixture passes, and two participant-only reviews find no material contract gap.

### Sector task: verified

- Target leaf: `leaf-joint-finite-size-signatures`.
- Target claim: on supplied finite ensembles, weak- and strong-disorder packets are jointly distinguishable through spectral and eigenstate diagnostics. The conclusion is finite-size and ensemble-specific; it is not a thermodynamic edge claim.
- Included operation subgraph: parse explicit experiments -> enumerate a fixed-`n_up` basis -> assemble the periodic spin-one-half Hamiltonian -> diagonalize and cache eigensystems -> select reversed-normalized-energy packets -> compute gap ratio, real-space EE, participation entropies, and subsystem magnetization -> aggregate within realization -> compare ensembles -> issue an evidence-linked conclusion.
- Structural metrics: nine meaningful operations, dependency depth nine, four branches, and multiple linked participant/private-rubric artifacts.
- Why genuinely hard: success requires correct combinatorial sector construction, normalization-sensitive Hamiltonian assembly, reusable eigensystems, sector-to-tensor Schmidt reconstruction, several independent observables, unequal-packet clustered statistics, fresh-sector/query/identifier generalization, and evidence provenance. One formula, one entropy, or one library call cannot satisfy the linked hidden rubrics.

## Candidate comparison

| Candidate | Leaf and backward slice | Verifiability | Difficulty quality | Decision |
| --- | --- | --- | --- | --- |
| `spectral-scaling-audit-v1` | gap-ratio packets through finite-size fit, stability, clustered uncertainty, prediction, and claims | Oracle, two valid solvers, four hidden families, 15 mutants, 14 probes, six metamorphics, archive gates, and an ED realism fixture pass | Long statistical workflow with fresh families and invariants | Accepted for collaborator review |
| `disordered-sector-audit-v1` | basis and Hamiltonian through eigensystems, multiple observables, realization aggregation, contrasts, and conclusions | Oracle, two valid solvers, hidden evaluator, mutants, fixtures, invariants, and robustness gates pass | Integrated many-body, numerical, statistical, and evidence workflow | Accepted for collaborator review |
| `entanglement-ridge-table-v1` | digitize or fit one plotted/table ridge | No raw-data oracle and weak hidden generalization | Easy leaf-level extraction | Rejected as too shallow |
| `l22-shiftinvert-reproduction-v1` | direct production-scale L=22 reproduction | No bounded independent oracle; historical settings absent | Difficulty dominated by compute and arbitrary gaps | Rejected |

## Visibility boundary

### What the spectral participant sees

The spectral participant package contains eight files totaling 1,468,388 bytes: a paper-blind `TASK.md`, retired neutral case (`manifest.json`, `packets.csv`, `eigenvalues.npz`, `queries.csv`, `analysis_grid.json`), and validator/README. It discloses exact schemas, numeric and archive bounds, realization/packet/group semantics, deterministic reference workflow, method-agnostic estimator allowance, qualitative/metamorphic criteria, and the Python 3.11+/NumPy environment. The participant submits only `output/analyze.py`; a run must emit `realization_stats.csv`, `packet_stats.csv`, `transition.csv`, `stability.csv`, `predictions.csv`, and `claims.json`. Participant-only reviews pass the exact final TASK, validator, and README hashes.

### What the sector participant sees

The sector participant package contains exactly four files totaling 21,092 bytes: `TASK.md`, a retired `experiment.json`, `software/validate_submission.py`, and its README. It discloses `L`, `n_up`, exchange, fields, subsystem queries, reversed energy targets, packet sizes, basis/bit/spin conventions, periodic bonds, tie/order rules, natural-log observables, realization-first statistics, output schema, qualitative success criteria, and a 4-CPU/8-GiB/20-minute/2-GiB-disk NumPy 2.3.5 environment with network and subprocesses disabled. The participant submits only `output/solution.py`, which must produce one result JSON containing `state_rows`, `aggregate_rows`, and `conclusions`. A fresh participant-only review passes after all initially identified material ambiguities were repaired.

### What remains hidden

- Private evaluator: fresh experiment/crossover families, generator seeds and parameters, reference artifacts, exact numerical tolerances, metric weights, score gates, mutants, metamorphic variants, and security probes.
- Author only: pinned paper/source bytes, bibliographic identifiers, evidence locators, version comparison, provenance and licensing analysis, claim/operation/artifact DAGs, candidate rationale, trusted generators, oracle implementations, reference solvers, and verification/calibration records.
- Neither participant package requires access to the paper, an official repository, private references, or the evaluator.

## Finalized spectral verification

- Exact build: `sha256:42c4b45503175b7bfce961de20a9fa5ab40f63a374ee8114ca25ddafbce7a8eb` over 126 files.
- Authoritative ledger: `tasks/heisenberg_mbl_edge/tasks/spectral_scaling_audit/author/verification_results.json`, SHA-256 `b6b53838fb5d2ae27825ea2e09b0c2d695a831dc679784f97f44eeebc6fded45`.
- Verification report SHA-256: `6d83f207aa4aca671a9210f2b5034d2200061b8b15a4f53856789b33dadf6436`.
- Root independent repeat: pass 14/14 in `308.45864439999787` seconds, with zero required failures. The preceding same-build authoritative run also passed 14/14 in `310.83801350000067` seconds and reproduced every score, digest, mutant, probe, and metamorphic result.
- Exact participant snapshot: TASK SHA-256 `9e578bff82c161fb5a6effa9b35417f26e53e9ba3ac503cf0ae4708fa29762c2`; validator `2079a06958294cf580cc707d230cc6acd583b1b03d6c8c45c573460a8478e99b`; README `0980bf232343a1b6814f3b96e745e82d2d31a8a2a7c2762691d41d68cfe9d5c8`.
- Privileged oracle: repeated generation matches 63 semantic files; four hidden inputs, 34 references, the retired case, and the realism fixture match packaged digests.
- Paper-blind participant-only numeric and specification reviews: pass on the exact participant snapshot.

### Reproduction commands and scores

From the repository root:

```text
python -B tasks/heisenberg_mbl_edge/tasks/spectral_scaling_audit/scripts/verify.py --results tasks/heisenberg_mbl_edge/tasks/spectral_scaling_audit/author/verification_results.json --jobs 2 --command-timeout 600
```

From the spectral task root, the author-only clean-room/reference sequence is:

```text
python -B author/reference_solver/solve.py --participant participant --output CLEAN_SUBMISSION
python -B participant/software/validate_submission.py --submission CLEAN_SUBMISSION --run-public
python -B private/grader/grade.py --submission CLEAN_SUBMISSION
python -B author/alternative_solver/solve.py --participant participant --output ALT_SUBMISSION
python -B private/grader/grade.py --submission ALT_SUBMISSION
```

The reference score is exactly `0.8996699182281552`; component scores are realization `1.0`, grouping `1.0`, held-out prediction `0.9264977680056898`, critical curve/exponent `0.5791808745280645`, stability `1.0`, uncertainty `0.8948481481481482`, and evidence `1.0`. The independent alternative score is exactly `0.8723372222137469`; its component scores are `1.0`, `1.0`, `0.9773965697360711`, `0.707702083967269`, `0.5005509014379065`, `0.8732186698144256`, and `1.0`. Both clear the aggregate and every per-case mandatory floor in repeated deterministic evaluation.

### Spectral mutant, metamorphic, robustness, and realism results

All 15 complete schema-valid scientific mutants are rejected with zero hard-gate failures across 14 categories: `target_mirror` 0.6247764199111627, `use_shift_energy` 0.7522688410977463, `unsorted` 0.24525477202395646, `raw_ratio` 0.3020180727683548, `pool_gaps` 0.8473686984239975, `gap_sem` 0.857521032255433, `no_size_scaling` 0.6958701096817309, `wrong_l_exponent` 0.6896277073796685, `largest_size_only` 0.7383250198739754, `constant_edge` 0.8493440215802439, `hardcoded_public` 0.7231143594521261, `no_stability` 0.7735891336230301, `skip_bootstrap` 0.8629296853404083, `stale` 0.8926699182281552, and `fabricated_claims` 0.8856699182281552. Every mutant fails a mandatory scientific component even when its total exceeds the private score threshold.

Both solvers pass all six metamorphic relations at `atol=5e-9`, `rtol=5e-8`: affine control (reference/alternative maxima `8.88e-16`/`1.02e-14`), positive affine energy (`1.81e-14`/`2.35e-14`), realization-ID bijection (`0`/`0`), row/packet permutation (`4.44e-16`/`4.44e-15`), shard split/rejoin (`4.44e-16`/`2.43e-14`), and target/energy mirror (`4.44e-16`/`7.99e-15`). The conditioned affine-energy map preserves all 3,132 selected prefixes; maximum retained-ratio perturbation is `7.6972e-13`, below `1e-10`, and shift/span is `0.0038061`, below `0.005`.

All 14 malformed/nonfinite/partial/oversize/security probes reject safely at score zero. Analyzer and produced-artifact hard links reject. Six physical NPZ adversaries—duplicate member, oversized header, negative dimensions, NUL-truncated name, oversized zero-length itemsize, and zero-itemsize huge shape—reject before any eager `np.load`. Affine scale 3.0 rejects before destination creation, and the malformed metamorphic CLI emits the exact structured failure JSON.

The fixed-sector Heisenberg realism fixture passes twice byte-identically: 144 packets, 23,184 eigenvalues, and sector dimensions 70/252. Weak/strong mean ratios are `0.5031222903864401`/`0.3967747341652005`, with overall margin `0.10634755622123959` and minimum group margin `0.07309571411437954`. It is an invariant gate, not scored scaling truth.

### Spectral tolerance justification

- Direct realization/group statistics receive tight deterministic allowances: excellent knots `2e-7` and `3e-7`, with minimum-credit error `0.012`; group SEM uses `3e-7` excellent and `0.006` minimum-credit.
- Fitted quantities use continuous behavioral knots because finite sampling and valid estimator choice make exact equality inappropriate: held-out mean `0.010` to `0.065`; crossover coordinate `0.10` to `0.52`; exponent `0.18` to `0.95`; stability coordinate/exponent/RMSE `0.035/0.08/0.002` to `0.42/0.75/0.045`; transition/query log-width excellent `0.08` with minimum-credit `2.2/1.8`.
- The private pass threshold is `0.76`. Four-case components aggregate as 80% mean plus 20% worst case and then apply aggregate and per-case floors. The two scientifically distinct solvers pass; every calibrated mutant is rejected, demonstrating margin without exact-fit overconstraint.

### Spectral hidden validity and resources

Four unpublished clustered-gamma-gap crossover families contain 2,806-3,132 packets and 102-108 groups, with critical-curve spans `0.5587584` to `0.7450624` and minimum weak-minus-strong margins above `0.1406`. They cover unequal realization sampling, missing grids, shifted/rescaled and asymmetric curves, and edge target slices. The visible `retired_cedar` case is absent from hidden scoring.

The two final same-build verifier runs complete in about 5.14-5.18 minutes within the declared 20-minute participant budget. The largest packaged case is 1,447,319 bytes and largest uncompressed NPZ payload 1,127,900 bytes. Peak RSS was not instrumented; the 8-GiB limit still requires target-infrastructure measurement.

## Finalized sector verification

- Exact build: `sha256:9dc29e54c250afdb07aa10391431147535ece606b2f4eee3cd9fcd0c00cc6b73`.
- Authoritative ledger: `tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/author/verification_results.json`, SHA-256 `0d9f3e2bfe2e647d90dc7efeb4c0ec41bfceeb77859572cde4b73a5ef6f5b995`.
- Verification report SHA-256: `f303080e80df6f74f51a5553299a913b7aa908a8906e5d2e6ea438bdf889ddc0`.
- Root verifier: pass in `49.1263065000021` seconds; the preceding same-build run passed in `47.03349860000162` seconds.
- Privileged oracle: two byte-deterministic generations in `1.9328316` and `1.8965305` seconds; all 36 weak-minus-strong target effects are positive.
- Clean-room reference: two participant-only runs in `0.1737066` and `0.1591180` seconds produced byte-identical 79,873-byte JSON (SHA-256 `2cbebda0376a7772bce7e3be2279784f0d94e1820e73460271383e9044a1f54b`). Hidden score is `1.0` twice, with every per-experiment mandatory score equal to `1.0`.
- Independent alternative: hidden score is `1.0` twice. Two guarded public runs are byte-identical and also score `1.0`.
- Paper-blind participant-only specification review: pass.

### Reproduction commands

From the repository root:

```text
python tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/scripts/verify.py
```

Author-only oracle and direct reference/grader entry points:

```text
python -B tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/author/oracle/generate.py --task-root tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit --check
python -B tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/author/reference_solver/solution.py --experiment tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/participant/input/retired_experiment --output RESULT.json
python -B tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/private/grader/grade.py --participant tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/participant --submission SUBMISSION_DIR
python -B tasks/heisenberg_mbl_edge/tasks/disordered_sector_audit/author/alternative_solver/solution.py --experiment EXPERIMENT --output RESULT.json
```

The full verifier, not a direct author command in isolation, establishes the participant-only clean-room boundary. Its staged child has the shape:

```text
python -I -B guard.py source/solution.py input output/result.json STAGE_ROOT
```

## Sector mutant, metamorphic, and robustness results

All 12 complete, schema-valid scientific mutants are rejected: `pauli_scale` 0.00, `unit_exchange` 0.333, `open_boundary` 0.00, `wrong_energy_normalization` 0.00, `one_sided_packet` 0.00, `shannon_entanglement` 0.40, `log2_entanglement` 0.40, `s2_ipr` 0.40, `mz_second_moment` 0.65, `naive_aggregation` 0.70, `sem_over_states` 0.80, and `stale_evidence` 0.70. Every mutant crosses structural/execution gates and fails at least one mandatory scientific metric; no total exceeds 0.80 against the private 0.95 pass threshold.

Five metamorphic families pass in the privileged oracle, clean-room reference, and independent alternative: cyclic site relabeling, uniform fixed-sector field shift, common Hamiltonian scaling, global spin flip in a nonzero sector, and input-record permutation. Maximum errors are approximately `2.43e-13` in the oracle and `1.64e-13` in participant-facing solvers, below the `2e-10` metamorphic ceiling; permutation error is zero. Four analytic Hamiltonian/product/Bell-state fixtures also pass, with maximum error `4.44e-16`.

Robustness checks cover malformed/partial JSON, NaN/Inf, oversized artifacts, stale identities, syntax errors, extra submission files, context corruption, fabricated evidence, output/console floods, traversal/private reads, process/network attempts, and link attacks. Twenty-seven live probes pass or reject safely. Five platform-specific probes are unavailable on the current Windows host: `os_fork`, `os_forkpty`, `os_posix_spawn`, submission-root symlink, and `solution.py` symlink. In-child symlink creation and hard-linked solution/result files are live-rejected. Python audit hooks and staged path controls are defense in depth; they do not replace the production ALE OS sandbox.

## Sector tolerance justification

- Exact comparison is used for identifiers, counts, indices, categorical fields, and Boolean conclusion flags.
- State-level eigenvalue, normalized-energy, gap-ratio, EE, participation, and magnetization values use `max(2e-8, 1e-7*abs(reference))` elementwise.
- Realization aggregates, SEM values, and conclusion effects use `max(5e-8, 2e-7*abs(reference))` elementwise.
- Sparse-loop and vectorized implementations, SVD and reduced-density routes, and repeated BLAS runs disagree below `2e-12`; analytic fixtures are within `4.44e-16`. The tolerances leave a broad float64/eigensolver/reduction-order margin while every realistic scientific mutant remains outside a mandatory metric.

## Hidden validity and resource evidence

- Three fresh hidden suites span `L=9,10,12`, half and non-half sectors, exchange `1.0,1.35,0.8`, 28 records, opaque/disjoint identifiers, two or three queries, wraparound cuts, reversed targets, and packet sizes from 2 to 15. They contain 66 hidden record-query rows; the verifier checks 86 retired-plus-hidden record-query row counts against their query-specific packet sizes.
- The minimum hidden gap-ratio weak-minus-strong effect is approximately `0.05273`; the direction flag is finite-ensemble evidence, not statistical significance.
- Largest scored sector: `L=12,n_up=5`, dimension 792. A separate `L=12,n_up=6` probe has dimension 924, a 6,830,208-byte dense matrix, and runs in `0.1616314` seconds.
- The public contract supports `L<=14`, but this build has no L=14 scored instance. Peak RSS was not measured on this Windows host.

## Unresolved risks

- Scientific: finite supplied ensembles do not establish asymptotic localization or a mobility edge. Four or five realizations per condition provide deterministic benchmark discrimination, not precision inference or a significance claim.
- Numerical: generated spectra are nondegenerate and conditioned; a broader future generator must retain that contract or add subspace-aware evaluation.
- Spectral scientific scope: the clustered-gamma-gap families are a grounded finite-size extension, not paper-number reproduction; collaborators should review their scientific fairness and preserve the finite-size-only claim.
- Numerical portability: exact generated fixture bytes can vary across OS, NumPy, or BLAS; production should pin the environment and treat digest drift as a review event.
- Security/platform: production OS/container isolation, process-tree and memory quotas, POSIX process probes, privileged symlink/junction CI, peak-RSS measurement, target ALE integration, and a redacted participant-feedback adapter that never exposes private evaluator diagnostics remain open.
- Release hygiene: checked-in review seeds must be rotated to server-secret streams; final generated-asset/dependency licensing and independent scientific expert review remain open.
- Difficulty: no pinned frontier-agent calibration has run, so both tasks remain provisional `structurally_hard_candidate` at most.

## Current decision

Both `spectral-scaling-audit-v1` and `disordered-sector-audit-v1` are accepted for collaborator review as locally verified, paper-blind, finite-size workflow tasks. Each remains `needs_agent_calibration` with provisional difficulty `structurally_hard_candidate`. Neither task is approved for production/public release or described as frontier difficulty.
