# Verification report: periodic-orbital-transport

## Decision

- Lifecycle status: `needs_agent_calibration`
- Collaborator disposition: `accepted_for_collaborator_review`
- Provisional difficulty: `structurally_hard_candidate`
- Frontier-agent calibration: not run on the exact final build
- Blocking issues for collaborator review: none
- Publication conditions still open: pinned frontier-agent calibration, independent scientific review, and a production ALE outer-sandbox run

This is one selected task, although the session preference was two. No second
candidate met the hard-only, paper-blind, closed-specification, and bounded
verification standard, so a weaker task was not forced.

## 1. Source and provenance

- Paper/version: M. V. Klymenko, J. A. Vaitkus, J. S. Smith, and J. H. Cole,
  *NanoNET: an extendable Python framework for semi-empirical tight-binding
  models*, arXiv:2010.07463v1, submitted 2020-10-15, corresponding to Computer
  Physics Communications 259 (2021) 107676.
- Pinned paper: `../../authoring/sources/2010.07463.pdf`, 4,179,539 bytes,
  14 pages, SHA-256
  `d239584d5be9d87d2f39cdedf97e401f828176f4bb8cc68d8c42ca568e287f91`.
- Official repository: `https://github.com/freude/NanoNet`, MIT license.
- Current inspected commit: `0c71da6c53129fcc0794efa7f35610ed9f44e135`
  dated 2026-08-14, declared version 1.9.9. It was used only for static
  corroboration and conflict discovery.
- Nearest located pre-paper commit:
  `50d02856b5bcfcf9a91de6d46ebd54bf24938797`, dated 2020-09-22. The read-only
  TAR is 3,747,840 bytes with SHA-256
  `ad51448dfca44e58971a65bf6a25c5869ce40adc6497662b2f38f9c0848bb6f4`.
- Dataset/version: none. All participant and hidden instances are newly
  generated synthetic records.
- Licenses: official source is MIT. No redistribution license was asserted for
  the paper PDF, so the PDF, checkout, and archive remain author-only.
  Benchmark-authored participant assets are eligible for redistribution.

Paper/code/configuration conflicts were handled as follows:

| Topic | Evidence conflict | Resolution in this task |
| --- | --- | --- |
| DOS normalization | Paper Equation (10) implies `-2 Im Tr(G)/pi`; example code uses a block-averaged expression without that factor or `pi`. | Public spinless convention is `-Im Tr(G)/pi`, with cell LDOS using the corresponding block trace. |
| Retarded damping | The paper uses `E+i0+`; example calls pass an imaginary `damp`, while source code multiplies `damp` by `1j` again in one path. | Public contract fixes real positive `eta` and `z=E+i*eta`. |
| Left/right orientation | Source documentation, cropped ends, and return order use inconsistent left/right naming. | Public contract fixes `B_left=H1^H`, `B_right=H1` and both contact matrices explicitly. |
| Version drift | The current checkout postdates arXiv v1 by nearly six years. | Current and nearest pre-paper commits are pinned separately and are not participant dependencies. |
| Complex-band Equation (7) | The printed lower-right block appears to omit an inverse used by the adjacent block; source solves a generalized problem instead. | That side branch was excluded. The selected task uses the unambiguous Hermitian Bloch Hamiltonian. |
| Block optimality | Source implements recursive local sum-of-cubes cuts without a global optimum proof. | The block-optimization candidate was rejected, so the unresolved terminology is not a selected-task requirement. |
| Missing silicon assets | The PDF refers to supplementary coordinates and predefined Si/H parameters not contained in the paper. | Exact Figure 9 reproduction was rejected; every selected-task geometry and parameter is public synthetic input. |

Grounded workflow evidence is recorded in
`../../authoring/evidence_map.yaml`, with the claim tree and operation/artifact
DAG in `../../authoring/workflow_graph.yaml`. All 14 paper pages were rendered
and visually inspected. Provider code was inspected statically and was not
imported into the oracle, solvers, or evaluator.

## 2. Target leaf and workflow boundary

