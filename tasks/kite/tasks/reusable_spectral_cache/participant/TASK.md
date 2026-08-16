# Reusable Chebyshev spectral cache

## Objective

Build a reusable, energy-independent Chebyshev moment cache for three supplied
sparse Hermitian systems. Then demonstrate that the same cache answers the
supplied retarded, advanced, and spectral-density queries at several energies,
broadenings, and truncation prefixes without rerunning the matrix recurrence.

Your submission is data only. Produce exactly these files in one output
directory:

```text
moments.npz
public_response.csv
diagnostics.json
```

The held-out evaluation uses the submitted moments at additional energies,
broadenings, and prefixes. No submitted program is executed.

## Provided files

`input/manifest.json` lists the systems, dimensions, common number of probes,
common number of moments, conservative spectral bounds, relative input paths,
and SHA-256 digests. `input/public_queries.csv` contains the response rows you
must materialize.

For each system:

- `onsite.csv` has columns `index,value` and defines the real diagonal.
- `edges.csv` has columns `i,j,value_real,value_imag`. Every row has `i < j`
  and defines `H[i,j] = value_real + i*value_imag` and
  `H[j,i] = conjugate(H[i,j])`. No reverse row is present.
- `probes.csv` has columns `probe_id,index,value_real,value_imag`. It contains
  every entry of every probe exactly once.

Indices are zero-based. Values use the energy unit named by the manifest.

## Required numerical convention

For a system of dimension `N` with supplied bounds `L < U`, define

```text
a = (U - L) / 2
b = (U + L) / 2
A = (H - b I) / a
```

The bounds are deliberately conservative. The spectrum of `A` is strictly
inside `[-1, 1]`; the diagnostics below check a stronger public Gershgorin
certificate.

Use the probes exactly as stored. They have unit-modulus entries but are not
unit-norm vectors. Do not normalize them. For probe `p`, cache the raw moments

```text
T_0(A) xi_p = xi_p
T_1(A) xi_p = A xi_p
T_n(A) xi_p = 2 A T_(n-1)(A) xi_p - T_(n-2)(A) xi_p

tau[p,n] = xi_p^* T_n(A) xi_p / N
```

Here `*` means conjugate transpose. Divide by `N` exactly once. The requested
orders are `n = 0,...,383`; a `prefix` of `m` means orders `0,...,m-1`.
In particular, `tau[p,0] = 1` for every supplied probe. Retain one row per
probe; do not replace the four rows by their mean. The NPZ probe-axis index is
the integer `probe_id` from `probes.csv` (`0,1,2,3`).

### Finite resolvent contraction

Let `bar_tau[n]` be the equal-weight arithmetic mean of `tau[p,n]` over the
four supplied probes. For a query with `sigma=+1` for `GR` or `DOS`, and
`sigma=-1` for `GA`, define

```text
z = (E - b + i sigma eta) / a,     eta > 0.
```

Of the two roots of `s^2 = z^2 - 1`, choose `s` so that

```text
q = z - s
abs(q) < 1.
```

For stable arithmetic, after selecting `s` compute `q = 1 / (z + s)`.
Do not use an unqualified principal `sqrt(z*z - 1)`: its sign is wrong on part
of the complex plane. For the upper half-plane an equivalent construction is
`s = principal_sqrt(z - 1) * principal_sqrt(z + 1)`; the disk condition above
is authoritative for both signs of `sigma`.

The exact finite-prefix contraction required by this task is

```text
R_m(E, eta, sigma) =
    [bar_tau[0] + 2 sum(n=1..m-1, q^n bar_tau[n])] / (a s).
```

This is the order-`m` Chebyshev reconstruction, not the infinite-order or exact
finite-matrix resolvent. `GR` is `R_m(...,+1)` and `GA` is `R_m(...,-1)`.
For a `DOS` row write

```text
rho_m(E,eta) = -imag(R_m(E,eta,+1)) / pi
```

as the real output value and write zero as its imaginary value. This is a
fixed-probe trace estimate, not an exact density of states.

