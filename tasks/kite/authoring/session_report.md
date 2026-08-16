# Paper-to-task Codex session report

## Session result

- Paper: *KITE: high-performance accurate modelling of electronic structure and response functions of large molecules, disordered crystals and heterostructures*, arXiv:1910.05194v2.
- Output root: `tasks/kite`.
- Final status: `needs_agent_calibration`. Both selected packages pass local verification and are accepted as `structurally_hard_candidate` packages for collaborator review; neither is approved for benchmark release or described as frontier-hard.
- Selected task IDs: `reusable-chebyshev-spectral-cache-v1`; `spinful-packet-dynamics`.
- Exact verified builds: spectral `sha256:439d24074b7efc721570f33b64e0433427dfa6488945274a4aedbd78ee4b3f54`; spin `sha256:1723af0f244159dee47f96d153123e6e6e8b80bb02509ad75c765360f6163ca1`.
- Rejected candidate IDs: `candidate-03-kubo-hall`, `candidate-04-matrix-free-kernel`, `candidate-05-momentum-spectrum`.
- Session date: 2026-08-15.
- Codex/model revision if available: not recorded by the local verification artifacts.

## Sources inspected

- Paper and supplement: arXiv v2/published PDF, 38 pages, revised 2020-03-13, saved author-only as `authoring/sources/1910.05194.pdf`; SHA-256 `df4bea7b0fb8d4059bc16e0a20357912450cfaf63799cc2ac8ada97453dd3e82`. No separate supplement was identified.
- Official code: immutable KITE v1.0 Zenodo archive DOI `10.5281/zenodo.3485089`, commit `7bb1fc44d2b5a67ef65524fe33702e9c2cdef416`, git tree `510dd52f3fd77b59e0b31d0c7336a1188509287f`; archive SHA-256 `09c45bd2b4ac7f4bcb6a0bb7b4a51ed00e1c4ac017424ece38196ba0ee34fefd`, MD5 `39ec4e2aa4cb04e44daca53c379dec9d`, deterministic extracted-tree SHA-256 `0e7c71ab1b9c13d4d6d9ae5a82f39e5f40f83467c6b8dfb791e3ff7567c724ad`. Current upstream commit `560a4c9d86a9b34f153abcb402334a7fc2780585` was observed only for comparison.
- Data: examples and configurations in the pinned archive were inspected only as corroborating author evidence. Participant inputs are deterministic, independently authored synthetic systems, not copies of upstream examples or reported outputs.
- Environment: Windows 11, bundled Python 3.12.13 and NumPy 2.3.5. Participant contract is Python 3.11+ with NumPy `==2.3.5`, CPU only, no network.
- Licenses: the paper carries the arXiv non-exclusive distribution license. The official archive is internally inconsistent: `LICENSE.md` says LGPL-3.0 while its README and Zenodo description say GPL-3.0. No paper, source, example, or configuration bytes enter either participant package, so that upstream conflict is not inherited by the public bytes; an explicit downstream license for the independently authored participant assets has not yet been selected.
- Source reproduction status: paper metadata/text extraction and a safe 306-member archive traversal audit completed; 265 files were extracted. Provider code was inspected but not executed because it is untrusted evidence and its heavyweight build is unnecessary for the independent finite-system oracles.

## Source workflow execution

| Run | Command | Purpose | Exit | Runtime | Key outputs |
| --- | --- | --- | ---: | ---: | --- |
| Paper metadata | `pdfinfo authoring/sources/1910.05194.pdf` | Confirm page count, format, and encryption state | 0 | not separately timed | 38-page, unencrypted A4 PDF |
| Paper extraction | `pdftotext -layout authoring/sources/1910.05194.pdf tmp/kite-paper.txt` | Locate equations, workflow claims, and figure evidence | 0 | not separately timed | Author-only text used to build the evidence map |
| Archive audit/extraction | safe member audit followed by `Expand-Archive` | Reject rooted/traversal paths before inspecting the pinned code | 0 | not separately timed | 306 safe members; 265 extracted files; pinned tree hash |
| Official build | provider code not executed | Avoid executing untrusted, unnecessary provider commands | not run by design | not applicable | Static code/equation corroboration only |

## Claim tree and workflow graph

