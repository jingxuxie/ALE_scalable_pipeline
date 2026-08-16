# Paper-to-task Codex session report

## Session result

- Paper: *NanoNET: an extendable Python framework for semi-empirical tight-binding models*, arXiv:2010.07463v1
- Configured output root: `E:/Desktop2026.2.1/ALE/scalable_pipeline/tasks`
- Per-paper output root: `E:/Desktop2026.2.1/ALE/scalable_pipeline/tasks/nanonet`
- Final lifecycle status: `needs_agent_calibration`
- Provisional difficulty: `structurally_hard_candidate`
- Frozen participant build ID: SHA-256 `ccc4469029e0ac6da765061bd0f315d659ac9e8f3b48581db32dd0d77a3a5005`
- Paper-blind specification review: **PASS**, with no blocking or nonblocking findings, for the frozen participant build above
- Collaborator disposition: one verified task selected for collaborator review; no frontier-difficulty claim
- Selected task IDs: `periodic-orbital-transport`
- Rejected candidate IDs: `candidate-exact-figure-9-reproduction`, `candidate-periodic-block-assembly-only`, `candidate-block-decomposition-optimization`, `candidate-complex-band-and-modal-surfaces`, `candidate-exact-bismuth-bands`
- Session date: 2026-08-15
- Codex/model revision if available: not recorded by the local extraction interface

The preferred count was two. Only one candidate met the hard-only,
paper-blind, closed-specification, and bounded-verification requirements. A
second task was not forced.

## Sources inspected

- Paper and supplement: all 14 pages of the pinned arXiv v1 PDF were rendered and visually inspected; text extraction was used for locator checks. The paper refers to supplementary silicon coordinates, but no supplement was supplied or found in the PDF.
- Official code: `https://github.com/freude/NanoNet`, current commit `0c71da6c53129fcc0794efa7f35610ed9f44e135`; nearest located pre-paper commit `50d02856b5bcfcf9a91de6d46ebd54bf24938797` was archived separately.
- Data: no external dataset is needed. Participant instances are newly generated, neutral synthetic geometry/parameter records.
- Environment: Python 3.12.13 and NumPy 2.3.5 for authoring; participant contract supports Python 3.11+ and NumPy 1.26 through 2.x.
- Licenses: official code is MIT. No paper-PDF redistribution license was asserted. The PDF, repository checkout, and archive remain author-only; participant assets are newly authored and redistributable.
- Source reproduction status: static source inspection only. Provider code and paper-supplied commands were not executed. Exact Figure 9 reproduction was intentionally not attempted because it would require missing supplementary and repository-only material.

## Source workflow execution

| Run | Command | Purpose | Exit | Runtime | Key outputs |
| --- | --- | --- | ---: | ---: | --- |
| Paper retrieval | `Invoke-WebRequest -Uri https://arxiv.org/pdf/2010.07463 -OutFile tasks/nanonet/authoring/sources/2010.07463.pdf` | Pin primary paper evidence | 0 | not retained | PDF, SHA-256 `d239...7f91` |
| Code retrieval | `git clone https://github.com/freude/NanoNet tasks/nanonet/authoring/sources/NanoNet_official` | Pin official source for static corroboration | 0 | not retained | Current commit `0c71da6...` |
| Paper-era archive | `git -C ... archive --format=tar --output ../NanoNet-paper-era-50d02856.tar 50d02856...` | Preserve nearest pre-paper official snapshot | 0 | not retained | TAR, SHA-256 `ad5144...b6f4` |
| Visual inspection | `pdftoppm -png -r 144 tasks/nanonet/authoring/sources/2010.07463.pdf $env:TEMP/nanonet_pdf_inspect/page` | Inspect every page and figures | 0 | not retained | 14 temporary renders, removed after inspection |
| Oracle generation | `python tasks/nanonet/tasks/periodic-orbital-transport/author/oracle/generate_assets.py --task-root tasks/nanonet/tasks/periodic-orbital-transport` | Generate public/hidden instances and references | 0 | about 0.369 s | 2 public cases, 10 hidden cases, 48 reference artifacts |
| Oracle determinism | `python tasks/nanonet/tasks/periodic-orbital-transport/author/oracle/generate_assets.py --task-root tasks/nanonet/tasks/periodic-orbital-transport --check` | Regenerate and compare deterministic assets | 0 | under 1 s | Byte/content inventory check passed |
| Oracle artifact evaluation | artifact-only evaluator mode, invoked by `scripts/verify.py` | Score privileged hidden references through the same parser and metrics | 0 | 0.332 s | Score 1.0; 471275 disk bytes and 687809 expanded bytes |
| Reference evaluation | `python private/grader/evaluate.py --submission author/reference_solver/solve.py --json-out author/verification_logs/reference_evaluation.json` | Hidden-suite clean-room reference | 0 | 2.614 s | Score 1.0 over 10 cases |
| Reference repeat | same command with `reference_evaluation_repeat.json` | Test parsed-score and report determinism | 0 | 2.639 s | Exact evaluator JSON repeat |
| Alternative evaluation | `python private/grader/evaluate.py --submission author/alternative_solver/solve.py --json-out author/verification_logs/alternative_evaluation.json` | Independent valid implementation | 0 | 15.340 s | Score 1.0 over 10 cases |
| Alternative repeat | same command with `alternative_evaluation_repeat.json` | Test parsed-score and report determinism | 0 | 15.484 s | Exact evaluator JSON repeat |
| Mutant calibration | invoked by `scripts/verify.py` over `private/mutants/*.py` | Exercise scientific and artifact failure modes | 0 | bounded by suite limit | All 9 mutants rejected; scores ranged from 0.0 to 0.8138667 |

