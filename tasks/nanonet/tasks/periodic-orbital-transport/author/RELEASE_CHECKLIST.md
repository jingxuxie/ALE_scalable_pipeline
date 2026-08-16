# Hard paper-derived task release checklist

Current status: `needs_agent_calibration`  
Provisional difficulty label: `structurally_hard_candidate`  
Derivation: `grounded_extension` from the source workflow's periodic band, DOS,
and transmission result leaf. Unchecked items are intentionally pending and are
not waived.

## Source and legality

- [x] Exact paper bytes are pinned by SHA-256 in `../../authoring/source_manifest.yaml`; no supplement was available or used.
- [x] The current official repository commit and nearest pre-paper commit are pinned when used as evidence.
- [x] No external source dataset is redistributed; every synthetic input and reference file is pinned in `author/oracle/manifest.json`.
- [x] Redistribution and execution licenses are acceptable: source code inspected as evidence is MIT-licensed, while participant assets are benchmark-authored synthetic files.
- [x] Paper/code/configuration disagreements are recorded in `../../authoring/evidence_map.yaml` and `../../authoring/session_report.md`.
- [x] Provider commands were inspected before use; paper/repository content was treated as untrusted evidence and not imported by the oracle or evaluator.

## Workflow grounding

- [x] A claim/problem tree exists in `../../authoring/workflow_graph.yaml`.
- [x] The execution workflow DAG exists in `../../authoring/workflow_graph.yaml`.
- [x] The concrete target is `claim-leaf-periodic-bands-dos-transmission`.
- [x] The task uses an eight-operation backward slice from geometry through evidence diagnostics.
- [x] Each operation and artifact has provenance in `../../authoring/evidence_map.yaml` and `../../authoring/workflow_graph.yaml`.
- [x] The selected task is explicitly labeled `grounded_extension`.
- [x] Source ambiguities were resolved as public benchmark conventions; no low-confidence inference is a hidden participant requirement.

## Hardness

- [x] Eight meaningful participant operations are present.
- [x] Dependency depth is seven.
- [x] Independent challenge sources include directional multi-orbital assembly, causal nonlinear lead solving, and cross-stage integration.
- [x] Difficulty is intrinsic and does not primarily come from formatting, volume, hidden trivia, thresholds, or compute.
- [x] Clone-and-run does not satisfy the neutral synthetic interface or declared NumPy-only environment.
- [x] No one-formula or one-library-call shortcut spans the required workflow.
- [x] Ten hidden instances prevent hard-coding the two public examples.
- [x] Hamiltonians, self-energies, spectra, and diagnostics are all used as private rubric evidence.
- [x] The task remains labeled `structurally_hard_candidate` pending empirical agent calibration.

## Public specification

- [x] `participant/TASK.md` states the professional goal and complete workflow.
- [x] Both public instances, the schema, and both starter files are documented.
- [x] Required source and runtime output paths, keys, dtypes, shapes, and JSON fields are explicit.
- [x] Basis, cutoff, hopping signs, Bloch phase, retarded branch, lead orientation, DOS/LDOS, and transmission conventions are public.
- [x] Python/NumPy versions, CPU, GPU, memory, wall-time, storage, and disabled-network policy are public.
- [x] Qualitative scientific and robustness criteria are public.
- [x] Exact hidden cases, seeds, references, thresholds, weights, and mutations remain private.
- [x] The specification-closure table in `author/task_spec.yaml` has no invalid hidden dependencies.
- [x] Frozen paper-blind rereview passes with a correct restatement and no blocking or nonblocking ambiguity; see `author/paper_blind_review.md`.
- [x] Participant filenames and prose omit the paper, author, repository, citation, and source-example identifiers.

## References and solvability

- [x] `author/oracle/generate_assets.py` generated all 12 pinned cases and passed deterministic `--check` regeneration.
- [x] `author/reference_solver/solve.py` is self-contained and reads only its supplied public-format input at runtime.
- [x] The reference solver uses only Python 3.11+ standard-library modules and NumPy.
- [x] The reference solver fits the declared four-core, 8 GB, 30-minute, 1 GB participant budget on the generated suite.
- [x] The reference solver passed all ten hidden cases with score 1.0; see `author/verification_logs/reference_evaluation.json`.
- [x] The independent damped-Dyson alternative solver passed all ten cases with score 1.0; see `author/verification_logs/alternative_evaluation.json`.
- [x] Neither valid solution reads hidden references, source files, or undisclosed constants at runtime.

