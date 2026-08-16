# Finite-Size Spectral Crossover Audit

## Objective

Write a deterministic analyzer that converts raw, realization-clustered
eigenvalue packets into an evidence-backed finite-size crossover curve. Your
submission is an executable Python program, not a table of answers. It will be
run on fresh cases with different size grids, control coordinates, target
coordinates, sampling imbalance, packet order, and crossover shapes.

This is a finite-size inference task. A successful result is evidence for a
finite-size spectral crossover; it is not proof of a thermodynamic transition
or mobility edge.

## Submission and invocation

Submit exactly one single-link regular file: it must not be a symbolic link,
hard link, junction/reparse-point alias, device, socket, or other special file.

```text
output/analyze.py
```

The file must be UTF-8 text without a byte-order mark and at most 250,000
bytes. It is invoked once per case as

```text
python output/analyze.py --input <case-directory> --output <result-directory>
```

`<result-directory>` normally does not yet exist. The analyzer must create it
(including missing parents) and create exactly these six regular files in it:

```text
realization_stats.csv
packet_stats.csv
transition.csv
stability.csv
predictions.csv
claims.json
```

Each produced artifact must likewise be a single-link regular file, and the
result directory must not be a link or junction. Do not create logs, caches,
directories, or temporary files inside the result directory. The analyzer may
not read or write outside its case and result
directories, launch another process, use the network, dynamically execute
code, or depend on retired-case filenames, identifiers, coordinates, row
order, or numeric answers. Private evaluation uses a filesystem/process/network
guard in addition to behavioral checks.
Each of stdout and stderr is capped at 1,000,000 bytes; normal submissions
should keep both streams quiet.

## Environment and bounds

- Python 3.11 or newer and NumPy 2.3.5.
- The guarded environment supports `argparse`, `collections`, `csv`,
  `itertools`, `json`, `math`, `pathlib`, `typing`, and NumPy. Do not import
  SciPy, pandas, another compiled extension, or an unlisted module.
- No GPU or network. Four CPU cores and 8 GB RAM are available.
- Each v1 invocation has the 180-second wall-time limit declared by the
  manifest. Every supplied case is oracle-tested to complete the disclosed
  reference workflow within that limit on the stated environment. The complete
  hidden suite has a 20-minute budget.
- The six output files together may occupy at most the positive integer byte
  limit in `manifest.json`, which never exceeds 4,000,000 bytes. If `P`, `G`,
  `T`, `S`, and `Q` are the packet, observed-group, target, stability-cell, and
  query counts, respectively, every case guarantees
  `output_bytes >= 512*(P+G+T+T*S+Q)+8192`. Thus every mandatory row serialized
  at the required precision fits within the cap.
- A case has 1--8 targets, 3--8 sizes, 5--21 controls per target-size curve,
  2--128 realizations per observed group, at most 6,000 packets, at most
  4,096 eigenvalues per packet, at most 5,000,000 flat eigenvalues, and at most
  512 queries. Every packet size, query size, and `min_sizes` entry is at least
  `1` and at most `1,000,000`. Case IDs, tokens, packet IDs, realization IDs, and query IDs
  are nonempty UTF-8 strings of at most 48 encoded bytes. Total case-input size
  is at most 256 MiB. `manifest.json` and the analysis-grid JSON are each at
  most 65,536 physical bytes. The physical NPZ expands to at most 40,020,000
  bytes across its two bounded members.

Every required fit has at least eight observed groups from at least three
sizes. Every target has at least three observed sizes, and every group has from
2 through 128 realizations. Coordinates and all numeric input values are
finite. Every raw energy, spectral extremum, and shift energy has absolute
value at most `1e100`. Every observed/query control and every analysis
halfwidth has absolute value at most `1e6`. The tighter control bound supports
the explicit float64 proof below. Sizes are positive.

## Input contract

The retired example is under `input/`. The bootstrap manifest filename is
always exactly `manifest.json`; it is the only fixed input filename. Every case
also contains the four data files named inside that manifest. In the retired
case those files are:

