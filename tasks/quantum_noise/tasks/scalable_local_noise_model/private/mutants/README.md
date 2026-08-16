# Scientific mutant suite

`build_mutants.py` derives eleven reproducible faulty submissions from the
clean-room solver. Each changes one scientifically meaningful convention while
retaining the same input/output interface. The suite covers table orientation,
separator conditioning, root estimation, smoothing, cross-clique queries,
audit ranking, a concealed single-topology failure, validation leakage,
hash-seed nondeterminism, stale outputs, and incomplete models. Every listed
mutant is required to fail the private score contract or a hard gate.
