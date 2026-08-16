# Spectral correlation audit

## Objective

Build a reusable analyzer that turns raw randomized-target count histograms into
a nuisance-robust binary error distribution, audits a supplied local graphical
model, and ranks the strongest interactions that the local model cannot express.
The analyzer will be run on unseen inputs with different dimensions, length
grids, target masks, nuisance distributions, and correlations.

Submit exactly one source file at `output/analyze.py`. The evaluator invokes it
as:

```text
python analyze.py --input INPUT_DIR --output OUTPUT_DIR
```

`OUTPUT_DIR` is initially absent. The analyzer must create it and write exactly
the six runtime artifacts specified below. Evaluation recomputes every reported
quantity; self-reported values are not trusted.

## Provided files

| Path | Description |
| --- | --- |
| `input/manifest.json` | Public experiment identity, bit count, sequence lengths, mask convention, and local clique-tree model. |
| `input/raw_counts.csv` | Sparse count rows with header `length,sequence_id,target_mask,observed_mask,count`. |
| `software/validate_submission.py` | Structural public runner for the visible instance. It does not score scientific accuracy. |

All masks are unsigned decimal integers in `[0, 2^n)`. Unit `0` is the
least-significant bit: bit `i` of mask `x` is `(x >> i) & 1`. CSV counts are
positive integers. `sequence_id` is provenance only; counts are pooled, not
averaged per sequence.

The manifest's `local_model.cliques` is an ordered list of unit-index lists.
`tree_edges` contains pairs of zero-based clique-list indices and forms a tree
with the running-intersection property. Every clique and each intersection are
listed in ascending unit order. `top_k_nonlocal` gives the required ranking
length.

The manifest's `count_file` field is authoritative and must be used to locate
the CSV. It is guaranteed to be the literal filename `raw_counts.csv` in this
task version.

### Valid-input envelope

Every public and hidden input satisfies all of these guarantees:

- `6 <= bit_count <= 8`.
- `sequence_lengths` contains 3 through 10 distinct, strictly increasing,
  nonnegative integers, each at most 20. Each listed length has positive pooled
  count, and every CSV row's length occurs in that list.
- `raw_counts.csv` is at most 12,000,000 bytes and has at most 60,000 data rows.
  Every `sequence_id` is 1 through 64 ASCII letters, digits, underscores, or
  hyphens. Masks are in range, counts are positive integers no greater than
  10,000, and pooled counts fit in a signed 64-bit integer.
- `manifest.json` is at most 16,384 bytes. Manifest schema/type strings and
  column declarations have exactly the values shown by the public manifest.
  `experiment_id` follows the same 1-through-64-character ASCII restriction as
  `sequence_id`. The input directory contains exactly the two documented files,
  so total input size is at most 12,016,384 bytes.
- Every clique is a nonempty, ascending list of distinct in-range units, has
  width at most 3, and the clique union covers every unit. There are between 1
  and 8 cliques and no two clique scopes are equal. Clique-tree edges use valid
  distinct clique indices, are unique undirected edges, form a tree, have
  nonempty intersections, and satisfy running intersection.
- `top_k_nonlocal` is a positive integer no larger than the number of pairs not
  co-contained in a clique. Every separator marginal produced by the canonical
  fit/inverse/projection workflow below is at least `1e-3`.
- For every nonzero mode, the bounded all-length decay objective has an
  identifiable global minimizer on the generated instances. More precisely, if
  `L(lambda) = min_{0 <= A <= 1} sum_m (z_m - A*lambda^m)^2` and `lambda_star`
  is the canonical minimizer, then `L(lambda) >= L(lambda_star) + 1e-10`
  whenever `abs(lambda-lambda_star) >= 1e-4`. Latent nuisance amplitudes and
  eigenvalues are positive and bounded away from zero (at least `0.12`), and bit
  variances are nonzero.

These bounds are part of the task contract. Inputs outside this envelope need
not be handled.

## Required workflow and conventions

Let `n = bit_count`, `S = 2^n`, and let `M` be the manifest's ordered sequence
length list.

### 1. XOR correction and aggregation

For every row, the corrected error mask is

```text
x = target_mask XOR observed_mask.
```

For each `m` in `M`, sum `count` over all rows with that length and corrected
mask `x` to obtain `C_m(x)`. Include zero-count masks. Normalize only after
pooling:

```text
q_m(x) = C_m(x) / sum_y C_m(y).
```

Do not average normalized sequence histograms. Repeated or split CSV rows have
additive counts.

### 2. Unnormalized LSB-first Walsh-Hadamard spectra

For every length and mode mask `s`, compute the unnormalized forward transform

```text
qhat_m(s) = sum_x (-1)^popcount(s & x) q_m(x).
```