The normalization above is complete and overrides other conventions you may
know. The cached `tau` values are raw moments. The order-zero term is used once
and every higher-order term receives the explicit factor `2` in the
contraction. Do not absorb `(2 - delta[n,0])`, a kernel, the factor `1/a`, or
the probe average into `tau`.

Held-out response queries use the supplied systems, prefixes from 1 through
384, energies inside the supplied spectral interval, and `eta/a` between
0.025 and 0.12. Exact held-out tuples and scoring thresholds are not public.

## Output schemas

### `moments.npz`

Create a NumPy NPZ archive that loads with `allow_pickle=False`. It must contain
exactly these arrays:

| Key | Dtype and shape | Value |
| --- | --- | --- |
| `schema_version` | scalar Unicode/bytes | `spectral-moments/v1` |
| `system_ids` | Unicode/bytes, `(3,)` | manifest order |
| `dimensions` | integer, `(3,)` | manifest dimensions |
| `moment_count` | scalar integer | `384` |
| `probe_count` | scalar integer | `4` |
| `tau_real` | `float64`, `(3,4,384)` | real parts of raw moments |
| `tau_imag` | `float64`, `(3,4,384)` | imaginary parts of raw moments |

All values must be finite. Hermiticity makes the exact moments real, but retain
and report the computed imaginary roundoff rather than silently changing the
definition.

### `public_response.csv`

Use this exact header and the same row order as `input/public_queries.csv`:

```text
query_id,system_id,prefix,kind,energy,eta,value_real,value_imag
```

Copy the six query fields without changing their parsed values and append the
finite double-precision result. Every public query appears exactly once.

### `diagnostics.json`

The top-level object has exactly:

```json
{
  "schema_version": "spectral-diagnostics/v1",
  "moment_count": 384,
  "probe_count": 4,
  "public_query_count": 21,
  "systems": []
}
```

`systems` follows manifest order. Each record has exactly:

```json
{
  "system_id": "...",
  "dimension": 0,
  "tau0_max_abs_error": 0.0,
  "max_abs_imaginary_moment": 0.0,
  "max_abs_moment": 0.0,
  "scaled_gershgorin_radius": 0.0
}
```

The first three floating fields are respectively
`max_p(abs(tau[p,0]-1))`, `max_(p,n)(abs(imag(tau[p,n])))`, and
`max_(p,n)(abs(tau[p,n]))` for that system. To compute the final field, start
each site `i` at `abs((onsite[i]-b)/a)`, add `abs(H[i,j])/a` to both incident
sites for every undirected edge, and report the maximum site total. All numeric
fields must be finite and non-negative. These values are recomputed during
evaluation; they are not trusted self-reports.

## Qualitative success criteria

- The cache follows the disclosed affine scaling, Hermitian edge convention,
  conjugate inner product, and two-step Chebyshev recurrence.
- It preserves all four probe-resolved raw moment sequences through order 383.
- The same cache gives branch-stable, unit-consistent responses for different
  energies, broadenings, sectors, and prefixes.
- `tau[p,0]` is one, imaginary moment roundoff is small, moments remain bounded
  under the supplied spectral certificate, and the public sidecars agree with
  the submitted cache.
- Numerically equivalent double-precision implementations are accepted with
  absolute and relative tolerances; byte identity is not required.

## Environment and limits

- Python 3.11 or newer with `numpy==2.3.5`; the standard library is available.
- CPU only, at most 4 logical CPUs, 8 GiB RAM, and 20 minutes wall time.
- Network access is disabled. No additional packages are required or allowed.
- Output total is at most 3 MiB. Individual caps are 2,000,000 bytes for NPZ,
  500,000 bytes for CSV, and 64,000 bytes for JSON.
- The output directory must contain only the three regular files above. Links,
  executable submissions, pickled/object arrays, and additional files are
  rejected.

`software/validate_submission.py` performs public structural checks. It does
not contain reference values or certify scientific correctness.
