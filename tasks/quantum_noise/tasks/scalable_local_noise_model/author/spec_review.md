# Paper-blind specification review

## Review context

The reviewer received only the planned participant-facing objective and schema,
with no paper, source repository, private generator, evaluator, reference
solver, thresholds, or answers. The first pass identified four material closure
requirements: a unique public model family or explicitly behavioral target; an
authoritative flat-table axis convention; exact partial-assignment semantics;
and an exact definition of a validation interaction and its rank score.

## Resolved review

The final participant package now supports this correct restatement:

> Implement one deterministic solver for unseen binary junction-tree instances.
> Estimate normalized root and child-conditional factors from independent noisy
> clique counts, marginalize unmentioned variables when answering conjunction
> probabilities, predict held-out parity-event rates, rank their disclosed
> standardized residuals, and report recomputable normalization and fit
> diagnostics without constructing a global `2**n` table.

The following decisions are explicitly public:

- binary coding and `index = sum(value[j] * 2**j)` with a worked child-factor example;
- rooted running-intersection layout, separator ordering, and exactly-once variable introduction;
- normalized root-times-conditionals joint representation;
- predictive evaluation against a latent member of the disclosed family, so no secret canonical projection is required;
- count totals, zero-cell behavior, a disclosed smoothing baseline, and validation isolation;
- joint evidence probability (not conditional or log probability), empty evidence, input order, and legal IDs;
- parity-event meaning, exact signed z score, descending absolute score, tie rule, and top-k behavior;
- output fields, numeric domains, invocation, hidden size ranges, dependencies, and resource limits;
- qualitative scientific metrics while exact cases, thresholds, and weights remain private.

A second fresh paper-blind audit then checked the literal finalized text and
public validator. It
found and resolved nine narrower closure defects: validation may also determine
the diagnostic interaction inventory; all source/output caps now use exact
decimal bytes; `audit_top_k` is guaranteed in `[0,M]`; count and validation ID,
scope, and count invariants are explicit; smoothing is strictly positive;
rank ties use evaluator-recomputed binary64 values; fitted separator TV is
explicitly based on adjacent induced clique marginals; and the exact
`declared_bounds` object is public. A validator-focused follow-up required exact
audit/diagnostic record checks, strict `[0,1]` factors, rank-order validation,
and flagged top-k ordering; those checks were added. The reviewer then reopened
the amended participant package and returned `PASS` with no further issue.

A later security-only amendment made CLI root checks lexical before `lstat`, so
symlink/reparse submission and output roots cannot be erased by resolution. It
did not change task semantics, schemas, visible input, or the expected workflow.
The amended participant build is SHA-256
`f095d644815187489501b6a83567f01888b929b47164156f140b9bc6f0841834`.

The participant-visible package contains every referenced file. Intended freedom
is limited to the statistical reconciliation method and dynamic-programming data
structures; the evaluator is behavioral on induced probabilities. No remaining
solution-critical choice depends on the paper or a private convention.

## Status

- Reviewer source access: absent
- Task restatement: correct
- Missing public files or definitions: none after revision
- Intended method freedom: understood
- Material ambiguities: none
- Result: pass after an independent final restricted-package re-review
