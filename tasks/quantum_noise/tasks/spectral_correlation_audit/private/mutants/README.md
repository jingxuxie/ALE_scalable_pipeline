# Scientific mutant suite

`build_mutants.py` applies one realistic scientific error at a time to a valid
analyzer. Thirteen mutants execute successfully, emit six mutually linked
schema-valid artifacts, and then fail a mandatory scientific submetric. The
`ascending-cmi-ranking` mutant emits well-formed files but intentionally violates
the exact global-top-k cross-artifact contract, so it is rejected by that hard
linked-ranking gate. Parser, security, malformed, partial, nonfinite, and
oversized cases are tested separately by `scripts/verify.py`.