## Claim tree and workflow graph

- Central question: how can atomic geometry and two-center orbital parameters be transformed into reproducible periodic electronic structure and open-boundary transport?
- Candidate leaf findings: geometry-to-periodic Hamiltonian construction; the Figure 9 bands/DOS/transmission pipeline; block-structure performance; and bulk-bismuth transfer.
- Selected target leaf: `claim-leaf-periodic-bands-dos-transmission`, grounded in the paper's Figure 9 silicon-nanowire band structure, DOS, and coherent transmission result.
- Workflow graph path: public geometry/parameter JSON -> neighbor/image enumeration -> signed s/p orbital blocks -> H0/H1 -> Bloch bands and finite-device branches -> causal left/right surfaces -> contact self-energies -> device Green function -> DOS/LDOS/Caroli transmission -> residual diagnostics.
- Major provenance gaps or conflicts: supplementary Si coordinates and full paper-era parameter tables are absent; DOS normalization differs between Equation (10) and example code; damping is inconsistently typed; left/right surface naming is ambiguous; current source substantially postdates the paper; the complex-band linearization appears inconsistent; and the block optimizer is locally heuristic despite optimal naming.

## Candidate comparison

| Candidate | Target leaf | Operations/depth | Verification strength | Shortcut risk | Resource fit | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| Periodic orbital Hamiltonian and open-boundary transport | Figure 9 bands/DOS/transmission workflow | 8 / 7 | Strong: two solvers, 10 hidden cases, intermediate/final metrics, metamorphics | Low | Excellent; hidden dimensions at most 84 and suite runs in seconds | Select |
| Exact Figure 9 reproduction | Same leaf, exact published system | 6 / 6 | Weak without repository-only assets | High: clone-and-run or hard-code plot | Bounded but scientifically under-specified | Reject |
| Periodic block assembly only | Geometry-to-H0/H1 leaf | 3 / 3 | Strong exact matrix oracle | Low | Excellent | Reject as too short/easy |
| Block-decomposition optimization | Figure 3/11 structure-performance leaf | 4 / 4 | Potential validity plus relative-cost scoring | Medium: published fixed blocks and source heuristic | Acceptable after a new calibration campaign | Reject |
| Complex bands and modal surfaces | Equation 7/8 branch | 4 / 4 | Possible with residual/subspace scoring | Medium: close source mapping | NumPy-only generalized eigenproblem is not closed | Reject |
| Exact bismuth bands | Figure 10 material example | 4 / 4 | Mostly one final band artifact | High: paper transcribes parameters and source workflow | Excellent | Reject as source-trivia dominated |

## Selected task rationale

