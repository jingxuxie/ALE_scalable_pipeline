# Paper-blind specification review

## Review boundary and frozen snapshot

Two independent fresh reviewers inspected only the participant projection. They
did not inspect the paper, source archive, authoring records, author solvers,
hidden inputs, private evaluator, references, mutants, score thresholds, or task
history. Neither reviewer edited a file. Both reviews hash-gated and passed this
exact replacement snapshot:

- `participant/TASK.md`: `9e578bff82c161fb5a6effa9b35417f26e53e9ba3ac503cf0ae4708fa29762c2`
- `participant/software/validate_submission.py`: `2079a06958294cf580cc707d230cc6acd583b1b03d6c8c45c573460a8478e99b`
- `participant/software/README.md`: `0980bf232343a1b6814f3b96e745e82d2d31a8a2a7c2762691d41d68cfe9d5c8`

## Verdict

**PASS.** The participant package is self-contained, paper-blind,
automatically checkable, and feasible in the disclosed environment. A
participant can implement the complete reference workflow without the paper,
an official repository, private evaluator behavior, hidden answers, or an
unstated scientific convention. The allowed conclusion is finite-size
crossover evidence, not a thermodynamic transition or mobility-edge claim.

This is a specification verdict, not an authoritative replacement-build
verification ledger and not frontier-agent calibration.

## Participant-task restatement

The participant submits one deterministic NumPy analyzer. For each fresh case,
it follows the manifest to bounded raw eigenvalue packets, reconstructs the
requested target energy from `target`, `e_min`, and `e_max`, selects and sorts
levels with stable distance ties, computes adjacent-gap ratios, and aggregates
at the realization level. It then fits a target-dependent finite-size crossover,
executes every minimum-size/halfwidth stability cell, bootstraps complete
realization blocks, predicts held-out coordinates, and emits six mutually
consistent evidence artifacts.

The published reference path fixes canonical coordinates, fixed-window
selection, weighted/rescaled cubic fitting, diagnostics, search grids,
clipping-before-spacing, loop order, strict incumbent ties, bootstrap streams
and nesting, failure handling, quantiles, interval combination, predictive
uncertainty, claims, and numeric serialization. Independent deterministic
estimators remain behaviorally eligible, but are not needed for solvability.

## Decision / implementability / validator matrix

`D` means publicly disclosed, `I` means implementable from public files, and
`M` summarizes public-validator coverage.

| Contract area | D | I | M | Finding |
| --- | ---: | ---: | ---: | --- |
| One-file submission and six-artifact invocation inventory | yes | yes | full | Exact paths, schemas, link, encoding, byte, and row rules are closed |
| Manifest filenames and exact ordered v1 CSV/JSON schemas | yes | yes | full | Manifest-directed, POSIX/Windows-safe bounded filenames are authoritative |
| Physical ZIP/NPY container and preload safety | yes | yes | full preflight | Duplicate/ambiguous names, headers, compression, payload, dtype, endianness, shape, and expansion are bounded before `np.load` |
| Integer lexemes, field widths, finite numbers, and cardinalities | yes | yes | full | 1--20 unsigned ASCII digits, 128-byte fields, and all public caps are explicit |
| Target energy, nuisance shift, stable selection, and ratios | yes | yes | full | The true formula and the `0.005`-span diagnostic-shift bound are distinct and recomputed |
| Realization-first grouping and canonical downstream coordinates | yes | yes | full | Pseudoreplication and raw-coordinate reuse are excluded |
| Weighted cubic, searches, stability, and diagnostics | yes | yes | consequence checks | Exact reference workflow is public; hidden scoring remains behavioral |
| Bootstrap seeds, nesting, interval level, and claims | yes | yes | structural/consistency | Derived target seeds remain uint64 and interval level is exactly `0.68` |
| Predictions and numeric conditioning | yes | yes | broad/full | Raw polynomial is checked before clipping; all public finite-domain bounds are explicit |
| Permutation, affine, mirror, and shard relations | yes | yes | private transformations | Applicability predicates and qualitative relations are public |
| Python/NumPy, time, memory, input/output, and capacity | yes | yes | full where local | Every supplied case is promised oracle-feasible within 180 seconds |
| Filesystem/process/network isolation | yes | yes | partial public, hardened private | Public checker is not a security boundary; production OS isolation remains required |

The public validator is explicitly necessary but insufficient. Its omission of
fresh cases, private scoring knots and weights, exact comparison tolerances, and
production isolation creates no hidden implementation decision because the
normative workflow, validity domain, schemas, and qualitative behaviors are
public.

