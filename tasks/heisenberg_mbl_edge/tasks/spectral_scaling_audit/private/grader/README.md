# Private evaluator security and aggregation

`grade.py` is the private entry point. It expects a submission directory whose
only artifact is `output/analyze.py`.

## Execution boundary

For every hidden case, `core.py` creates a fresh temporary execution tree and
copies in only:

- the participant analyzer;
- the guarded runner; and
- exactly that case's five public-format input files (`manifest.json`,
  `packets.csv`, `eigenvalues.npz`, `queries.csv`, and
  `analysis_grid.json`).

The child process receives paths inside this staging tree. Private truth,
reference outputs, the task repository, and the original submission path are
not present in its arguments, working directory, or environment. The child
environment is an allowlist containing only platform temporary-directory keys,
the Windows system-root keys when applicable, and deterministic UTF-8 Python
settings. The grader drains stdout and stderr concurrently while retaining only
bounded tails, so an analyzer cannot make trusted-process memory grow merely by
printing.

The submission analyzer and every produced artifact must be a single-link
regular file. Symbolic links, Windows junctions, hard links, special files,
extra submission artifacts, and oversized analyzers are hard-gate failures.
Produced files are checked before the trusted grader copies them out of the
child tree for parsing.

`guarded_runner.py` installs a restrictive Python audit hook. It limits imports,
filesystem roots, writes, process creation, networking, dynamic code execution,
and other capabilities. This hook is defense in depth, not a complete sandbox:
Python-level controls share a process with NumPy and the submitted code. A
production deployment must also enforce an operating-system sandbox, CPU and
memory limits, network isolation, a read-only runtime image, and process-tree
termination on timeout.

## Scientific aggregation

Each scientific component is computed independently on every hidden case. The
reported component value is 80% of its across-case mean plus 20% of its
worst-case value. In addition to the aggregate component floors, each case has
a lower mandatory floor. Thus a complete failure on one family cannot be
washed out by strong results on the other families. The case floors are kept
below the aggregate floors to allow ordinary finite-sample variation while
still rejecting missing workflow stages.

The evaluator returns `component_means`, `component_minima`, blended
`components`, aggregate `mandatory_failures`, and
`per_case_mandatory_failures` to make the decision auditable by task authors.

Evidence consistency is exact because every checked claim (case provenance,
row counts, direction, and summaries) is deterministic from the mounted input
and submitted tables. Uncertainty also has an aggregate floor so nominal or
near-zero intervals cannot pass on point estimates alone. Finally, the
stability component is forced to zero when, for every target, all requested
minimum-size/window cells literally repeat the same `(h_c, nu, n_groups)`
triple despite the grid having multiple coordinates. This narrowly detects a
copied primary fit without imposing a generic smoothness assumption on a
meaningfully independent solver.
