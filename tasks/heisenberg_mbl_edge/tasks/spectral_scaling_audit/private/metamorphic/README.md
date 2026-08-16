# Private metamorphic harness

`harness.py` provides deterministic, NumPy/stdlib-only case transforms and
behavioral output comparisons for the spectral scaling task. It is private
evaluator infrastructure and must never be included in the participant package.
Its subprocess helper is intended for trusted author analyzers during package
verification; untrusted participant code must still run through the private
guarded evaluator.

The suite checks six relations:

1. `row_packet_permutation` reorders packet rows and flat packet blocks, and
   independently shuffles raw eigenvalues within every packet. All outputs are
   invariant after row-key normalization.
2. `realization_id_permutation` applies a global derangement of realization
   labels. Point estimates and evidence are invariant after applying the inverse
   label map. Because a label permutation changes which observation occupies a
   fixed pseudorandom bootstrap index, finite-replicate interval widths are
   checked behaviorally rather than for accidental bitwise equality.
3. `positive_affine_energy` applies the default map `E' = 1.625 E - 4.75`
   to raw energies, extrema, and shift energies. Every scientific output is
   invariant. Evaluator-supplied maps are accepted only after the preflight
   below proves that finite-precision selection and ratio evidence are safely
   conditioned.
4. `affine_control` applies `h' = a h + b`, `a > 0`, to observations and queries
   and multiplies every analysis halfwidth by `a`. The comparator maps controls,
   fitted edges, interval edge bounds, and halfwidths back to the original
   coordinate; `nu`, response predictions, and other quantities are invariant.
5. `target_mirror` maps `target -> 1-target` while reflecting spectra with
   `E -> -E` and swapping extrema. This preserves selected levels and relabels
   the finite-size edge curve. As with ID permutation, target-indexed bootstrap
   streams are compared by interval behavior.
6. `shard_rejoin` deterministically partitions packet blocks into a private
   intermediate shard representation and rejoins them in reversed shard order.
   Before running the analyzer, the harness proves per-packet metadata and raw
   eigenvalues survived the round trip exactly.

Run all checks against an analyzer and one case with:

```text
python -B private/metamorphic/run.py --analyzer author/reference_solver/analyze.py --case private/hidden_inputs/case_amber
```

Use `--work <empty-directory>` to retain transformed cases and outputs, and
`--report <path>` to write the JSON report. Without `--work`, all intermediate
files are placed in a temporary directory and removed automatically. The same
structured report is emitted on stdout and, when requested, at `--report`.
The command returns zero only when every relation passes, making it directly
usable from `scripts/verify.py` or another CI runner.

If any suite or transform preflight raises an exception, `run.py` suppresses
the traceback and exception text because they can contain hidden paths,
analyzer stderr, packet identifiers, or other private evaluator state. It
returns one and emits this minimal report to stdout and `--report`:

```json
{
  "fatal_error": "metamorphic_suite_exception",
  "passed": false,
  "schema_version": "spectral-scaling-metamorphic-report/v1"
}
```

Warnings raised by the parent harness process are converted to exceptions
inside the same boundary. This prevents the default warning renderer from
printing private source paths and line numbers to stderr before the failure
report is produced. Analyzer subprocess output is captured separately by the
harness.

`scripts/verify.py` can import `run_metamorphic_suite` directly. Transform
functions return relation dictionaries accepted by
`compare_output_directories`, so the verifier can also assemble smaller probes.
Default numeric tolerances (`atol=5e-9`, `rtol=5e-8`) cover only text rendering
and benign floating-coordinate roundoff. The relaxed uncertainty checks apply
solely to finite-replicate bootstrap bounds after index relabeling; all point
estimates, grouped evidence, stability fits, and response predictions remain
strict.

## Energy-affine preflight

Positive scale alone is not sufficient to justify energy-affine invariance in
floating-point arithmetic. `transform_positive_affine_energy` therefore
accepts an evaluator map only when `0.5 <= scale <= 2`, all baseline and
transformed energy magnitudes are at most `1e100`, and every packet passes the
following checks both before and after transformation:

- the diagnostic shift satisfies
  `abs(shift_energy-target_energy) <= 0.005*(e_max-e_min)`;
- the retained/unretained distance margin is at least
  `max(1e-8*S, 2**20*ulp(M))` whenever `keep_count < eigen_count`;
- the minimum adjacent gap among selected levels is at least
  `max(1e-9*S, 2**20*ulp(M))`;
- exact preservation of both the stable nearest-level index sequence and its
  subsequent energy-sorted index sequence; and
- maximum perturbation of any retained adjacent-gap ratio at most `1e-10`, well
  below the suite's `5e-9` absolute metamorphic tolerance.

Here `S = max(max(levels)-min(levels), e_max-e_min)` and
`M = max(1, max(abs(levels)), abs(e_min), abs(e_max), abs(target_energy))`,
evaluated separately in the baseline and transformed coordinates. This is the
same quantified float64 predicate promised by the public input contract. It
guards the only target-distance tie that can change membership, rather than
imposing an unnecessary all-pairs distance-separation condition.

The preflight evaluates transformed packet metadata after the same `.17g`
rendering used on disk, so it checks the case the analyzer will actually read
rather than an ideal real-arithmetic map. A rejected map is reported before the
destination case is created. Aggregate span-normalized and ULP margins,
requirement ratios, magnitude maxima, maximum shift fractions, the exact-index
results, and the worst ratio perturbation are stored in the transform relation
and copied into the `positive_affine_energy` test's `conditioning` object in
the JSON report.
