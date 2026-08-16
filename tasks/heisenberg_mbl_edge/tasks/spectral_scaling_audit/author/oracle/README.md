# Trusted oracle

`generate.py` creates the retired case, four unpublished hidden crossover
families, private truth, oracle outputs, and the canonical valid analyzer. The
families are grounded extensions: they preserve bounded adjacent-gap ratios,
weak- versus strong-control limiting behavior, realization clustering,
target-dependent size crossings, and the affine invariants used by
verification. Generator assertions gate those properties. They are not
presented as thermodynamic phase-transition evidence.

The same command also calls `ed_realism.py` to build an author-only realism
fixture from direct exact diagonalization of the periodic random-field
spin-1/2 Heisenberg Hamiltonian in the fixed zero-magnetization sector at
sizes 8 and 10. Its complete shuffled spectra exercise the participant packet
representation and gate the weak/strong-field gap-ratio ordering. The tiny ED
fixture is deliberately not included in the scored finite-size-scaling suite.

From the task root:

```text
python -B author/oracle/generate.py
python -B author/oracle/ed_realism.py --output-root .
```