- Why the leaf is scientifically meaningful: bands, DOS, and transmission are the central electronic-structure and transport observables used to demonstrate the framework, not an incidental implementation statistic.
- Why the workflow boundary is long enough: eight meaningful operations span two dependent branches and require both geometric orbital assembly and causal open-system numerical linear algebra.
- Why the public package is specification-complete: it states the basis, cutoff, image enumeration, signed s/p matrix elements, H0/H1 and Bloch conventions, device construction, left/right Dyson equations, contact embedding, observable normalization, CLI, schemas, dtypes, shapes, limits, and qualitative evaluation criteria.
- Why source access is not required at participant runtime: every geometry, onsite value, hopping value, grid, potential, bond/contact scale, and convention comes from the supplied JSON and TASK.md. Paper and project names are absent from the participant package.
- Why the evaluator is outcome-based: it recomputes Hamiltonians, bands, causal self-energies, DOS/LDOS, transmission, and identities across held-out instances with continuous numerical scores and hard artifact gates.
- Why obvious shortcuts fail: private rotations, site permutations, heterogeneous orbital counts, cutoff edges, defects, asymmetric weak contacts, metamorphic pairs, and cross-artifact checks defeat public-case hard-coding and fabricated diagnostics.
- Why the task is only a structural hard candidate until calibration: no pinned frontier agent has attempted the exact final public build under the declared resource policy.

## Execution and verification summary

| Task | Oracle | Clean-room solver | Alternative | Mutants | Metamorphic | Leakage | Final status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `periodic-orbital-transport` | Pass; 12 deterministic cases, max surface residual `1.969e-15` | Pass; public and hidden score 1.0, hidden repeat exact | Pass; public and hidden score 1.0, hidden repeat exact | 9/9 rejected, score range 0.0-0.8138667 | Energy shift max `3.777e-14`; site permutation max `3.459e-13` | Participant/private/author split and security probes are release gates in `scripts/verify.py` | `needs_agent_calibration` / `structurally_hard_candidate` |

Reference-versus-alternative maximum absolute differences were
`2.22e-16` for H1, `4.44e-15` for bands, `3.1711e-10` for contact
self-energies, `1.3226e-10` for DOS, `7.0998e-11` for LDOS, and
`1.7176e-11` for transmission. These measurements support the task-level
absolute and relative tolerances; exact thresholds remain private.

## Commands

The paper and repository are evidence only; no provider code is executed.

```text
python tasks/nanonet/tasks/periodic-orbital-transport/author/oracle/generate_assets.py --task-root tasks/nanonet/tasks/periodic-orbital-transport --check
```

```text
python tasks/nanonet/tasks/periodic-orbital-transport/scripts/verify.py
```

The packaged `verify.py` is cross-platform and resolves the active Python
interpreter through `sys.executable`; on this authoring host it was invoked
with the bundled Python 3.12.13 runtime.

## Unresolved risks

- Scientific: this is a grounded extension using synthetic s/sp systems, not a numerical reproduction of the paper's full sp3d5s* silicon model. Finite positive broadenings test the retarded workflow but not the singular zero-broadening limit.
- Specification: the isolated participant-only rereview passed with no blocking or nonblocking findings for build `ccc4469029e0ac6da765061bd0f315d659ac9e8f3b48581db32dd0d77a3a5005`; any later participant edit invalidates that attestation and requires a new build ID and rereview.
- Evaluation: the local evaluator stages a logically clean temporary directory and statically rejects network/process/dynamic facilities, but hostile executable isolation must be supplied by the production ALE runner.
- Runtime: private cases are deliberately small and dense. The benchmark evaluates scientific workflow correctness rather than the paper's large-system scaling claim.
- Licensing: author-only paper/source snapshots must never enter the participant release; generated participant assets are independent and redistributable.
- ALE packaging: production integration must execute participant code in an OS-level sandbox, then run the private grader on artifacts only.
- Agent calibration: the exact build has not been attempted by pinned frontier agents, so no empirical frontier-hardness statement is warranted.

## Recommended next action

The single cross-platform verification command passes on the settled package.
Proceed with collaborator review, then run pinned frontier-agent calibration on
the immutable participant build and complete production ALE sandbox validation.
