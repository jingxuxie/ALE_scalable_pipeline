# Hard paper-derived task release checklist

This checklist records only evidence available to the shared authoring pass on
2026-08-15. Checked items have a concrete authoring or task-level artifact.
Unchecked items are release blockers and are not assumed to pass. Both current
participant projections passed external paper-blind review after iterative
repair. A clean-checkout audit subsequently invalidated both exact build hashes
because generated text fixtures used CRLF despite repository LF normalization.
Both checkout-stable replacements now pass independent reruns: spectral 10/10
and local 9/9, with zero CRLF or cache files in either task tree.

## Source and legality

- [x] Exact paper/supplement bytes are pinned. Evidence: `source_manifest.yaml` paper and supplement hashes.
- [x] Official code commits are pinned. Evidence: both repository commit and Git-tree IDs in `source_manifest.yaml`.
- [x] Dataset version and present/LFS hashes are recorded, including incomplete-checkout scope.
- [x] Final participant archives contain only generated or repository-owned assets with audited redistribution terms.
- [x] Paper/code/data disagreements and source defects are recorded without silent reconciliation.
- [x] Untrusted source commands were inspected and not executed; pickles were not deserialized.
- [x] Embedded source `.git` directories and restricted/provider bytes are explicitly excluded from parent Git by `authoring/sources/.gitignore`; exact provenance remains in `source_manifest.yaml`.
- [x] The command and tool version that created `1907.13022v2.txt` are recorded and reproduce its SHA-256 exactly.

## Workflow grounding

- [x] Claim/problem tree exists in `workflow_graph.yaml`.
- [x] Execution workflow DAG exists in `workflow_graph.yaml`.
- [x] Each selected task has a concrete target leaf.
- [x] Each selected task uses a meaningful seven-operation backward slice.
- [x] Each operation and artifact has source or benchmark provenance.
- [x] Grounded extensions are labeled as extensions.
- [x] No low-confidence inference is currently designated a hidden participant requirement.
- [x] Cross-file IDs and every task-spec provenance path are validated against landed task packages.

## Hardness

- [x] Each selected design contains at least four meaningful operations.
- [x] Each selected design has dependency depth at least three.
- [x] Each selected design has at least two independent challenge sources.
- [x] Designed difficulty is not primarily formatting, volume, hidden trivia, thresholds, or compute.
- [x] Clone-and-run rejection is confirmed on both final LF-stable exact builds.
- [x] One-formula and shallow-library baselines fail on both final LF-stable exact builds.
- [x] Hard-coded public examples fail hidden tests on both final LF-stable exact builds.
- [x] Intermediate artifacts are designated for private rubric checks where useful.
- [x] The label is changed to `structurally_hard_candidate` only after all final exact-build verification gates pass.
- [ ] Pinned frontier-agent calibration is complete before any frontier-hard claim.

## Public specification

- [x] Each landed participant goal is audited as clear.
- [x] Every visible input is documented in the landed `TASK.md`.
- [x] Required output paths and schemas are explicit and match validators.
- [x] All required scientific definitions and conventions are public.
- [x] Environment, tools, network, dependency versions, and resource limits are public.
- [x] Qualitative success criteria and metric directions are public.
- [x] Exact hidden cases, thresholds, weights, seeds, and references remain private.
- [x] Each task's specification-closure table has no invalid hidden dependency. Evidence: fresh external participant-only reviews pass on both current projections.
- [x] A paper-blind reviewer can restate each task and finds no material missing information.
- [x] Paper/source/device identifiers and direct answer leakage are absent from participant projections.

## References and solvability

- [x] Spectral privileged oracle runs successfully on checkout-stable build `0bba762f4be56c68c2b20c5147c99d37b716f47ae74a8cff88f7f2271e796a1b`.
- [x] Local-model privileged oracle runs successfully on checkout-stable build `9716962c4c4f3338ef2b66a7aea69e10289c8575db33edd64cbadb81e8a62573`.
- [x] Each public-input reference solver reads only participant-visible files on the final build.
- [x] Each public-input reference solver runs in the declared participant environment on the final build.
- [x] Each public-input reference solver fits the resource budget on the final build.
- [x] Each public-input reference solver passes its private evaluator on the final build.
- [x] An independent valid solution passes for each final build.
- [x] No reference solution reads undisclosed constants or source-only files at runtime on the final build.

