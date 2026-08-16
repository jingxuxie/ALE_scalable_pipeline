# Public validator

Run `validate_submission.py --submission <root> --run-public`. The submission
root must contain exactly the single-link regular file `output/analyze.py`.
The validator runs it on the retired input with a wall-time and console-output
bound, then checks exact schemas and key coverage, reconstructs packet and
realization-first group statistics, verifies the declared cubic diagnostics
and claims, and applies broad public scientific checks. Before `numpy.load`, it
also checks the physical ZIP/NPY inventory, headers, dtypes, shapes, and
compressed-expansion bounds; input cardinality and the published float64
safety domain are enforced. It also performs a static allowed-import scan; the
private evaluator applies the runtime
filesystem, dynamic-code, process, and network guard.

This public validator is a convenience checker, not a security boundary for
untrusted code. Production evaluation must run submissions inside the ALE OS
sandbox; the private Python guard is additional defense in depth.

The validator contains only public smoke-test tolerances. It does not expose
fresh cases, private score weights, private pass thresholds, or private
reference outputs, so passing it remains necessary but not sufficient.