```text
manifest.json
packets.csv
eigenvalues.npz
queries.csv
analysis_grid.json
```

The entries of `manifest["files"]` are authoritative. Each is a distinct,
nonempty UTF-8 filename of at most 128 encoded bytes, not a path: it contains
neither `/` nor `\`, is not absolute or drive-qualified under either POSIX or
Windows path rules, and is neither `.` nor `..`. A case directory contains
exactly `manifest.json` and those four single-link regular files, with no
directories or extra artifacts. In particular, always open the packets,
eigenvalue archive, queries, and analysis grid through those
entries even though the retired filenames are conventional. The manifest also
supplies the case ID/token, exact CSV column lists, resource limits, and a grid
summary. Do not infer a fresh case from the retired summary.

`manifest["resource_contract"]` has exactly the keys `python`, `numpy`,
`network`, `wall_time_seconds`, and `output_bytes`. The first three values are
strings (`python` is exactly `3.11+`, `numpy` is exactly `2.3.5`, and
`network` is `disabled`). `wall_time_seconds` is the JSON integer `180` in v1 and
`output_bytes` is a positive JSON integer no greater than 4,000,000 and obeys
the row-capacity formula above; Booleans and numeric strings are invalid for
either integer.

Before any array allocation, the NPZ archive named by
`manifest["files"]["eigenvalues"]` has exactly two *physical ZIP entries* (so
duplicate member names are invalid), named exactly `schema_version.npy` and
`energies.npy`. For each entry, `ZipInfo.orig_filename` and
`ZipInfo.filename` are identical exact names and contain no NUL character.
Both are unencrypted, non-directory members using ZIP stored or deflate
compression. Their summed uncompressed size is at most 40,020,000 bytes. Each
is NPY v1.0 or v2.0 with a header of at most 4,096 bytes,
`fortran_order=false`, and physical member length equal to the NPY
preamble/header length plus the dtype-and-shape payload length—no truncation or
trailing payload is allowed. The logical arrays are:

- `schema_version`: zero-dimensional NumPy Unicode array whose scalar string is
  exactly
  `spectral-scaling-eigenvalues/v1`;
- `energies`: one-dimensional finite array whose dtype is exactly the
  native-endian `numpy.dtype(numpy.float64)`, with from 1 through 5,000,000
  entries (exactly eight payload bytes per entry).

The schema Unicode dtype occupies at most 256 bytes. Object, structured,
subarray, and other dtypes are absent. Only after these physical size, member,
header, dtype, and shape checks is it safe to call
`numpy.load(..., allow_pickle=False)`. The case provider and public/private
preflight perform these container checks before invoking a submission; an
analyzer may rely on this valid-input guarantee and need not import `zipfile`
(which is not in its guarded import allowlist).

In v1, `manifest["packet_columns"]` is exactly this ordered JSON array:

```json
["packet_id","realization_id","size","control","target","e_min","e_max","shift_energy","keep_count","eigen_offset","eigen_count"]
```

The packet CSV has one row per raw packet and exactly those columns in that
order:

| Column | Meaning |
| --- | --- |
| `packet_id` | Unique, nonempty packet identifier. |
| `realization_id` | Independent sample identifier within one target-size-control group. |
| `size` | System-size integer from 1 through 1,000,000. |
| `control` | External crossover-control coordinate. |
| `target` | Normalized energy target in `[0,1]`. |
| `e_min`, `e_max` | Per-realization spectral extrema, with `e_min < e_max`; every raw eigenvalue in the packet slice lies in the closed interval `[e_min,e_max]`. |
| `shift_energy` | Diagnostic acquisition shift; do not use it in place of the target formula. |
| `keep_count` | Number of levels nearest the target to retain. |
| `eigen_offset`, `eigen_count` | Slice into the flat `energies` array. |

Packet rows cover the flat array consecutively in CSV row order: the first
offset is zero, every later offset equals the preceding offset plus count, and
the final slice ends at `energies.size`. Each packet has
`5 <= keep_count <= eigen_count <= 4096`.

There is exactly one packet for each observed
`(target,size,control,realization_id)` key. A `realization_id` may occur in
another group; it does not link samples across controls. Thus one packet is the
complete resampling block for that group-realization. Packet IDs are unique,
but they are not output keys.

### Packet statistic

For each packet, calculate

```text
E_target = e_max + target * (e_min - e_max)
```

Choose the `keep_count` entries with smallest absolute distance from
`E_target`. Break an exact distance tie by the earlier position in that
packet's NPZ slice (equivalently NumPy stable `argsort`), and then sort the
chosen energies in ascending numeric order. The inputs have no intentional
exact energy degeneracies. With sorted levels `E_0,...,E_(k-1)`, define

```text
delta_i = E_i - E_(i-1)                 for i = 1,...,k-1
r_i     = min(delta_i,delta_(i+1))
          / max(delta_i,delta_(i+1))    for i = 1,...,k-2