- Target claim/result leaf: `claim-leaf-periodic-bands-dos-transmission`, the
  paper's Figure 9 silicon-nanowire band structure, density of states, and
  coherent transmission result on pages 9-10.
- Scientific meaning: these are the paper's central periodic electronic
  structure and open-boundary transport observables, rather than an incidental
  implementation statistic.
- Derivation type: `grounded_extension`. The task preserves the scientific
  workflow and equations on fully disclosed neutral synthetic systems; it is
  not a numerical reproduction of the paper's silicon figure.
- Public boundary: JSON geometry, basis, onsite and hopping data, grids,
  broadening, finite-device perturbations, every convention, CLI, schemas,
  limits, and qualitative criteria are participant-visible.
- Private boundary: ten hidden instances and seeds, exact reference arrays,
  thresholds, weights, mutant sources, and oracle convergence details.

Included participant operations, in dependency order:

1. Enumerate same-cell and forward-image neighbors with the disclosed cutoff.
2. Assemble signed, direction-dependent heterogeneous `s`/`sp3` hopping blocks.
3. Assemble the one-cell `H0` and forward `H1` matrices in site-major order.
4. Compute ordered Bloch bands from `H(theta)`.
5. Build the cell-dependent finite-device Hamiltonian.
6. Select causal retarded left/right surface solutions and form contact self-energies.
7. Form the device Green function and compute DOS, cell LDOS, and Caroli transmission.
8. Report identity, Hermiticity, and surface-residual evidence.

The workflow branches after `H0/H1` into periodic bands and finite-device
transport, then rejoins in the spectra and diagnostics artifacts. Private
rubric intermediates include neighbor pairs, orbital blocks, `H0/H1`, bands,
the finite-device Hamiltonian, both surface Green functions, both contact
self-energies, and device Green-function observables. Participants submit
`hamiltonian.npz`, `self_energies.npz`, `spectra.npz`, and
`diagnostics.json` in addition to `output/solution.py`.

## 3. Specification closure

| Solution-critical decision | Disclosed | Inferable | Method-agnostic | Invalid hidden dependency | Evidence |
| --- | ---: | ---: | ---: | ---: | --- |
| Basis ordering and allowed orbital sets | yes | no | no | no | `TASK.md`, Input contract and Basis convention |
| Neighbor images, direction, inclusive cutoff, zero-distance rule | yes | no | no | no | `TASK.md`, Neighbor enumeration |
| Slater-Koster `s/p` signs and matrix elements | yes | no | no | no | `TASK.md`, Hopping blocks |
| `H0/H1` orientation and Bloch phase | yes | no | no | no | `TASK.md`, Periodic Hamiltonian |
| Device potentials, bond scales, block order, and `C==1` | yes | no | no | no | `TASK.md`, Finite device |
| Retarded broadening, outward lead orientation, contacts | yes | no | no | no | `TASK.md`, Retarded lead surfaces and contacts |
| Surface numerical algorithm | no | no | yes | no | Any stable method selecting the disclosed retarded solution is accepted. |
| DOS/LDOS/transmission and spin normalization | yes | no | no | no | `TASK.md`, observable equations |
| CLI, files, keys, dtypes, shapes, residual definitions | yes | no | no | no | `TASK.md`, Required entry point and outputs |
| Exact equivalence thresholds and hidden aggregation | no | no | yes | no | Public qualitative criteria plus private double-precision calibration |

All rows closed: yes.

### Paper-blind specification review

- Reviewer/context: fresh paper-blind subagent, followed by an isolated rereview
  after the bounded-domain contract edits.
- Source access confirmed absent: yes. The reviewer attests that no paper,
  author file, private file, official implementation, hidden case, Git history,
  or external reference result was inspected.
- Task restatement: correctly identified geometry-to-`H0/H1`, Bloch bands,
  finite device, two retarded surfaces, self-energies, DOS/LDOS, transmission,
  and residual artifacts.
- Missing definitions or files: none material.
- Intended method freedom: understood; the causal surface method is open while
  the equations and outputs are fixed.