There is no forward factor of `1/S`. The inverse of a vector `v(s)` is

```text
inverse(v)(x) = (1/S) sum_s (-1)^popcount(s & x) v(s).
```

Rows and modes use ordinary ascending decimal mask order; do not bit-reverse.

### 3. Nuisance-amplitude decay fits

Independently for every mode, fit all supplied lengths to

```text
qhat_m(s) = A_s * lambda_s^m
```

by minimizing the unweighted sum of squared residuals subject to
`0 <= A_s <= 1` and `0 <= lambda_s <= 1`. Lengths are their manifest integer
values, not row positions. Report

```text
fit_rmse_s = sqrt(mean_m((A_s * lambda_s^m - qhat_m(s))^2)).
```

For mode zero, write exactly `A_0 = 1` and `lambda_0 = 1`; its RMSE is computed
against the observed mode-zero spectrum. Some evaluation inputs omit length
zero, so the nuisance amplitudes must genuinely be fitted. Any numerical
optimizer that reaches an equivalent bounded least-squares solution is allowed.

Exponentiation uses the standard empty-product convention `lambda^0 = 1`,
including when `lambda = 0`. If an otherwise valid input ever has multiple
exact global minimizers, choose the one with the smallest `lambda`, then the
smallest `A`; this deterministic tie rule makes the downstream estimate unique.

### 4. Inverse transform and simplex projection

Form the raw estimate

```text
p_raw(x) = inverse(lambda)(x).
```

Then compute the Euclidean projection onto the probability simplex:

```text
p = argmin_u ||u - p_raw||_2
    subject to u(x) >= 0 and sum_x u(x) = 1.
```

The submitted `p` must be finite, nonnegative to numerical tolerance, and sum
to one. Clipping and renormalizing is not generally the Euclidean projection.

### 5. Dependence diagnostics

Treat bit `i` under `p` as a binary random variable `X_i`. For every pair
`i < j`, report:

- mutual information `I(X_i; X_j)`;
- conditional mutual information `I(X_i; X_j | Z)`, where `Z` is the joint
  variable containing every bit except `i` and `j`;
- Pearson correlation of the two `0/1` variables;
- `co_local = 1` iff at least one supplied clique contains both units.

Use natural logarithms throughout, so mutual information and conditional mutual
information are in nats. Terms with zero numerator probability contribute zero.
All private instances have nonzero bit variances; if a degenerate public-derived
case is encountered, define its Pearson correlation as zero.

Writing `p_ab = Pr(X_i=a,X_j=b)`, `p_a = Pr(X_i=a)`, and similarly for the
remaining-bit value `z`, the required formulas are

```text
MI  = sum_(a,b) p_ab * ln(p_ab / (p_a p_b))
CMI = sum_(a,b,z) p_abz * ln((p_abz p_z) / (p_az p_bz))
Pearson = (E[X_i X_j] - E[X_i]E[X_j])
          / sqrt(Var(X_i) Var(X_j)).
```

Any summand with zero leading probability is zero. The valid-input envelope
excludes zero denominators for positive leading probabilities. For `n=2`, the
conditioning variable has one empty-scope value of probability one; hidden
instances in this task have `n>=6`.

### 6. Local-model reconstruction and adequacy

For a scope `U = [u_0,...,u_(k-1)]`, its marginal index is

```text
index_U(x) = sum_r bit(x, u_r) * 2^r.
```

Compute every clique marginal `p_C` from the submitted `p`. For each clique-tree
edge `(a,b)`, let its separator be the sorted intersection
`S_ab = C_a intersect C_b`, and compute `p_S_ab`. Reconstruct

```text
p_local(x) = product_C p_C(x_C) / product_(a,b) p_S_ab(x_S_ab).
```

Normalize the resulting vector to sum to one to remove roundoff. The supplied
instances make all required separator denominators positive.

Let `r = (p + p_local)/2`. Report the natural-log Jensen-Shannon distance and
total-variation distance using exactly

```text
JS_distance = sqrt(0.5 * KL(p || r) + 0.5 * KL(p_local || r))
TV_distance = 0.5 * sum_x abs(p(x) - p_local(x)).
```

This task intentionally uses the square-root distance, not the unsquared
divergence, and natural logarithms, not base-2 logarithms.

Here `KL(u || v) = sum_x u(x) ln(u(x)/v(x))`, with zero-`u(x)` terms defined as
zero. The mixture makes every denominator positive whenever its numerator is
positive.

Rank only pairs with `co_local = 0` by decreasing conditional mutual
information. Break exact ties by increasing `unit_i`, then increasing `unit_j`.
Return the first `top_k_nonlocal` pairs.

## Runtime output schemas

