# Why verified paper-derived tasks can still be easy

The first Codex authoring kit optimized strongly for provenance, specification
closure, evaluator correctness, hidden-instance coverage, mutation resistance,
and reproducibility. Those properties are necessary, but they do not imply that
a frontier agent will find the participant task difficult.

The generated tasks under `tasks/` expose a recurring failure mode:

> the authoring process spends most of its effort proving that a precisely
> specified numerical recipe is implemented and graded correctly, while the
> participant only needs to translate that recipe into code.

## What happened in the current examples

### Reusable spectral cache

The participant task gives the affine scaling, the complete Chebyshev
recurrence, the exact finite-prefix resolvent contraction, the branch-selection
rule, all output schemas, and diagnostic formulas. The clean-room reference
solver is a small single Python file and the session report records sub-second
solver execution.

This is a good numerical-programming test, but it is not a hard research-agent
task. Hidden energies and prefixes prevent hard-coding; they do not make the
algorithm hard to discover because the algorithm is already public.

### Spinful packet dynamics

The participant task gives the complete Hamiltonian blocks, initial state,
Chebyshev-vector recurrence, Bessel contraction, observables, aggregation, and
structured conclusion rules. A solver must be careful, but it does not need to
make consequential scientific or engineering decisions. The session report
records a clean solver runtime well below one second.

### Periodic orbital transport

The participant task provides the basis order, neighbor enumeration,
Slater-Koster blocks, periodic and device Hamiltonians, surface Dyson equation,
self-energies, Green function, density of states, and transmission formulas.
The result is a longer implementation, but it is still primarily a
specification-following coding task. The reference implementation evaluates the
hidden suite in seconds.

### Disordered sector and spectral-correlation audits

These tasks are described as seven- or nine-operation workflows, but the public
task enumerates nearly every operation, formula, tie rule, aggregation rule,
and output field. Counting `parse`, `assemble`, `diagonalize`, `measure`, and
`aggregate` as separate graph operations inflates structural complexity without
creating uncertainty, search, debugging, or experimental decision-making.

## Root causes

### 1. Operation count was used as a difficulty proxy

A workflow can have ten serial operations and still be easy when every
operation is completely specified and standard. Frontier coding agents are
particularly good at converting long technical specifications into one working
program.

The more relevant quantities are:

- consequential decision points;
- amount of method search or diagnosis;
- number of feedback-and-revision cycles;
- integration across an existing workspace;
- hidden-distribution generalization;
- gap between an obvious baseline and the required outcome;
- observed performance of fresh strong agents.

### 2. Verifier strength was mistaken for task difficulty

A task can reject fifteen realistic mutants and still be easy. Mutation testing
shows that the evaluator distinguishes selected wrong answers from correct
answers. It does not show that producing a correct answer is difficult.

Likewise, hidden cases, anti-hard-coding tests, metamorphic tests, and strict
artifact schemas improve evaluator quality but do not necessarily increase
participant-side reasoning.

### 3. Specification closure became reference-algorithm disclosure

The kit correctly required every solution-critical hidden dependency to be
closed. Codex often satisfied this by copying the reference method into
`TASK.md`: equations, pseudocode, normalization, optimizer, tie rules, and
aggregation.

For hard tasks, specification closure should usually come from an
outcome-defined contract:

- the data and scientific semantics are public;
- required behavior and deliverables are public;
- several methods can succeed;
- the evaluator scores behavior on hidden cases;
- the source method remains author-only.

If only one exact method can pass and that method must be fully disclosed, the
result is usually an implementation task rather than a hard ALE task.

### 4. The clean-room solver created an ease-selection bias

The same privileged Codex session was required to design a task and immediately
write a passing public-input solver. It naturally selected tasks that it could
specify and solve reliably. Because frontier agents share many of the same
coding strengths, these tasks were also easy for an independent strong agent.

A clean-room solver is still required for solvability, but it must not be used
as evidence of difficulty.

### 5. Expensive hardening happened before difficulty falsification

The v1 flow built source manifests, large evidence maps, complete workflow
graphs, private generators, oracles, alternative solvers, many mutants,
metamorphic suites, paper-blind reviews, deterministic packaging, and long
verification reports before any frontier-agent pilot was required.