- Material ambiguities resolved: public bounds, numeric scales, input and
  output limits, integral JSON handling, and the actual public fixture names
  now agree across `TASK.md`, schema, helpers, and shipped files.
- Status: PASS, with no blocking or nonblocking findings.

The refreshed review file is `author/paper_blind_review.md`; it confirms no
blocking or nonblocking findings and an exact cache-free participant inventory.

## 4. Intrinsic difficulty audit

- Meaningful operation count: 8.
- Dependency depth: 7.
- Branch count: 2 major scientific branches after periodic assembly.
- Tools: one declared numerical package, NumPy, plus the Python standard library.
- Required artifacts: one executable source and four mutually consistent data artifacts.
- Independent challenge sources: geometric heterogeneous multi-orbital
  assembly; causal nonlinear matrix surface solving for two orientations; and
  cross-stage periodic/device/spectral integration.
- Public-input volume: two compact review cases, one scalar diatomic and one
  rotated heterogeneous multi-species case.
- Expected expert effort: approximately 8-16 focused hours for convention
  translation, assembly, solver selection, integration, and invariant testing.

The task is not one formula because an assembly error changes both downstream
branches, while a surface-branch or contact-orientation error can leave bands
correct and corrupt transport. It is not clone-and-run because the neutral
synthetic schema and NumPy-only CLI do not match a source example. Formatting
does not create the difficulty: all artifacts are small and exactly specified.

### Shortcut attempts

| Shortcut/baseline | Command or test | Result | Why it passes/fails |
| --- | --- | --- | --- |
| Clone and run official project | Static interface comparison | Fails | Official examples do not implement the neutral input/output contract and are not participant dependencies. |
| Implement only `H0/H1` or one formula | Assembly-only candidate audit | Fails | Bands, two causal leads, a nonuniform device, and observables remain mandatory and independently scored. |
| Hard-code two public examples | `mutant_stale_public.py` plus ten hidden cases | Fails, score 0.3856 | Hidden rotations, orderings, bases, cutoff edge, contacts, defects, and transforms differ. |
| Omit periodic coupling | `mutant_omit_periodic.py` | Fails, score 0.1940 | `H1`, bands, self-energies, and transport are all checked. |
| Fabricate diagnostics | Evaluator recomputation | Fails as a shortcut | Bands, observables, Hermiticity, Dyson residuals, causality, and LDOS sums are recomputed from submitted arrays. |

No pinned frontier agent has attempted the exact final package. The justified
label is therefore only `structurally_hard_candidate`.

## 5. Privileged oracle run

- Command: `python author/oracle/generate_assets.py --task-root . --check`
  from the task root.
- Environment: Python 3.12.13, NumPy 2.3.5, Windows authoring host, one process,
  no network use.
- Source-only information used: the paper/repository grounded the workflow
  topology and conflict audit. Numerical instances and reference values are
  benchmark-authored synthetic data computed by `private/grader/science.py`.
- Runtime: clean deterministic checks measured 0.366-0.369 s of total oracle
  solving.
- Peak memory: peak RSS was not measured on this Windows run. The largest
  generated hidden basis is 12, the largest device has 7 cells, and the largest
  energy/phase grids contain 31/25 values.
- Output inventory: 2 public inputs, 10 hidden inputs, 48 four-file reference
  artifacts, and one deterministic manifest.
- Scientific invariants: maximum surface residual `1.968552123949753e-15`,
  maximum Hermiticity residual `0.0`; every generated `H1` is meaningful and
  at least 75 percent numerical rank (all checked cases were full rank).
- Artifact-only evaluator: score 1.0 on all 10 hidden references; 471,275
  serialized bytes and 687,809 expanded bytes; 0.304-0.332 s across measured runs.
- Logs: `author/verification_logs/oracle_check.json` and
  `author/verification_logs/oracle_artifacts_evaluation.json`.
- Status: PASS.

## 6. Clean-room public-input reference run

