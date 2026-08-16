# Scientific mutant suite

`build_mutants.py` reads the clean author reference analyzer and changes only
its dormant `MUTATION_MODE` selector. It materializes 15 complete submissions
at `cases/<mutant_id>/output/analyze.py` and writes a hash-bearing generated
inventory to `cases/mutant_manifest.json`.

Every listed mutant is expected to parse, run on a valid case, and emit all six
required output artifacts. Rejection should therefore come from behavioral,
scientific, uncertainty, or cross-artifact consistency checks rather than a
missing file or malformed schema. The suite spans normalized-energy targeting,
acquisition-shift misuse, spectral ordering and observable definitions,
realization aggregation, clustered uncertainty, finite-size coordinates,
critical-curve modeling, stability, uncertainty propagation, anti-hardcoding,
and evidence integrity.

The `no_size_scaling` build also routes rank-deficient narrow sweep cells to
that mutant's valid primary fit. Removing all size dependence can otherwise
make the cubic design singular in a narrow cell; the fallback keeps the
intended wrong finite-size coordinate while ensuring complete output.

The clean analyzer's dormant `largest_size_only` branch normally stops at its
three-size support guard. For this suite the builder narrowly replaces that
one estimator with a schema-complete shortcut: it takes the midpoint of the
largest-size control sweep as `h_c`, fixes `nu=1`, and retains the normal fixed
fit, bootstrap, prediction, and serialization pipeline. Its stability rows
repeat that same largest-size-only estimate because the shortcut has no
multi-size refit to perform; this remains complete output and is rejected by
the behavioral stability gate.

Build from the task root with:

```text
python private/mutants/build_mutants.py
```

The operation is deterministic and safe to rerun. `manifest.json` documents
the error and expected rejection rationale for every generated case. The
dormant `wrong_group_weight` diagnostic branch is excluded from required
rejections. The participant contract deliberately permits deterministic
weighting choices, and calibration showed this alternative remains
behaviorally valid; rejecting it would couple the evaluator to the reference
implementation rather than the disclosed scientific contract.