- Central question: how can sparse tight-binding systems support accurate, reusable electronic-structure and dynamics calculations without dense diagonalization?
- Candidate leaf findings: the selected leaves are `leaf-spectral-cache` (one energy-independent Chebyshev moment cache answers new retarded, advanced, density, broadening, and prefix queries) and `leaf-spin-precession` (bond-directed spin-orbit coupling and an added Ising field produce different spin/spatial ensemble trajectories). Supporting but unselected leaves cover Hall response, decomposed matrix-free equivalence, and momentum spectra.
- Spectral workflow path: `op-spectral-assemble` -> `op-spectral-rescale` -> `op-spectral-recurrence` -> `op-spectral-aggregate` -> `op-spectral-reconstruct` -> `op-spectral-diagnose`, producing probe-resolved moments, public responses, and diagnostics. This is six meaningful operations at dependency depth five.
- Spin workflow path: `op-spin-assemble` and `op-spin-packet` -> `op-spin-rescale` -> `op-spin-recurrence` -> `op-spin-contract` -> `op-spin-observables` -> `op-spin-ensemble` -> `op-spin-analysis`, producing reusable basis states, realization trajectories, ensemble summaries, and a linked comparison. This is eight meaningful operations at dependency depth six, counted as the longest operation-to-operation transition chain.
- Major provenance gaps or conflicts: printed moment normalizations conflict internally and were resolved to an explicit raw-moment convention checked against dense eigensystems; paper Eq. 4.13 prints `(-1)^n` while the source and independent unitary check require `(-i)^n`; paper Eq. 4.15 has a malformed Gaussian exponent, so the task discloses a normalized `exp(-|r-r0|^2/(4 sigma^2))` convention; the historical v1.0 tag naming differs from current upstream tags; and upstream licensing declarations conflict. Every benchmark choice is participant-visible and independently checked.
- Workflow `estimated_runtime_minutes` fields denote expert implementation/debugging attention per stage, not machine execution; measured solver wall times are recorded separately below.

## Candidate comparison

| Candidate | Target leaf | Operations/depth | Verification strength | Shortcut risk | Resource fit | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| `candidate-01-spectral-cache` | `leaf-spectral-cache` | 6 / 5 | recurrence and eigensolver implementations, 18 hidden contractions, 15 scientific mutants, metamorphic checks | low: hidden prefix/energy/broadening queries recompute from submitted raw moments | bounded, about 1 GiB target | select |
| `candidate-02-spin-dynamics` | `leaf-spin-precession` | 8 / 6 | spectral oracle plus dense and edge-accumulated solvers, six hidden times, paired ensembles | low: private-time contraction and basis grading defeat public-row hard-coding | bounded, about 2 GiB target | select |
| `candidate-03-kubo-hall` | `leaf-hall-response` | 5 / 4 | dense finite-system response possible | high common-mode risk because the full DC kernel is not printed | bounded, but authoring convention would dominate | reject: specification gap |
| `candidate-04-matrix-free-kernel` | `leaf-matrix-free-equivalence` | 6 / 5 | explicit sparse equivalence is strong | low | bounded | reject: reserve is more kernel-centric and less directly scientific |
| `candidate-05-momentum-spectrum` | `leaf-momentum-spectrum` | 6 / 4 | dense spectral-map oracle possible | medium finite-size/feature-extraction risk | bounded, about 3 GiB target | reject: less stable tolerances than the selected cache and a shorter application slice than dynamics |

## Selected task rationale

### `reusable-chebyshev-spectral-cache-v1`

- Why the leaf is scientifically meaningful: it tests the reusable numerical object underlying many-energy and many-resolution sparse spectral calculations, rather than a single plotted value.
- Why the workflow boundary is long enough: participants must assemble three heterogeneous complex Hermitian systems, validate affine bounds, run 384-order recurrences for four explicit probes, preserve raw probe-resolved moments, contract multiple response branches/prefixes, and generate consistency diagnostics.
- Why the public package is specification-complete: the 14-file participant tree supplies `TASK.md`, a manifest, 21 public queries, all onsite/edge/probe tables for dimensions 311, 529, and 769, and a structural validator. Scaling, normalization, root branch, units, schemas, limits, and qualitative success criteria are explicit.
- Why source access is not required at participant runtime: all systems and probes are synthetic and complete; the official repository has neither these instances nor their answers.
- Why the evaluator is outcome-based: it parses exactly `moments.npz`, `public_response.csv`, and `diagnostics.json`, contracts submitted moments at 18 held-out queries, and never executes participant code.
- Why obvious shortcuts fail: averaged/kernelized caches, zero-padded prefixes, order shifts, hard-coded public grids, branch/Jacobian mistakes, and fabricated diagnostics are all rejected; dense diagonalization remains a valid but still end-to-end alternative.
- Why the task is only a structural hard candidate until calibration: its six-operation/depth-five workflow, multiple coupled artifacts, and mutant resistance establish structural difficulty, but no pinned frontier-agent trials have measured solve rates or failure modes on the exact verified build.

### `spinful-packet-dynamics`