```

All selected gaps are strictly positive. Therefore a packet contributes
`keep_count - 2` finite ratios in `[0,1]`. Its realization statistic is their
ordinary arithmetic mean.

The diagnostic shift also satisfies
`abs(shift_energy-E_target) <= 0.005*(e_max-e_min)`, a dimensionless condition
preserved by positive affine energy maps. The input has the following
quantified float64 safety predicate. For one packet,
let `E` denote its raw energy slice and define

```text
S = max(max(E)-min(E), e_max-e_min)
M = max(1, max(abs(E)), abs(e_min), abs(e_max), abs(E_target))
u = 2**20 * ulp(M)
gap_margin    = max(1e-9*S, u)
cutoff_margin = max(1e-8*S, u),
```

where `ulp(M)` is Python `math.ulp(M)`. Every adjacent gap in the retained,
sorted levels is at least `gap_margin`. If `keep_count < eigen_count`, sort all
absolute target distances stably as `d_1 <= ... <= d_n`; the retain cutoff
satisfies
`d_(keep_count+1)-d_keep_count >= cutoff_margin`. These margins keep every raw
difference used by the ratio calculation positive and keep cutoff/tie
membership stable well above binary64 rounding noise.

### Group statistic and canonical keys

Numeric output keys are canonicalized as

```python
round(float(value), 10)
```

using Python/NumPy round-to-nearest-even behavior. Apply this to `target`,
`control`, and `halfwidth` when constructing or matching keys. Packet/output
`size` cells and all count/flag fields are base-10 integers. In CSV input and output, every such
integer is encoded as 1 through 20 unsigned ASCII decimal digits (`0` through
`9`), with no sign, whitespace, separator, exponent, or decimal point; leading
zeros are allowed. Every input and output CSV field, including identifiers and
numeric text, occupies at most 128 bytes when UTF-8 encoded.
Different input keys remain different after canonicalization.

The canonical `target` and `control` values of each observed group are also
the numerical coordinates used in every window, crossing, fit, stability,
bootstrap, prediction-model, and claims calculation; do not return to raw
packet coordinates after grouping. For a query, canonicalize its `target` only
to select the target model, while using its supplied finite `size` and
`control` values numerically.

For a `(target,size,control)` group, let `m_j` be the packet mean of its
`R >= 2` realizations. Report

```text
mean_r = sum_j m_j / R
se_r   = sample_std(m_1,...,m_R; ddof=1) / sqrt(R)
```

The group `n_ratios` is the sum of its packet ratio counts, and
`n_realizations` is `R`. The group mean is an *unweighted* mean of realization
means. Pooling individual ratios, weighting by packet count, or treating ratios
as independent samples is scientifically invalid.

In v1, `manifest["query_columns"]` is exactly the ordered JSON array
`["query_id","target","size","control"]`. The query CSV has exactly those
columns in that order and contains at least one data row. Query IDs are unique and nonempty, sizes are finite
numbers in `[1,1_000_000]`, controls are in `[-1e6,1e6]`, and every query
target matches an observed canonical target.
Queries contain no observations; some sizes/controls interpolate and some
modestly extrapolate the observed grid.

The analysis-grid JSON object has exactly these scalar/container types. A
"JSON number" below means a finite JSON integer or float, never a Boolean or a
numeric string.

- `schema_version` is the string
  `spectral-scaling-analysis-grid/v1`;
- `min_sizes` is a nonempty array of at most eight unique JSON integers from
  `1` through `1,000,000`;
- `halfwidths` is a nonempty array of at most eight unique JSON numbers, each
  in `[0.4,1e6]`;
- `primary_min_size` is a JSON integer present in `min_sizes`;
- `primary_halfwidth` is a JSON number present in `halfwidths` after the public
  ten-decimal canonicalization;
- `bootstrap_replicates` is a JSON integer from `8` through `64` inclusive;
- `interval_level` is the JSON number `0.68` in v1.

The Cartesian-product stability grid contains from 2 through 24 cells, so the
across-variant sample standard deviations below are defined and the public
runtime budget remains bounded. The manifest's `bootstrap_seed` is a JSON
integer (not a Boolean or string) in `[0,18446744073709544552]`, which equals
`[0,2**64-1-1009*7]`. With at most eight sorted targets, every disclosed
`bootstrap_seed + 1009*t` stream therefore remains an unsigned 64-bit integer.

After reading the grid, canonicalize every halfwidth with
`round(float(value), 10)` and use that canonical value both as its output key
and in every numerical window, search-radius, stability, bootstrap, and
prediction calculation. The supplied values stay unique and in `[0.4,1e6]`
after canonicalization. Canonicalize `primary_halfwidth` the same way before
matching or using it.

## Required finite-size reference analysis

The following algorithm is the reproducible reference workflow. It is
sufficient to solve every evaluation case. The evaluator uses numerical and
behavioral comparison, so an independently implemented deterministic estimator
may be used for `h_c`, `nu`, intervals, and predictions, provided it retains the
exact packet/group statistics, required diagnostic semantics, covariance, and
comparable out-of-sample behavior. Merely emitting plausible values or fitting
the retired case does not pass.

For each target independently use the finite-size coordinate

```text
x = (control - h_c) * size**(1/nu),       nu > 0.
```

### 1. Fixed observation-window center

Compute a preliminary control center once for any dataset passed to a fit:

1. For each size in ascending order, sort that size's grouped rows by control.
   If there are `n` rows, set `f = max(2, min(3, n // 3))` and
   `midpoint = (median(first f mean_r) + median(last f mean_r)) / 2`.
2. Scan adjacent curve points in ascending control order. If the left value is
   exactly the midpoint, add its control as a crossing. Otherwise, when the two
   offsets from the midpoint have opposite signs or the right offset is zero,
   and the two means differ, add their linearly interpolated crossing.
3. For that size retain the crossing closest to the median of its controls.
   A distance tie retains the first crossing encountered.
4. The preliminary center is the median retained crossing across sizes. If no
   size has a crossing, it is the median control of all grouped rows.

For a requested `(min_size, halfwidth)`, select rows satisfying

```text
size >= min_size
abs(control - preliminary_center) <= halfwidth * (1 + 1e-12).
```

This selected observation set remains fixed while trial `h_c` and `nu` change.
The half-width is therefore preliminary-center based, not trial-`h_c` based;
`h_c` centers the scaling coordinate `x`. A valid selected set has at least
eight rows and three distinct sizes, as all supplied cases guarantee.

### 2. Weighted cubic at fixed parameters

At a trial `(h_c,nu)`, calculate `x` for each selected group and set

```text
x_scale = max(max(abs(x)), 1.0)
z       = x / x_scale
p(z)    = a0 + a1*z + a2*z**2 + a3*z**3
weight  = 1 / max(se_r, 0.0025).
```

Solve the weighted least-squares system with NumPy
`lstsq(matrix * weight[:,None], mean_r * weight, rcond=None)`. Rank must be
four. Define

```text
validation_rmse = sqrt(sum((p(z)-mean_r)**2 * weight**2)
                       / sum(weight**2)).
```

Despite the historical field name, this is the weighted residual RMSE on the
fixed selected groups, not a held-out score. The fit `n_groups` is exactly the
number of selected grouped rows.

#### Float64 domain and standardized-coordinate bound

All primary, local-refinement, stability, and bootstrap point estimates use
`0.2 <= nu <= 4.0`, and every `h_c` candidate is clipped to the target's
observed control range. Consequently

```text
abs(control-h_c) <= 2e6
size**(1/nu)     <= (1e6)**5 = 1e30
abs(x)           <= 2e36.
```

To allow for the last float64 rounding step, the enforced round cap is
`abs(x) <= 2.1e36`. Every supplied primary/stability/bootstrap cubic
evaluation satisfies this cap. Its `x_scale` is finite in `[1,2.1e36]`, and
every training coordinate satisfies `abs(z) <= 1` up to eight float64
epsilons. Since
realization means are in `[0,1]`, the SEM floor makes every reference weight
lie in `[2,400]`. Every disclosed weighted design has at most 6,000 rows, rank
four, 2-norm condition number at most `1e12`, fitted coefficient magnitudes at
most `1e6`, and weighted squared-residual sum at most `1e35`.

For each supplied query, standardization by its target's primary `x_scale`
guarantees `abs(z_query) <= 2`. Thus the absolute cubic basis is bounded by
`[1,2,4,8]`, and the finite raw polynomial value is at most `15,000,000` in
absolute value (the validator permits the round cap `2e7`). These guarantees
apply per case and query, rather than relying only on the final `[0,1]` range.

Check finiteness after forming powers, `x`, `x_scale`, `z`, basis arrays,
weights, weighted matrices/vectors, least-squares coefficients, residuals,
squared reductions, bootstrap/stability spreads, interval endpoints, and the
raw query polynomial. Check the weighted matrix and weighted observation
vector before calling `cond` or `lstsq`. A non-finite or out-of-bound candidate is invalid. In
particular, test the raw polynomial for finiteness and the `2e7` bound *before*
calling `clip`; clipping infinity is not a valid prediction.

### 3. Deterministic parameter search

Let `low` and `high` be the minimum and maximum control for all grouped rows of
the target, and `span = high-low`.

For the primary global search, examine the Cartesian product, with `h_c` as the
outer loop and `nu` as the inner loop:

```text
h_c: 29 linearly spaced values from low + 0.08*span
                              through high - 0.08*span
nu:  23 log-spaced values from 0.35 through 2.6
```

Keep the lowest-RMSE full-rank fit. An exact RMSE tie keeps the first candidate
in the loop order. Refine twice. On each refinement, center a new 11-by-11
linear grid on the current best, using

```text
h_c radius = max(span/80, halfwidth/18), clipped to [low,high]
nu  radius = max(0.04, 0.14*current_nu), clipped to [0.2,4.0].
```

For every primary, stability, and bootstrap search grid in this section,
first clip the lower and upper endpoints to their stated bounds and then call
`linspace` (or take a linear spacing in log space for a stated log-spaced
grid). Iterate `h_c` as the outer loop and `nu` as the inner loop. At every
initial or refinement grid, update the incumbent only for a *strictly* smaller
RMSE, so the first exact tie is retained. The fit produced with
`primary_min_size` and `primary_halfwidth` is the primary fit used in
`transition.csv` and for predictions.

At the start of each primary, stability, or bootstrap search, the incumbent is
unset. A supplied seed only defines the initial grid endpoints: do not evaluate
or adopt the seed separately unless it is itself a grid point. The first
full-rank initial-grid candidate becomes the incumbent; if none exists, that
search fails. Thereafter the incumbent persists while both refinement grids
are scanned and is retained when no strictly better full-rank candidate is
found, even if it is not a point on the current refinement grid.

For each stability variant, seed a separate search at the primary
`(h_c,nu)`. Its initial 11-by-11 product is

```text
h_c: primary_h_c +/- 0.35*max(halfwidth,0.4), clipped to [low,high]
nu:  log-spaced from max(0.25,0.65*primary_nu)
                   through min(3.5,1.45*primary_nu).
```

The `halfwidth` in this stability radius is the canonical numerical halfwidth
for that variant. Then apply the same endpoint-clipping, loop order, first-tie
rule, and two refinements. The stability fit recomputes the
preliminary center from the target's original grouped rows, but never moves
the selected rows with a trial `h_c`.

### 4. Stability fields and transition score

Run every Cartesian-product pair from `analysis_grid.json["min_sizes"]` and
`["halfwidths"]`, including the primary pair. Each supplied case supports all
fits, so the reference emits `fit_ok=1` for every row. Report the fitted
`h_c`, `nu`, weighted residual `validation_rmse`, and selected-row `n_groups`.
Because the stability entry for the primary grid pair is a fresh centered
search, it need not be bitwise identical to the global primary fit reported in
`transition.csv`.

For the transition row, set

```text
fit_score = 1 / (1 + primary_validation_rmse / 0.02).
```

Across all stability variants for that target, calculate sample standard
deviations (`ddof=1`) `s_h` and `s_nu`. Set

```text
stable = int(s_h <= 0.5*primary_halfwidth and s_nu <= 0.9).
```

These are declared diagnostic definitions, not private pass thresholds. The
evaluator recomputes scientific quality and does not trust a self-reported
score or flag.

### 5. Realization-cluster bootstrap and intervals

`analysis_grid.json` supplies `bootstrap_replicates` and `interval_level`.
Evaluation cases use interval level `0.68`; the reference therefore takes the
NumPy default-linear quantiles `0.16` and `0.84`. It performs exactly the
supplied number of replicates.

Sort targets by canonical numeric value and give them zero-based index `t`.
For each target create a fresh

```python
numpy.random.default_rng(int(manifest["bootstrap_seed"]) + 1009*t)
```

stream. The loop nesting is exactly replicate outermost, then groups in
ascending `(size,control)` order, with realization means within each group
ordered lexicographically by `realization_id`:

```python
for replicate in range(bootstrap_replicates):
    for group in groups_sorted_by_size_then_control:
        indices = rng.integers(0, R, size=R)
```

Thus, in every replicate and every group, draw `R` integer indices uniformly
with replacement using
`rng.integers(0, R, size=R)`. Resample the complete realization means, then
recompute that group's unweighted mean and `ddof=1` SEM. Fit the resulting
group table using the primary grid pair and a local search seeded at the
primary fit:

```text
h_c: primary_h_c +/- 0.22*max(primary_halfwidth,0.4), 11 linear points,
     clipped to [low,high]
nu:  the same 11-point log range max(0.25,0.65*primary_nu) through
     min(3.5,1.45*primary_nu),
then the same two 11-by-11 refinements.
```

The bootstrap grid uses the same endpoint-clipping-before-spacing,
`h_c`-outer/`nu`-inner, and first-exact-tie rules stated above.

The bootstrap fit recomputes its preliminary center from the resampled group
means. If a replicate has insufficient support or rank, discard it without
rewinding the random stream. Fewer than `max(8, bootstrap_replicates//2)`
successful fits is an analysis failure; supplied cases are constructed not to
fail.

Let `(q_h_lo,q_h_hi,q_nu_lo,q_nu_hi)` be the four bootstrap quantiles. Combine
bootstrap and stability sensitivity as

```text
d_h  = sqrt(max(primary_h_c-q_h_lo, q_h_hi-primary_h_c, 0)**2 + s_h**2)
d_nu = sqrt(max(primary_nu-q_nu_lo, q_nu_hi-primary_nu, 0)**2 + s_nu**2)

h_c_lo = primary_h_c - d_h
h_c_hi = primary_h_c + d_h
nu_lo  = max(0.01, primary_nu - d_nu)
nu_hi  = primary_nu + d_nu.
```

Do not bootstrap individual ratios, combine all gaps as independent samples,
or reuse one target's RNG stream for another target.

### 6. Query predictions

For each query, evaluate the primary fit's cubic with its own `x_scale`, and
clip the resulting mean to `[0,1]`. The reference predictive standard error is

```text
0.008
+ 0.025 * min(1, abs(query_control-h_c) / max(primary_halfwidth,0.1))
+ 0.015 * min(1, (h_c_hi-h_c_lo) / max(primary_halfwidth,0.1)).
```

This value is finite, nonnegative, and at most `0.25`. Emit exactly one row for
every query and no others. Query predictions must come from the supplied case;
the private suite changes target curves and includes shuffled packets and
coordinate transformations.

## Output schemas and semantics

CSV files are UTF-8 with one header row, exactly the listed columns, one row
per required key, no duplicate keys, and finite numeric text (never `NaN` or
infinity). Emit at least 10 significant decimal digits for computed floats.
For every numeric key cell (`target`, `control`, or `halfwidth`), serialize the
canonical value so parsing and applying `round(float(text),10)` recovers that
exact canonical key; `format(value,".17g")` is a sufficient general choice and
is used by the reference. Numerical tolerances, rather than string equality,
are used for non-key values.

Row order is not graded after key matching, but deterministic reference order
is: realization and group keys lexicographically; transition targets ascending;
stability targets ascending, then `min_sizes` and `halfwidths` in JSON order;
queries in query-CSV order. This order is recommended for reproducibility.

`realization_stats.csv`:

```text
case_id,target,size,control,realization_id,n_ratios,mean_r
```

Exactly one row per packet/group-realization key. `case_id` equals the manifest
value; `n_ratios > 0`; `mean_r` is in `[0,1]`.

`packet_stats.csv`:

```text
case_id,target,size,control,n_realizations,n_ratios,mean_r,se_r
```

Exactly one row per observed canonical `(target,size,control)` key.
`n_realizations >= 2`, `n_ratios > 0`, and `se_r >= 0`.

`transition.csv`:

```text
case_id,target,h_c,nu,h_c_lo,h_c_hi,nu_lo,nu_hi,fit_score,stable
```

Exactly one row per observed target. Intervals contain their point estimates;
the point estimate satisfies `0.2 <= nu <= 4.0`, `nu_lo` is positive, and
`nu_hi <= 10`. Both `h_c` interval endpoints have absolute value at most
`4e6`. `fit_score` is in `[0,1]`; `stable` is the integer `0` or `1`.

`stability.csv`:

```text
case_id,target,min_size,halfwidth,h_c,nu,validation_rmse,n_groups,fit_ok
```

Exactly the target-by-min-size-by-halfwidth Cartesian product. Each `h_c` lies
within that target's observed control range, `0.2 <= nu <= 4.0`,
`validation_rmse >= 0`, `n_groups > 0`, and `fit_ok` is `0` or `1` (the
reference emits `1` on all guaranteed-valid inputs).

`predictions.csv`:

```text
query_id,mean_r,se_r
```

Exactly one row per input query ID. `mean_r` is in `[0,1]` and
`0 <= se_r <= 0.25`.

`claims.json` is a strict JSON object with exactly these keys and JSON types:

```json
{
  "schema_version": "spectral-scaling-claims/v1",
  "case_id": "<manifest case_id>",
  "case_token": "<manifest case_token>",
  "finite_size_crossover": true,
  "phase_direction": "mean_r_decreases_with_control",
  "n_realizations": 0,
  "n_groups": 0,
  "n_targets": 0,
  "low_control_mean_r": 0.0,
  "high_control_mean_r": 0.0
}
```

Here `n_realizations` is the packet/realization-row count, `n_groups` is the
unique canonical group count, and `n_targets` is the unique canonical target
count. For the two summaries, find the *global* minimum and maximum canonical
control among observed groups. Each summary is the unweighted arithmetic mean
of the group `mean_r` values present at that extreme, across available targets
and sizes. Missing edge groups are simply absent. Supplied cases satisfy
`low_control_mean_r > high_control_mean_r`. All counts and summaries must agree
with the CSV evidence, and the case ID and opaque token must be copied from the
current manifest.
The three counts are JSON integers (not Booleans); the two mean summaries are
finite JSON numbers (not Booleans or numeric strings). Serialize each computed
summary with at least 10 significant decimal digits, matching the CSV evidence
within numerical tolerance.

## Qualitative success criteria

A strong analyzer:

- reconstructs every realization and grouped statistic from raw packets;
- respects realization-level dependence and reports cluster-aware uncertainty;
- predicts unseen size/control points rather than memorizing a table;
- distinguishes an energy-dependent curve from one constant crossing;
- obtains a defensible scaling exponent rather than only interpolating a
  midpoint;
- reports the full requested stability sweep with meaningful diagnostics;
- preserves ID-aligned evidence and point estimates under packet/CSV row
  permutations and realization-ID bijections (finite-replicate bootstrap
  intervals need only remain behaviorally consistent after an ID relabel);
- is invariant within numerical tolerance under an applicable positive affine
  energy map, as defined below, applied consistently to raw levels, extrema,
  and shift energies;
- under `control' = a*control+b`, `a>0`, with every analysis halfwidth scaled
  by `a` and every transformed halfwidth still in `[0.4,1e6]`, maps `h_c` and
  its bounds by the same affine rule while preserving
  `nu`, mean predictions, ratio evidence, residual diagnostics, and uncertainty
  in the corresponding units;
- under `target' = 1-target`, `energy' = -energy`, swapped/negated extrema, and
  negated shift energies, preserves evidence and relabels all target-indexed
  results by the mirror map (bootstrap intervals are compared behaviorally);
- gives ID-aligned invariant results when packet/eigenvalue blocks are split
  into storage shards and losslessly rejoined in another shard order; and
- keeps all structured claims consistent with independently recomputed
  evidence.

Exact fresh cases, evaluator tolerances, score weights, pass thresholds, and
reference outputs remain private.

For the affine-control check, the evaluator starts from canonical control and
halfwidth values and chooses `a,b` so the transformed keys remain distinct and
canonicalization commutes with the stated map. It also guarantees, before and
after transformation, that every candidate observation row is separated from
each window boundary by more than `1e-8*max(1,halfwidth)`. Thus the check does
not turn on decimal-rounding or sharp-boundary accidents.

For the affine-energy check, the evaluator uses finite `a > 0` and finite `b`
in `E' = a*E+b` only when the transformed five-file case satisfies every input
bound above, including chunk containment, shift consistency, and the same
`S`, `M`, `2**20*ulp(M)`, retained-gap, and cutoff-margin predicate recomputed
in transformed coordinates. It verifies that the stable selected-index prefix
and the ascending order of retained levels correspond exactly before and after
the map, and that every recomputed retained ratio changes by at most `1e-10`.
Only such numerically resolved maps are in scope; arbitrary translations that
erase float64 gaps are not. Exact transform constants and evaluator comparison
tolerances remain private.

## Public validation

From this participant directory, run

```text
python software/validate_submission.py --submission <submission-root> --run-public
```

The validator checks the one-file package, executes it on the retired case
with a bounded subprocess, reconstructs the raw packet/group statistics,
checks exact key and stability-grid coverage, verifies claims against evidence,
and applies public scientific consistency checks. Passing it is necessary but
not sufficient for private evaluation. This public validator is a convenience
checker, not a security boundary for untrusted code; production evaluation
uses separate OS isolation in addition to the private runtime guard.