The verifier copies only `participant/`, the submitted solver source, and the
two public instance files into a fresh temporary tree. The private evaluator
then stages each execution in another fresh directory containing only
`solver.py`, one `model.json`, output and console paths, with a scrubbed
environment, fixed single-thread variables, and `PYTHONDONTWRITEBYTECODE=1`.

- Solver command inside each isolated case:
  `python solver.py --input model.json --output output`.
- Reproduction command: `python scripts/verify.py` from the task root.
- Network policy: solver source imports are statically restricted and no
  network facility is used. OS-level hostile-code network denial is a pending
  production ALE responsibility, not claimed for direct author calibration.
- Runtime: 0.638-0.865 s across measured clean two-case reference runs.
- Peak memory: not measured; public output and dimensions are recorded below.
- Output inventory: four required artifacts per case; 81,816 serialized bytes
  and 78,816 expanded bytes over both cases.
- Evaluator metrics: assembly, bands, self-energies, DOS/LDOS, transmission,
  and evidence consistency all met their mandatory minima on both cases.
- Total score: 1.0 over 2 public cases.
- Hidden access audit: the solver source contains no private/source markers,
  imports only standard-library modules and NumPy, and runs from copied source
  and input bytes. No private, author, paper, or repository artifact is staged
  in the solver process directory.
- Log: `author/verification_logs/public_reference_evaluation.json`.
- Status: PASS.

The same reference solver passed all ten hidden cases with score 1.0. Repeated
suite runs took 2.515-2.703 s and produced exact evaluator JSON, process status,
702,816 serialized bytes, and 687,816 expanded bytes.

## 7. Alternative valid implementation

- Algorithmic independence: the reference solver uses Lopez-Sancho
  decimation/refinement, while the alternative uses damped Dyson fixed-point
  continuation. The alternative also independently reimplements parsing,
  orbital assembly, device construction, and serialization.
- Public command path: exercised by `python scripts/verify.py` in the same
  public clean-room construction.
- Hidden direct command:
  `python private/grader/evaluate.py --submission author/alternative_solver/solve.py --json-out author/verification_logs/alternative_evaluation.json`.
- Public result: score 1.0 on 2 cases in 1.827-1.900 s, 56,536 serialized
  bytes, 78,834 expanded bytes.
- Hidden result: score 1.0 on 10 cases. Repeated runs took 14.890-15.484 s,
  produced identical evaluator JSON, 479,703 serialized bytes, and 687,904
  expanded bytes.
- Maximum absolute disagreement from the reference: `1.11e-16` for `H0`,
  `2.22e-16` for `H1`, `4.44e-15` for bands, `3.17107661829854e-10` for
  self-energies, `1.32263977548064e-10` for DOS, `7.09983183355689e-11`
  for LDOS, and `1.71757885691903e-11` for transmission.
- Logs: `public_alternative_evaluation.json`, `alternative_evaluation.json`,
  and `alternative_evaluation_repeat.json` under `author/verification_logs/`.
- Status: PASS.

## 8. Tolerance calibration

Repeated deterministic reference and alternative runs had zero parsed-result
variation. The table therefore reports independent-method disagreement as the
meaningful calibration observation. Array comparisons use absolute plus
relative scaling; exact archive bytes are not a scientific criterion.

| Metric | Repeated variation | Largest independent disagreement | Absolute tolerance | Relative tolerance | Justification |
| --- | ---: | ---: | ---: | ---: | --- |
| `H0/H1` assembly | 0 | `2.22e-16` | `2e-12` | `2e-11` | Algebraic output; margin covers complex128 operation order without accepting topology/sign errors. |
| Bloch bands | 0 | `4.44e-15` | `2e-9` | `2e-9` | Allows independent Hermitian eigensolver ordering near degeneracy. |
| Contact self-energies | 0 | `3.1711e-10` | `5e-8` | `2e-7` | Band-edge conditioning needs margin; separate Dyson and causality scores prevent wrong-branch acceptance. |
| Total DOS | 0 | `1.3226e-10` | `5e-8` | `3e-7` | Green-function traces amplify surface differences. |
| Cell LDOS | 0 | `7.0998e-11` | `5e-8` | `3e-7` | Same conditioning as DOS, with all cells and the LDOS sum identity checked. |
| Transmission | 0 | `1.7176e-11` | `5e-8` | `5e-7` | Absolute protection is needed for weak-contact and defect-suppressed values. |
| Recomputed bands | 0 | same submitted arrays | `3e-10` | `2e-10` | Tighter same-artifact consistency check. |
| Recomputed DOS/LDOS | 0 | same submitted arrays | `3e-9` | `3e-8` | Tighter than cross-implementation truth comparison. |
| Recomputed transmission | 0 | same submitted arrays | `3e-9` | `3e-8` | Detects inconsistent final spectra. |
| Diagnostic Hermiticity | 0 | oracle maximum `0` | `1e-12` | `1e-5` | Scale-aware evidence claim and independently recomputed residual. |

