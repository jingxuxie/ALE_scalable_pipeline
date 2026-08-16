# Local verification

Run the complete cross-platform release suite from any working directory:

```text
python <task-root>/scripts/verify.py \
  --results <task-root>/author/verification_results.json
```

The verifier writes nothing into the package unless `--results` is supplied.
It regenerates the oracle and exact-diagonalization realism fixture in fresh
temporary roots, builds both clean-room submissions, repeats private grading,
regenerates and grades every scientific mutant, runs structural/security and
hard-link probes, and checks all required metamorphic relations. It exits zero
only when every release gate passes. The results path is restricted to the
task's `author/` or `scripts/` directory so private diagnostics cannot
accidentally enter the participant package.

`--jobs` controls mutant-grade concurrency (one through four). The default is
two, which respects the four-core task budget while keeping local verification
reasonably quick.
