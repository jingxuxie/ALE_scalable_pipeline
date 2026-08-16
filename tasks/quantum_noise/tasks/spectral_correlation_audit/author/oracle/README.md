# Privileged oracle and instance generator

`generate.py` constructs one permanently retired public review instance and
four private cases from disjoint deterministic authoring seeds. It independently
forms a nonnegative Pauli-support law, applies the two-thirds observation
visibility map, forms the full character matrix, synthesizes the exact
convolution spectra, samples randomized-target histograms, and writes hidden
truth distributions and decay parameters. The suite includes both chain and
branched running-intersection clique trees. It also packages a separately named canonical reference
submission for parser, behavioral-grading, mutant, and robustness tests; that
submission is not the privileged oracle. `scripts/verify.py` uses the latent
truth directly to check the generator equations, physical visibility roundtrip,
and continuous evaluator ceiling in memory. The latent truth record is not
expected to minimize the noisy-count least-squares objective; that documented
contract gate is instead exercised by the canonical executable reference.
Before scored publication, the fixed hidden seeds must be replaced by a
server-secret generation policy.