Surface evidence is scored logarithmically: the self-energy Dyson score is
excellent at `2e-9` and unacceptable at `2e-4`; causality is excellent at
`2e-10` and unacceptable at `2e-5`. The submitted diagnostic surface claim is
excellent at `1e-9` and unacceptable at `1e-5`. These ranges are wider than
the oracle residuals but reject noncausal and unconverged branches.

The suite is deterministic, not stochastic. It uses ten disjoint hidden seeds,
mean aggregation, all-case pass requirements, a total threshold of 0.90, and
mandatory per-metric minima. Exact weights and thresholds remain private in
`private/evaluation_spec.yaml` and `private/grader/evaluate.py`.

## 9. Mutant results

All mutants are ordinary unpacked standalone Python sources. Scientific
mutants passed structural gates and failed behavioral scoring; partial and NaN
mutants failed the intended artifact hard gates.

| Mutant | Category | Expected | Observed score | Evaluator pass | Notes |
| --- | --- | --- | ---: | --- | --- |
| `mutant_wrong_sp_sign.py` | Wrong directional `p`-to-`s` sign | fail | 0.202600 | no | Structural gates pass; assembly and downstream results expose the sign error. |
| `mutant_omit_periodic.py` | Omitted forward periodic interaction | fail | 0.194000 | no | Structural gates pass; `H1` and every periodic/open-boundary consumer are wrong. |
| `mutant_advanced_branch.py` | Advanced instead of retarded surface | fail | 0.541600 | no | Structural gates pass; causality, self-energy, and transport scoring reject it. |
| `mutant_eta_real_shift.py` | Broadening also applied as real shift | fail | 0.385600 | no | Structural gates pass; catches the source-inspired damping mistake. |
| `mutant_dos_factor.py` | Erroneous factor-two spin degeneracy | fail | 0.787733 | no | Structural gates pass; normalization and consistency metrics reject it. |
| `mutant_caroli_no_dagger.py` | Missing complex conjugation in Caroli trace | fail | 0.813867 | no | Highest-scoring mutant remains below mandatory pass requirements. |
| `mutant_stale_public.py` | Reused pristine/public device settings | fail | 0.385600 | no | Hidden potentials, bonds, contacts, and defects defeat stale-state overfit. |
| `mutant_partial.py` | Only Hamiltonian artifact emitted | hard-gate fail | 0.000000 | no | Every case reports the three missing required artifacts. |
| `mutant_nan.py` | NaN injected into transmission | hard-gate fail | 0.000000 | no | Every case rejects the non-finite value before scientific scoring. |

Mutation categories covered: sign, omitted interaction, causal branch,
broadening semantics, normalization, conjugation/metric, stale or public-case
overfit, partial output, and non-finite output. Per-mutant reports are
`author/verification_logs/mutant_*_evaluation.json`; the consolidated record is
`author/verification_logs/mutant_results.json`.

## 10. Metamorphic and invariant tests