All CSV files use one header row, no index column, and the row ordering stated
below. Numeric text may use any finite round-trippable decimal representation.
Fields documented as masks, lengths, counts, unit indices, ranks, `bit_count`,
and `co_local` must serialize as JSON/CSV integers, not decimal floating-point
strings. Summary ranks are consecutive one-based integers, and summary
`bit_count` equals the manifest value.

### `aggregated.csv`

Header:

```text
length,error_mask,corrected_count,probability
```

Write the Cartesian product of manifest lengths in manifest order and every
`error_mask` from `0` through `S-1` in ascending order.

### `spectra.csv`

Header:

```text
length,mode_mask,coefficient
```

Use the same length order and ascending `mode_mask` order.

### `decays.csv`

Header:

```text
mode_mask,amplitude,eigenvalue,fit_rmse
```

Write one row per ascending mode mask.

### `distribution.csv`

Header:

```text
error_mask,raw_probability,probability,local_probability
```

Write one row per ascending error mask. The last two columns are `p` and
`p_local` respectively.

### `dependence.csv`

Header:

```text
unit_i,unit_j,mutual_information,conditional_mutual_information,pearson_correlation,co_local
```

Write all pairs in lexicographic order: increasing `unit_i`, then `unit_j`.

### `summary.json`

Write exactly this object shape; the ranking list length is the manifest's
`top_k_nonlocal`:

```json
{
  "schema_version": "spectral-correlation-audit-result/v1",
  "experiment_id": "<manifest value>",
  "bit_count": 7,
  "simplex_adjustment_l2": 0.0,
  "jensen_shannon_distance": 0.0,
  "total_variation_distance": 0.0,
  "nonlocal_ranking": [
    {
      "rank": 1,
      "unit_i": 0,
      "unit_j": 3,
      "conditional_mutual_information": 0.0
    }
  ]
}
```

`simplex_adjustment_l2` is `||p - p_raw||_2`. Each ranking record repeats the
corresponding value from `dependence.csv`.

## Submission and public validation

Your submitted directory must contain exactly `analyze.py`, no links or extra
files. The source and all runtime artifacts must be regular files with filesystem
link count one; symbolic links, junctions/reparse points, and hardlinks are
forbidden. From this task directory, run the visible structural check with:

```text
python participant/software/validate_submission.py output
```

The validator executes the analyzer on the visible input and checks the packaged
input byte/identifier envelope, source size/encoding/syntax, executable
interface, inventory, schemas, row identities/order, integer fields, shapes,
finite values, simplex normalization, basic mathematical bounds, and ranking
cross-reference. It executes an immutable copy of the bytes it inspected and
bounds console and artifact growth. It does not sandbox untrusted Python,
enforce CPU or memory limits, check scientific reconstruction accuracy, or
check the full cross-artifact equations. Run it only on code you trust. Passing
it does not imply a private passing score.

## Environment and limits

- Cross-platform CPython 3.12 and NumPy 2.3.5; Python standard library and
  NumPy are the only allowed dependencies.
- Allowed imports are `argparse`, `collections`, `csv`, `itertools`, `json`,
  `math`, `numpy`, `pathlib`, `typing`, and `__future__`.
- CPU only, at most 4 logical cores, 8 GB memory, and 45 seconds per input.
- Network and subprocess creation are disabled. Dynamic code execution,
  runtime-policy monkeypatching, and mutation outside `OUTPUT_DIR` are
  prohibited during private evaluation. The private evaluator applies a local
  audit guard as defense in depth; the ALE service must also execute submissions
  inside its normal OS/container isolation. The public validator is not that
  security boundary.
- `analyze.py` is limited to 150,000 bytes. Combined runtime artifacts are
  limited to 8,000,000 bytes and console output to 40,000 bytes.
- Hidden evaluation uses fresh directories and multiple inputs. Do not rely on
  the current working directory, visible experiment ID, visible dimensions, or
  stale artifacts.

## Public success criteria

- XOR-corrected aggregate counts and spectra are exact up to floating-point
  roundoff.
- Fitted decays predict held-out lengths despite nuisance amplitudes and finite
  sampling.
- The inverse estimate is projected correctly and remains close to the latent
  error distribution across unseen cases.
- Dependence metrics, local-model reconstruction, adequacy distances, and the
  nonlocal ranking are consistent with the submitted distribution.
- Numerical equivalents are accepted; source-code similarity and exact bytes
  are not graded.
- Structural simplex feasibility uses a public `1e-8` normalization tolerance
  and `-1e-12` nonnegativity floor. Scientific fits, latent recovery, and
  near-tied truth rankings use private sampling-calibrated numerical tolerances;
  exact thresholds and weights are not public, but behaviorally equivalent
  bounded minimizers are accepted.
