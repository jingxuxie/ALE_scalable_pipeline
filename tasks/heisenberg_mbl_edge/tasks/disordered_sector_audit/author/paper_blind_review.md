# Paper-blind specification review

## Review boundary

The reviewer inspected only the participant package (`participant/TASK.md`, the
retired `experiment.json`, and the public structural validator). The reviewer
did not inspect the source paper, parent authoring evidence, hidden inputs,
references, evaluator, oracle, author solvers, mutants, or private thresholds.

## Final verdict

**PASS.** The participant package is self-contained and sufficient to implement
the requested executable without paper access or private information.

The final follow-up review confirmed:

- the fixed-sector basis, Hamiltonian coefficients/signs, periodic boundary,
  reversed extremal-energy normalization, interior packet eligibility,
  deterministic tie break, and zero-based state rank are explicit;
- input types, cardinality/range bounds, identifier scopes, comparison
  descriptor matching, simple-spectrum guarantee, and conditioned packet
  cutoff remove underspecified valid-domain cases;
- real-space Schmidt entropy, natural-log participation entropies, subsystem
  magnetization mean/variance, realization-first means, and clustered SEM are
  operationally defined;
- output keys, row identities, canonical ordering, finite-number requirements,
  and the `positive_effect` relation are unambiguous, with no residual
  statistically suggestive `supported` field;
- the retired input obeys the disclosed schema and size envelope, and paired
  weak/strong comparisons have matching `L`, `n_up`, `exchange`, energy target,
  and subsystem descriptors;
- the public submission validator is structural only and does not reveal a
  hidden scientific answer.

No material paper-blind ambiguity or arbitrary missing constant remained. The
review did not assess scientific grounding, hidden evaluator thresholds,
security isolation, or frontier-agent difficulty; those are author/private
release responsibilities.