| Test | Expected relation | Complete observed residual set | Status |
| --- | --- | --- | --- |
| Global energy-origin shift, `delta=1.191646088` | `H0` and bands shift by `delta`; `H1`, self-energies, DOS/LDOS, and transmission are invariant at shifted energies. | `h0=0`, `h1=0`, energy grid `8.882e-16`, phase grid `0`, bands `3.553e-15`, sigma left `1.732e-14`, sigma right `3.777e-14`, DOS `7.994e-15`, LDOS `4.441e-15`, transmission `1.110e-15` | PASS; max `3.777e-14` versus `2e-9` gate |
| Site-list permutation `[2,0,1]` | Matrices and self-energies transform by the induced site-major permutation; trace observables stay invariant. | `H0=0`, `H1=0`, sigma left `3.459e-13`, sigma right `1.145e-13`, bands `7.105e-15`, DOS `2.665e-15`, LDOS `2.665e-15`, transmission `1.221e-15` | PASS; max `3.459e-13` versus `2e-9` gate |
| LDOS partition identity | `sum_cells(ldos_cells)=dos_total` at every energy | Passed evidence-consistency scoring for both valid solvers on all ten hidden cases | PASS |
| Surface Dyson and causality | Both leads satisfy the fixed-point relation and have positive-semidefinite broadenings up to roundoff | Oracle maximum surface residual `1.969e-15`; valid solvers scored 1.0 | PASS |
| Hamiltonian/device Hermiticity | Normalized `H0` and device residuals remain small | Oracle maximum `0.0`; independently recomputed for submissions | PASS |

## 11. Evaluator robustness

- Repeated deterministic runs: exact evaluator JSON and process status matched
  for reference and alternative solvers; sizes also matched exactly.
- Malformed output: trusted-core probes rejected corrupt/duplicate NPZ members,
  wrong dtypes/shapes, renamed NPY entries, non-object JSON, and huge integers.
- Partial output: rejected on all ten cases with score 0.
- NaN/Inf: NaN transmission rejected on all ten cases with score 0.
- Oversized output: a 65,537-byte diagnostics artifact was rejected against
  the 65,536-byte limit.
- Stale cached output: the stale-device mutant scored 0.3856 and failed.
- Fabricated self-reported metrics: diagnostic claims are compared to
  independently recomputed Hermiticity and surface residuals and cannot
  replace the scientific arrays.
- Hard-coded public examples: public/stale behavior fails the ten-case hidden suite.
- Private-file access: source containing `private/reference` was rejected by
  the source-marker policy.
- Network access: source importing `socket` was rejected by the import policy.
- Path traversal: outputs must resolve directly beneath the evaluator-created
  directory; archive member separators, links, junctions, and unexpected files
  are rejected.
- Symlink probe: this Windows host could not create a symlink without privilege
  (`WinError 1314`). Static inspection confirmed `_is_link_like` enforcement;
  a live outer-sandbox symlink probe remains an ALE integration action.
- Executable isolation: direct `--submission` mode is explicitly trusted-author
  calibration, with temporary staging, source policy, scrubbed environment,
  timeouts, and output limits. Production must run untrusted code in an outer
  OS sandbox and grade only returned artifacts with `--artifacts-only`.

Security logs are `security_network_probe.json`,
`security_private_path_probe.json`, and `security_oversized_probe.json` under
`author/verification_logs/`.

## 12. Hidden-instance validity

- Generator: `author/oracle/generate_assets.py`, deterministic and checked by
  regeneration against the manifest.
- Inventory: ten hidden cases plus two permanently public review cases.
- Varying factors: arbitrary three-dimensional rotations, site order, species
  labels, heterogeneous `s`/`sp3` widths, cutoff epsilon boundary, contact
  asymmetry, cell/site potentials, bond contrast, a strong defect, weak
  contacts, and two metamorphic transformations.
- Bounds in this calibration suite: basis at most 12, device cells at most 7,
  phases at most 25, energies at most 31, and `eta` from 0.04 to 0.12.
- Scientific invariants preserved: directional two-center coupling, disclosed
  Bloch/device equations, retarded Dyson causality, global energy covariance,
  and site-permutation equivariance.
- Reference behavior: every `H1` is meaningful/full-rank in the generated
  suite; both independent valid solvers pass every case with score 1.0.