- Why the leaf is scientifically meaningful: it requires a controlled scalar-versus-Ising comparison of computed spin precession and spreading, while avoiding an unsupported claim about physical relaxation lifetimes or monotonic dephasing.
- Why the workflow boundary is long enough: participants assemble six 144-dimensional spinful Hamiltonians on a 72-site/127-bond open graph, validate spectra, build normalized wave packets, generate 52 reusable Chebyshev vectors, contract seven public times, compute nine observables, aggregate paired ensembles, and derive exact evidence-linked categories.
- Why the public package is specification-complete: its eight visible files provide the task, six complete inputs, and a Bessel helper; basis order, directed bond/spin blocks, packet convention, `(-i)^n` phase, units, output schemas, and allowed conclusions are explicit.
- Why source access is not required at participant runtime: the square-lattice, dense-Ising instance is a disclosed synthetic reduced-model extension absent from the official source and paper.
- Why the evaluator is outcome-based: it parses exactly `basis.npz`, `trajectories.csv`, `ensemble.csv`, and `analysis.json`, contracts the submitted basis at six unpublished in-range times, recomputes all evidence/categories, and executes no participant submission code.
- Why obvious shortcuts fail: public-time hard-coding, a first-order recurrence, omitted Ising field, SOC/Peierls sign mistakes, missing normalization/phase, and fabricated conclusions are rejected; an edge-accumulated recurrence is accepted independently of the dense reference.
- Why regeneration is portable: the generator canonicalizes LAPACK-derived spectral centers and half-widths to nine decimal places before publication and instance hashing. The verifier regenerates public and hidden inputs plus oracle artifacts in a fresh temporary tree, requires exact semantic input equivalence, and compares numerical reference artifacts under the disclosed cross-platform tolerances instead of depending on NPZ byte identity.
- Why the task is only a structural hard candidate until calibration: eight meaningful operations, depth six, four linked outputs, private-time reuse, and strong mutant coverage establish structural difficulty, but no pinned frontier-agent trial has tested the exact build.

## Participant/private boundary

| Task | Participant sees | Participant must produce | Author/private only |
| --- | --- | --- | --- |
| Spectral cache | neutral task text; manifest; 21 public queries; nine system/probe CSVs; validator and README | probe-resolved `(3,4,384)` real/imaginary moment arrays, 21 public response rows, diagnostics JSON | 18 hidden tuples, reference arrays/responses, exact tolerances/weights/pass gates, seeds, oracle, grader, mutants, and verification controls |
| Spin dynamics | neutral task text; sites, bonds, onsite fields, realizations, config, seven public times, Bessel helper | `(6,52,72,2)` complex basis, 42 realization rows, 14 ensemble rows, analysis JSON | six hidden times/trajectories, spectral reference basis, exact tolerances/weights/pass gates, seeds, oracle, grader, mutants, and verification controls |

Neither participant tree contains the paper title/acronym, citations, repository paths, official bytes, reported answers, hidden cases, references, score weights, or private thresholds.

## Execution and verification summary

Runtimes below are representative successful samples for the exact builds; the per-task `author/verification_results.json` files record the most recent host-specific rerun.

| Task | Oracle | Clean-room solver | Alternative | Mutants | Metamorphic | Leakage | Final status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Spectral cache | `1.0` | `1.0` twice; 0.241/0.245 s solver | `1.0`; eigensolver route, 0.577 s | 15/15 scientific rejected; 14/14 parser hard gates rejected | 8 invariant groups pass; largest reported covariance/permutation error `7.77e-16`; finite resolvent error stays below analytic tail bound | 14 participant files, zero identifiers; audit-hook source/socket/subprocess denial probes pass | `needs_agent_calibration`; local verifier pass in 15.313 s |
| Spin dynamics | `0.9999997412138324`; 0.145/0.140 s grades | `0.9999992243019628`; 0.171 s solver; deterministic repeat; 707,662 output bytes | `0.9999992285440962`; edge-accumulated route, 0.588 s | 8/8 scientific rejected, scores `0.019500208732849654`-`0.575999625981493`; 13/13 structural/adversarial rejected, scores `0`-`0.9934997412138324` | 6/6 groups pass; largest reported error `1.4210854715202004e-14`; Hermiticity error zero | 8 participant files, identifier scan pass; private-file/socket/subprocess denial probes pass | `needs_agent_calibration`; local verifier pass |

The current spin clean-room output inventory is `basis.npz` 689,721 bytes, `trajectories.csv` 8,706 bytes, `ensemble.csv` 5,318 bytes, and `analysis.json` 3,917 bytes. Temporary instance generation (`0.14808440000069822` s) and oracle regeneration (`0.1901726999994935` s) both matched the checked artifacts semantically. The clean solver took `0.17148079999969923` s and its repeated grades took `0.14174960000036663` s and `0.13836199999968812` s; the alternative solver took `0.5879759999997987` s.

