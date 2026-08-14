# HNN hard ALE task family

This fixture is a deliberately separate, slower complement to the three-task
HNN smoke family. It turns the canonical scalar-gradient rule
`(dq/dt, dp/dt) = (dH/dp, -dH/dq)` into three compositional challenges whose
hidden graders reconstruct physical truth instead of trusting submitted
predictions or executable model objects.

The source bundle pins *Hamiltonian Neural Networks* arXiv v3 by SHA-256 and
the official implementation by commit. Those identities are retained only in
author-side provenance; every generated agent projection is paper-blind.

## Tasks

- `hnn-hard-coupled-identification` fits a safe coefficient JSON for a
  three-DOF periodic Hamiltonian with off-diagonal kinetic terms and three
  nonlinear pair couplings. Training derivatives are noisy and local; hidden
  evaluation uses wide-angle states and long RK4 rollouts.
- `hnn-hard-variable-nbody` computes energies and complete canonical fields
  for softened attractive gravity with changing body counts, close encounters,
  and a permutation-equivalent case. The grader recomputes every result from
  the public query states.
- `hnn-hard-canonical-recovery` jointly recovers a latent canonicalizing linear
  transform and a coupled quartic Hamiltonian from mixed observed coordinates.
  Equivalent factorizations are accepted because the grader scores the induced
  observed-space field and rollouts, not raw coefficient equality.

Each task builds deterministic instances under
`input/instances/<NNN>/`, common participant software, evaluator-only truth and
graders, golden safe artifacts, one registered realistic mutant per instance,
and author-only provenance and QA notes. The generated `main.py` follows the
current `cua_bench`/`LinuxTaskConfig` ALE task pattern.

## Difficulty consumption

Every task makes an explicit selection from the standard `core` difficulty
profile. The default is `hard`, with `instance_count` overridden to two so the
example remains practical. The builder resolves that selection through
`paper2ale.difficulty`, emits the exact standard proof at
`author/difficulty_manifest.json`, and records the physical mapping and all
concrete generator/grader settings in
`author/difficulty_parameters.json`.

Changing a task selection to `medium`, `hard`, or `frontier` materially changes
sample density, label noise, OOD range, rollout horizon and count, hidden case
count, score tolerances, N-body cardinality, and close-encounter separation.
The label therefore cannot be changed cosmetically without changing generated
bytes and the manifest resolution ID.

## Direct build and checks

The family is registered as `hnn_hard` in the trusted task-family and
verification registries. Build and audit it through the normal CLI:

```powershell
paper2ale audit examples/hnn_hard/project.json --difficulty hard
paper2ale build examples/hnn_hard/project.json --difficulty hard --out dist --jobs 3
```

Run the focused tests from the repository root with:

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -p 'test_hnn_hard.py' -v
```

See [BUILD_REPORT.md](BUILD_REPORT.md) for the verified example build, bundle
hashes, and the distinction between structural difficulty and empirical model
calibration.