- Public review instances retired from hidden scoring: yes.
- Private seed policy: all twelve case/transform literal seeds are distinct;
  public, hidden, and transform seeds do not overlap or appear in participant files.

## 13. Participant package audit

- Paper/source identifiers removed: yes. Participant text contains no paper
  title, acronym, authors, arXiv ID, official repository, source API, example
  filename, hidden ID, or private-reference marker.
- Task semantics remain complete: yes; the paper-blind review could restate all
  required stages and found no hidden scientific dependency.
- Inputs sufficient: yes; schema and two fixtures include every numerical
  quantity required by the workflow.
- Output contract clear: yes; filenames, keys, dtypes, shapes, axes, grids,
  hash, JSON fields, and residual formulas are explicit.
- Public success criteria clear: yes; assembly, causal transport, robustness,
  identities, finiteness, determinism, and resource behavior are stated without
  exposing private cases or thresholds.
- Environment reproducible: Python 3.11+, NumPy 1.26 through 2.x, one process,
  at most four cores, 8 GB memory, no GPU/network, 120 seconds per instance,
  30 minutes per suite, 200 KiB source, 1 MiB console, and 50 MiB artifacts.
- No private artifacts included: participant inventory is exactly `TASK.md`,
  three input files, and two starter files after generated cache cleanup.
- Public fixture table: corrected to the shipped
  `public_scalar_diatomic.json` and `public_rotated_multispecies.json` names.

The final package verifier rejects participant additions, source/private
markers, binary or unexpected file types, duplicate private/author file hashes,
links, bytecode caches, unbounded schema dimensions, invalid JSON, and unfilled
template fields.

## 14. Commands to reproduce verification

From `tasks/nanonet/tasks/periodic-orbital-transport`:

```text
python author/oracle/generate_assets.py --task-root . --check
python author/oracle/generate_mutants.py --check
python author/oracle/run_mutant_calibration.py --check
python private/grader/evaluate.py --submission author/reference_solver/solve.py --json-out author/verification_logs/reference_evaluation.json
python private/grader/evaluate.py --submission author/alternative_solver/solve.py --json-out author/verification_logs/alternative_evaluation.json
python scripts/verify.py
```

The required one-command release gate is:

```text
python tasks/nanonet/tasks/periodic-orbital-transport/scripts/verify.py
```

After the report, cache cleanup, refreshed paper-blind review, checklist update,
and build-ID pinning, exact-package runs passed all 11 gates. The authoritative
current runtime and per-gate evidence are retained in
`author/verification_logs/verification_summary.json`.

## 15. Remaining risks and next actions

- Scientific review: an independent domain expert has not yet reviewed the
  synthetic grounded extension, tolerance margins, or finite-broadening regime.
- Scientific scope: the task tests synthetic `s`/`sp3` systems and finite
  positive `eta`, not the paper's full `sp3d5s*` silicon parameterization or
  the singular zero-broadening limit.
- Engineering review: peak RSS was not instrumented. Actual dimensions,
  runtimes, and output sizes are far below public caps, but production should
  collect memory telemetry.
- ALE integration: outer OS isolation, hard network denial, private mount
  exclusion, and a live symlink/path test are pending. Direct author evaluator
  execution is not a hostile-code sandbox.
- Frontier-agent calibration: no pinned agent system has attempted an immutable
  exact build. Continuous trial scores, system definitions, and uncertainty
  must be recorded before any frontier-hardness claim.
- Build identity: the frozen six-file participant tree is pinned as
  `sha256:ccc4469029e0ac6da765061bd0f315d659ac9e8f3b48581db32dd0d77a3a5005`
  using sorted relative-path, NUL, file-SHA-256, and LF records.
- Public ergonomics: a small expected-output oracle and explicit public `C==1`
  case could improve participant-side testing, but are not needed for
  specification closure or current evaluation validity.
- Licensing: author-only paper and repository snapshots must remain outside any
  participant release.

These are publication and calibration actions, not blockers for collaborator
review. The present decision remains `needs_agent_calibration`, with provisional
label `structurally_hard_candidate` and collaborator disposition
`accepted_for_collaborator_review`.