### Tolerance justification

- Spectral raw moments use absolute `2e-11` and relative `4e-10` tolerances; finite contractions use absolute `4e-10` and relative `4e-9`. Independent sparse recurrence and eigensolver disagreements were at most `3.13e-16` and `6.86e-15`, while response disagreement was `1.56e-15`, leaving a large platform/BLAS margin without accepting float32, normalization, or branch errors. Grading targets the disclosed finite-prefix contraction, not the exact infinite resolvent; the current direct-resolvent discrepancy is `3.42e-4`, below its analytic omitted-tail bound of `3.63e-2`.
- Spin basis, observable, ensemble, and contrast tolerances range from absolute `2e-10` to `5e-8` and relative `2e-8` to `3e-7`. Three implementations disagree by less than `2e-12` raw, so these limits cover platform, Bessel quadrature, and near-zero normalization effects while sign, recurrence, normalization, and omitted-interaction mutants remain far outside. Exact categorical conclusions are mandatory.
- Spin input regeneration is deterministic across supported eigensolver implementations because the only LAPACK-derived published bounds are rendered to nine decimal places, far finer than the evaluator tolerances and the `0.15`-`0.27` spectral padding. Regenerated CSV/JSON structures are compared semantically, and regenerated NPZ/trajectory values use the same calibrated numeric envelopes as independent valid solutions.
- Both tasks are deterministic on fixed public probes/realizations. Hidden exact cases, weights, and pass thresholds remain private; continuous numeric scoring uses `max(abs_tolerance, rel_tolerance * abs(reference))` per element.

## Commands

Source inspection/reproduction commands:

```text
pdfinfo tasks/kite/authoring/sources/1910.05194.pdf
pdftotext -layout tasks/kite/authoring/sources/1910.05194.pdf tmp/kite-paper.txt
# Audit every ZIP member for rooted/parent traversal paths before Expand-Archive.
```

Complete local verification commands, run from the repository root:

```text
python tasks/kite/tasks/reusable_spectral_cache/scripts/verify.py
python tasks/kite/tasks/spinful_packet_dynamics/scripts/verify.py
```

Clean public-input reference and private grading commands (author context only):

```text
python -B tasks/kite/tasks/reusable_spectral_cache/author/reference_solver/solve.py --participant tasks/kite/tasks/reusable_spectral_cache/participant --output tmp/kite-spectral-clean
python -B tasks/kite/tasks/reusable_spectral_cache/private/grader/grade.py --participant tasks/kite/tasks/reusable_spectral_cache/participant --submission tmp/kite-spectral-clean
python tasks/kite/tasks/spinful_packet_dynamics/author/reference_solver/solve.py tasks/kite/tasks/spinful_packet_dynamics/participant tmp/kite-spin-clean
python tasks/kite/tasks/spinful_packet_dynamics/private/grader/grade.py tmp/kite-spin-clean --pretty
```

## Unresolved risks

- Scientific: a collaborator should review the spectral normalization/finite-resolvent convention and decide whether the reduced square-lattice dense-Ising analogue is an appropriate spin-dynamics abstraction. The latter must not be interpreted as a graphene/TMD lifetime prediction.
- Specification: paper-blind reviews pass with no blocking gap. The main residual risk is that independent readers could still misinterpret a grounded synthetic extension as a physical reproduction; author materials label the boundary explicitly.
- Evaluation: private queries test reuse of submitted caches/bases, not execution of participant code on new Hamiltonians. Python audit hooks catch accidental clean-solver dependencies but are not an adversarial OS sandbox. Dynamic root-symlink creation was unavailable on this Windows host; spectral leaf-symlink creation was also unavailable, although static regular-file/reparse checks and the remaining adversarial cases pass.
- Runtime: CPU time and output size are bounded and recorded, but peak resident memory was not measured on this host.
- Licensing: upstream LGPL-3.0/GPL-3.0 declarations conflict. Public bytes are independently authored and contain no upstream material, but a downstream participant-asset license still must be selected before release.
- ALE packaging: compiler/publication projection and target-infrastructure integration have not been run; hidden review seeds must be replaced with server-secret instances if these checked-in private files are exposed.
- Agent calibration: no pinned frontier-agent runs exist for either exact build, so solve-rate calibration, difficulty strata, and any frontier-hard claim remain unavailable.

## Recommended next action

Accept both packages for collaborator review only. Obtain manual scientific review, choose a participant-asset license, run ALE compiler/publication integration, regenerate any exposed private instances, and then calibrate pinned agent systems on the exact immutable build IDs. Retain `needs_agent_calibration` and `structurally_hard_candidate` until those steps pass; do not release or claim frontier difficulty yet.