This explains the long authoring time. The pipeline was thoroughly hardening
tasks that should have been rejected early as recipe-following tasks.

### 6. Single-file hidden-input function synthesis dominated

Most generated tasks ask for one script or a few data files implementing a
fully specified mapping over new inputs. That is close to a scientific coding
benchmark. ALE-level work should more often involve an existing multi-file
workspace, incomplete or faulty components, experimentation, diagnosis,
comparison, and coupled deliverables.

## V2 correction

The v2 authoring kit uses a **screen-then-harden** process.

### Fast screening

Before full source reproduction or evaluator hardening:

1. propose at most three candidates;
2. reject formula-transcription and clone-and-run tasks;
3. identify decision nodes and feedback loops;
4. build only a minimal participant draft and lightweight hidden pilot;
5. run obvious baselines;
6. run fresh strong-agent solve attempts with no source access;
7. reject or strengthen anything solved quickly.

No alternative solver, large mutation suite, exhaustive evidence map, or full
release package is built for a candidate that fails this screen.

### Hardening

Only one surviving candidate is normally hardened:

- targeted source provenance;
- final participant workspace;
- privileged oracle;
- clean-room reference solver;
- private evaluator;
- calibrated tolerances;
- targeted mutants and metamorphic tests;
- paper-blind review;
- release packaging and later full agent calibration.

## Preferred hard-task shapes

V2 prioritizes tasks such as:

- diagnose and repair a multi-file scientific pipeline with realistic latent
  faults;
- adapt a method to a shifted dataset or physical regime;
- select and tune a method under a compute budget using supplied baselines;
- reproduce a result and then perform a nontrivial robustness or ablation
  extension;
- reconcile conflicting intermediate evidence and support a conclusion;
- complete an incomplete experimental workspace where several valid approaches
  are possible;
- optimize an outcome on hidden cases rather than implement a disclosed
  algorithm exactly.

The task should be hard because the participant owns meaningful decisions and
iteration, not because a constant, convention, or threshold is hidden.

## Hardness claims

V2 distinguishes:

- `screen_candidate`: proposed but not tested;
- `rejected_recipe_task`: the public specification is essentially a solution;
- `rejected_pilot_too_easy`: a fresh strong agent solved it within the screening
  budget;
- `hardening_candidate`: passed cheap baselines and difficulty-falsification
  pilots;
- `verified_hard_candidate`: hardened and clean-room solvable, but not yet
  population-calibrated;
- `frontier_challenging`: supported by exact-build trials across pinned frontier
  agent systems.

Structural graph counts alone can never produce the final two labels.

## How the current examples could be strengthened

### Spectral cache

Instead of publishing the complete recurrence and contraction recipe, provide a
multi-module spectral-analysis workspace with a correct slow baseline and
several interacting numerical limitations. Ask the participant to reach hidden
accuracy and memory targets over new spectra, choose a stable approximation,
and justify the selected truncation/broadening policy from generated evidence.
The private evaluator can compare hidden responses and cache reuse behavior
without requiring the source method.

### Spinful dynamics

Provide a runnable propagation pipeline that is accurate on short public times
but unstable or biased on longer, shifted lattices. Require diagnosis, method
selection, repair, hidden-time stability, controlled scalar-versus-Ising
experiments, and an evidence-linked conclusion. Do not prescribe every
Hamiltonian-to-propagator implementation step when several valid propagators can
pass.

### Periodic transport

Provide a partially functioning multi-file package with a scalar public case and
failing rotated/multispecies/contact diagnostics. Require the participant to
repair orbital assembly and lead/device integration, choose a stable surface
solver, validate conservation and causality, and meet hidden accuracy/runtime
objectives. The task remains specification-complete through public interfaces
and physical invariants rather than a line-by-line Green-function recipe.

### Quantum-noise tasks

Provide several plausible local-model or spectral estimators plus noisy public
diagnostics. Require model selection, reconciliation of inconsistent local
statistics, calibration on public holdouts, adaptation to hidden topology/shot
shifts, and a structured anomaly audit. Score predictive probabilities and
rankings against hidden latent models rather than asking for one fully stated
transform pipeline.
