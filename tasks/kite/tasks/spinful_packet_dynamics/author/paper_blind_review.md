# Paper-blind specification review

- Reviewer context: fresh delegated model context
- Source access: none; reviewer was instructed to inspect only `participant/`
- Status: pass

## Restatement

The reviewer identified a 72-site, 127-bond open system with six explicit
realizations.  A participant must assemble six 144-by-144 Hermitian spinful
Hamiltonians, validate their supplied affine bounds, build 52 Chebyshev vectors
per realization, contract at seven public times, compute nine observables,
aggregate two three-member ensembles, and emit the four declared artifacts.
The reviewer understood that `basis.npz` is also contracted at undisclosed
times in `[0, 2.5]`.

## Closure audit

The reviewer correctly enumerated all solution-critical choices: site-major
spin indexing; block orientation, phase and SOC signs; open boundaries;
Hermitian completion; supplied rather than re-fitted rescaling; global packet
normalization; Chebyshev recurrence; truncated Bessel coefficients; observable
normalizations; population standard deviation; per-realization spread before
model averaging; contrast sign; categorical comparison rules; and every output
axis, dtype, key and ordering requirement.

The visible input audit found 72 unique sites, 127 valid nearest-neighbor bonds,
six realizations, complete 432-row onsite coverage, three controlled scalar
field pairs, positive half-widths, and seven unique in-range public times.

## Issues found and resolution

Four non-blocking wording issues were reported and resolved before release:

1. An unused `base_m_z` metadata field was removed from `config.json` generation.
2. Strict spectral containment now uses the open-interval notation `(c-a,c+a)`.
3. `bounds` and `contrasts` are explicitly specified as JSON arrays.
4. Nested analysis objects now explicitly require the exact declared fields.

No material missing definition, file, convention, or constraint remained.  The
reviewer confirmed that it did not inspect the paper, source repository,
`author/`, or `private/`, and did not solve the numerical instance.