## Evaluation

- [x] Hard gates are reconciled and pass on both final exact builds.
- [x] Scientific quality receives continuous scoring on both final exact builds.
- [x] Evaluators recompute metrics from submitted artifacts on both final exact builds.
- [x] Submitted programs and models are evaluated behaviorally on hidden instances on both final exact builds.
- [x] Exact code, weights, pickle bytes, and plot pixels are not required by either final build.
- [x] Every absolute and relative tolerance is reconfirmed on both final builds.
- [x] Stochastic task behavior uses multiple instances and documented aggregation on both final builds.
- [x] Exact private thresholds and weights remain absent from both final participant projections.
- [x] Metric weights and score contracts are internally consistent on both final builds.
- [x] Repeated evaluator runs produce identical parsed scores and statuses on both final builds.

## Adversarial validation

- [x] Spectral mutants are classified consistently as 13 mandatory scientific plus one hard ranking failure, and all 14 fail on the final LF-stable build.
- [x] Local-model mutants cover at least five realistic categories and all required mutants fail on the final LF-stable build.
- [x] Malformed and partial outputs fail safely on both final builds.
- [x] NaN/Inf and oversized artifacts fail safely on both final builds.
- [x] Stale cached outputs are detected on both final builds.
- [x] Fabricated self-reported metrics do not influence recomputed scores on both final builds.
- [x] Hard-coded public examples fail hidden tests on both final builds.
- [x] Applicable metamorphic and invariant tests pass on both final builds.
- [x] Participant code cannot read private or author files under the final local evaluator harnesses.
- [x] Network, path, link, and executable-submission policies pass final local evaluator probes.

## Hidden instances

- [x] Private generation and seed separation are reconfirmed on both final builds.
- [x] Public review instances are permanently retired.
- [x] Generated spectral cases preserve the disclosed stationary XOR observation model and latent physicality map on the final build.
- [x] Generated local cases preserve running intersection and bounded-width semantics on the final build.
- [x] Valid solvers pass across ordinary, edge, and OOD private distributions on both final builds.
- [x] Hidden cases include anti-hardcoding label, ordering, topology, scale, and sampling shifts on both final builds.
- [x] Public, hidden, and mutation seeds are demonstrably separated on both final builds.

## Execution and packaging

- [x] Spectral `scripts/verify.py` independently passes 10/10 in 78.0011323 seconds on checkout-stable build `0bba762f4be56c68c2b20c5147c99d37b716f47ae74a8cff88f7f2271e796a1b`.
- [x] Local `scripts/verify.py` independently passes 9/9 in 68.8558793 seconds on checkout-stable build `9716962c4c4f3338ef2b66a7aea69e10289c8575db33edd64cbadb81e8a62573`.
- [x] Participant, private, and author projections are physically separated in both final builds.
- [x] No private or author artifact appears in either final participant package.
- [x] Dependencies and LF-stable generated bytes are reproducible on a clean checkout.
- [ ] Runtime, peak memory, disk, and output sizes are measured.
- [x] A real ALE-compatible environment run is complete or explicitly pending in each final verification report.
- [x] Both final task verification reports are complete and reconciled.
- [x] `session_report.md` contains final exact commands, scores, mutant/metamorphic results, and status.

## Calibration and release

- [x] Exact LF-stable build identities are recorded after all task files stabilize.
- [ ] Pinned frontier-agent trials are run before claiming frontier difficulty.
- [ ] Calibration includes continuous scores, pass/fail, and exact agent-system definitions.
- [x] Difficulty claims state uncertainty.
- [ ] Scientific expert review is complete.
- [x] Final status is selected only after both LF-stable exact builds pass.

## Integration blockers

| Blocker | Required evidence | Expected source |
| --- | --- | --- |
| Peak memory unmeasured | OS-level measurement for both reference solvers | ALE-compatible execution logs |
| Production ALE isolation unverified | run both packages with enforced CPU, memory, filesystem, process, and network limits | ALE integration logs |
| Fixed review seeds are not deployable scored seeds | regenerate retired cases from server-secret seeds | deployment pipeline |
| Collaborator scientific review incomplete | review of all-length spectral fit and benchmark-derived junction-tree/validation semantics | collaborator review |
| No agent calibration | pinned exact task build trials | later calibration session |