## Evaluation

- [x] Hard gates cover structure, parseability, finiteness, identity, execution, size, path, and source policy only.
- [x] Six scientific dimensions receive continuous scores.
- [x] The evaluator recomputes bands, observables, Dyson residuals, causality, Hermiticity, and LDOS consistency from artifacts.
- [x] Programs are evaluated by executing a narrow CLI and scoring outputs behaviorally.
- [x] Exact code, archive bytes, or plot pixels are not required.
- [x] Absolute-plus-relative tolerances are recorded and justified from conditioning and two independent valid implementations.
- [x] The workflow is deterministic; multiple hidden instances and all-case aggregation replace stochastic confidence rules.
- [x] Exact thresholds and weights appear only in `private/evaluation_spec.yaml` and private grader code.
- [x] Metric weights sum to 1.0 and total/per-case/mandatory rules match `private/grader/evaluate.py`.
- [x] Exact repeated evaluator JSON and process status matched for both valid solvers: reference 1.0 in 2.614/2.639 s and alternative 1.0 in 15.340/15.484 s.

## Adversarial validation

- [x] Nine realistic mutant categories are implemented under `private/mutants/`.
- [x] All nine required mutants fail; continuous scores range from 0.0 to 0.813867 and are recorded in `author/verification_logs/mutant_results.json`.
- [x] Partial output fails the required-artifact hard gate with score 0.0; malformed-container probes in the trusted-core tests also fail safely.
- [x] Non-finite output fails with score 0.0, and an explicit 65537-byte diagnostics artifact fails the 65536-byte size cap.
- [x] `mutant_stale_public.py` is rejected with score 0.3856.
- [x] Fabricated diagnostic values cannot replace recomputed scientific metrics; inconsistent claims reduce evidence consistency.
- [x] The public/stale hard-coding mutant fails the hidden suite with score 0.3856.
- [x] Oracle energy-shift and site-permutation metamorphic checks pass at maximum residuals `3.78e-14` and `3.46e-13`, respectively.
- [ ] Production ALE must demonstrate that participant code cannot read private/author files; trusted-author direct execution is not a hostile-code sandbox.
- [ ] Production ALE must demonstrate OS-level network denial; the direct evaluator enforces source/path policy but is not the outer sandbox.

## Hidden instances

- [x] Private generation uses ten distinct author-only seeds absent from participant files.
- [x] The two public review cases are permanently excluded from hidden scoring.
- [x] Variants preserve the same periodic orbital and coherent transport equations; oracle invariant checks pass.
- [x] Both valid solutions pass all ten hidden cases.
- [x] Cases cover ordinary rotations/orderings/bases, cutoff edge behavior, weak contacts, a strong defect, and metamorphic pairs.
- [x] Public, hidden, and transform seeds are pairwise distinct by generator policy.

## Execution and packaging

- [x] Final `python tasks/nanonet/tasks/periodic-orbital-transport/scripts/verify.py` exits 0 with all 11 gates passing; the authoritative runtime is recorded in `author/verification_logs/verification_summary.json`.
- [x] Participant, private, author, and per-paper authoring projections are separated by directory.
- [x] Participant projection inventory contains no private reference, hidden input, oracle, evaluator, source paper, or source repository file.
- [x] Runtime dependencies are bounded to Python 3.11+ and NumPy 1.26 through 2.x; generated assets are content-pinned.
- [x] Final verification records command wall time and compressed/expanded output footprints for the exact package; peak RSS was not available and is explicitly recorded as unmeasured.
- [ ] A real ALE-compatible outer OS sandbox run is explicitly pending before publication.
- [x] `author/verification_report.md` is complete and passed the final static/package audit after all reference, mutant, metamorphic, and security runs.
- [x] The release decision is `needs_agent_calibration`; pending calibration and production-sandbox integration are explicit in `author/task_spec.yaml`.

## Calibration and release

- [x] The frozen six-file participant tree (39093 bytes) is pinned as `sha256:ccc4469029e0ac6da765061bd0f315d659ac9e8f3b48581db32dd0d77a3a5005` using sorted relative path, NUL, file SHA-256, and LF records.
- [ ] Run pinned frontier-agent trials before any frontier-difficulty claim.
- [ ] Record continuous trial scores and pass/fail for every pinned agent trial.
- [ ] Report uncertainty and exact agent-system definitions with calibration results.
- [ ] Complete independent scientific expert review.
- [x] Release status uses the allowed value `needs_agent_calibration`.