## Numeric-domain proof

The replacement contract closes the full float64 path rather than relying on a
finite final output:

- observed/query controls and halfwidths have magnitude at most `1e6`, sizes
  are at most `1e6`, and every fitted `nu` lies in `[0.2,4.0]`;
- therefore the mathematical scaling coordinate satisfies `abs(x)<=2e36`,
  with an enforced rounding allowance `abs(x)<=2.1e36`;
- training coordinates satisfy `abs(z)<=1+8*eps`, query coordinates satisfy
  `abs(z)<=2`, weights lie in `[2,400]`, the rank-four weighted design has
  condition number at most `1e12`, coefficient magnitudes at most `1e6`, and
  weighted residual-square sum at most `1e35`;
- the query basis is bounded, giving a mathematical raw cubic bound of
  `15,000,000`; the implementation accepts a `2e7` round cap and checks the raw
  polynomial for finiteness and magnitude before clipping;
- weighted matrices and vectors are checked before `cond`/`lstsq`, and powers,
  coordinates, coefficients, residuals, reductions, spreads, intervals, and
  raw predictions are all explicitly finite.

This supplies a constructive finite-intermediate argument for every reference
fit, stability cell, bootstrap fit, and query, not merely a validator aftercheck.

## Conditioned affine semantics

Affine-control covariance applies only when transformed halfwidths stay in
`[0.4,1e6]`, ten-decimal canonicalization commutes, transformed keys remain
distinct, and rows have disclosed relative clearance from window boundaries.

Positive-affine energy invariance is also conditional in binary64. Both the
original and transformed case must satisfy the magnitude and chunk bounds,
`abs(shift_energy-E_target)<=0.005*(e_max-e_min)`, selected-gap clearance
`max(1e-9*S,2**20*ulp(M))`, retain-cutoff clearance
`max(1e-8*S,2**20*ulp(M))`, exact stable selected-prefix and retained-order
identity, and retained-ratio perturbation at most `1e-10`. Arbitrary maps that
erase resolved gaps are outside the promise. The public contract therefore
matches what a float64 analyzer can actually preserve.

## Physical-input and resource closure

Each case has exactly five single-link regular files. Manifest filenames are
distinct, bounded, NUL-free, filename-only values valid under POSIX and Windows
rules. JSON inputs and the whole case have physical-byte caps. The NPZ contains
exactly `schema_version.npy` and `energies.npy`; original and normalized ZIP
names agree, members are unencrypted stored/deflated NPY v1/v2 payloads with
bounded headers and exact lengths, and energies are native-endian
`numpy.float64`. Packet offsets/counts are checked against the preflighted NPY
shape before allocation and again after load.

Public bounds cover packets, eigenvalues, groups, targets, sizes, controls,
queries, stability cells, bootstrap replicates, IDs, fields, input bytes, and
output capacity. `bootstrap_seed<=18446744073709544552` ensures every
`bootstrap_seed+1009*t` stream for at most eight targets is a uint64 value.
Python is exactly described as `3.11+`, NumPy as `2.3.5`, network is disabled,
each case has 180 seconds, and the suite has 20 minutes.

## Resolved blind-review issues

The final two passes rechecked all earlier closure work and the replacement
additions. Material issues resolved before this snapshot include:

1. publishing a complete fitting, stability, bootstrap, prediction, and claims
   reference algorithm rather than a method-agnostic objective;
2. canonical group-coordinate and canonical halfwidth semantics, underflow-safe
   crossing signs, clipping/spacing/loop/tie order, and bootstrap nesting;
3. exact ordered input columns, bounded ASCII integer grammar, field widths,
   filenames, physical NPZ structure, and pre-allocation cardinality checks;
4. separating the true target energy from the bounded acquisition shift;
5. conditioning affine promises on float64-resolved selection and window
   boundaries;
6. bounding every cubic intermediate and requiring the raw pre-clip query
   polynomial to be finite;
7. fixing resource strings and limits, uint64-derived seeds, exact interval
   level, and output-capacity sufficiency; and
8. limiting the public source scan to allowed imports while delegating actual
   dynamic-code/process/network/filesystem enforcement to private runtime and
   production isolation.

No material ambiguity or task-conforming false rejection remained in either
fresh review.

## Residual scope

Paper-blind review does not decide scientific-grounding quality, private
tolerance calibration, hostile-code sandbox sufficiency, peak memory, or
frontier-agent difficulty. Exact fresh cases, evaluator weights, comparison
knots, pass floors, reference outputs, and mutant implementations remain
private. Those omissions do not impair public solvability.
