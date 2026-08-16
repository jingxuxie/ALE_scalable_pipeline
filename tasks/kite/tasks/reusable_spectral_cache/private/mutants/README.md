# Private mutant suite

`build_mutants.py` deterministically creates complete, schema-valid submissions
for fifteen realistic scientific failures. It refuses to overwrite a target.
The verifier builds a fresh copy in a temporary directory and requires every
case to retain structural validity but fail the scientific pass contract.

The suite covers affine scaling, recurrence, probe normalization, raw-versus-
kernelized caching, order/prefix handling, per-probe preservation, stale system
binding, response units, broadening scaling, complex branch selection,
order-zero normalization, public-grid hardcoding, and fabricated diagnostics.

Malformed, partial, object-array, non-finite, oversized, extra-file, link, and
stale-schema hard-gate cases are generated separately by `scripts/verify.py`.
