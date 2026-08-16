# Spinful wave-packet dynamics on a disordered open lattice

## Objective

Reconstruct and compare time-resolved spinful wave-packet dynamics for six
explicit realizations of a finite two-dimensional tight-binding system.  Build
each Hermitian Hamiltonian, validate its supplied affine spectral scaling,
construct a reusable Chebyshev-vector basis, contract that basis at the public
times, aggregate paired disorder ensembles, and report the comparison in
machine-readable form.

The deliverable is data, not executable code.  The reusable basis is essential:
evaluation may contract it at additional undisclosed times inside the declared
time interval.  Values hard-coded only at the public times are therefore not a
solution.

## Provided files

All paths below are relative to this participant package.

- `input/config.json`: global constants, basis order, state parameters, index
  conventions, instance ID, and allowed time interval.
- `input/sites.csv`: site IDs and Cartesian coordinates in authoritative
  site-major row order.
- `input/bonds.csv`: one oriented record for every undirected nearest-neighbor
  bond.  There are no periodic wrap bonds.
- `input/realizations.csv`: realization ID, disorder model, and supplied
  rescaling center and half-width.
- `input/onsite.csv`: explicit scalar and Ising onsite fields for every
  realization/site pair.
- `input/times.csv`: public contraction times.
- `software/bessel.py`: a NumPy-plus-standard-library implementation of the
  required integer-order Bessel sequence.  You may use it unchanged or replace
  it with a numerically equivalent implementation.

The `scalar_0`/`scalar_ising_0` pairs (and likewise pairs 1 and 2) share the
same scalar field.  This pairing makes the scalar-versus-Ising comparison
controlled rather than a comparison of unrelated random draws.

## Scientific conventions

Let the row index of site `i` in `sites.csv` be `r(i)`.  The vector index is
site-major with spin order `(up, down)`:

```text
index(i, up)   = 2*r(i)
index(i, down) = 2*r(i) + 1
```

Use the Pauli matrices

```text
I       = [[1, 0], [0, 1]]
sigma_x = [[0, 1], [1, 0]]
sigma_y = [[0, -i], [i, 0]]
sigma_z = [[1, 0], [0, -1]].
```

For one realization, the onsite block at site `i` is

```text
H_ii = u_i I + m_z,i sigma_z.
```

For each oriented `bonds.csv` record from site `i` to site `j`, compute
`dx = x_j - x_i` and `dy = y_j - y_i`, then set

```text
H_ij = exp(+i*phi_ij) * [-t I + i*lambda*(dy*sigma_x - dx*sigma_y)]
H_ji = H_ij dagger.
```

Insert each listed block once.  Unlisted off-diagonal blocks are zero.  This is
an open-boundary finite system.  Verify Hermiticity numerically before using a
Hamiltonian.

For each realization, `realizations.csv` supplies `center = c` and positive
`half_width = a`.  Compute the extreme eigenvalues of the assembled `H` and
verify both lie strictly inside the open interval `(c-a, c+a)`.  Record

```text
scaled_radius = max(abs((E_min-c)/a), abs((E_max-c)/a)).
```

It should not exceed `rho_limit` apart from floating-point roundoff.  Use the
supplied values, without re-fitting them, to form

```text
H_tilde = (H - c I) / a.
```

The initial spinor at site coordinates `(x,y)` is

```text
g(x,y) = exp(-((x-x0)^2 + (y-y0)^2)/(4*sigma^2))
          * exp(i*(kx*x + ky*y))
chi    = [cos(theta/2), exp(i*alpha)*sin(theta/2)]^T
psi0_i = g(x_i,y_i) * chi.
```

Normalize the complete `2*N` vector once so that `psi0 dagger psi0 = 1`.
Do not normalize individual sites and do not renormalize later basis vectors.

For every realization construct exactly `M = basis_order` vectors:

```text
q_0 = psi0
q_1 = H_tilde q_0
q_n = 2 H_tilde q_(n-1) - q_(n-2),  n = 2,...,M-1.
```

At time `tau`, contract the truncated basis as

```text
psi(tau) = exp(-i*c*tau) * [
    J_0(a*tau) q_0
    + 2 * sum_{n=1}^{M-1} (-i)^n J_n(a*tau) q_n
].
```

This truncated contraction, rather than a separately evaluated matrix
exponential, defines the required trajectories.

Energies use the same arbitrary units as the Hamiltonian inputs, `hbar = 1`,
and `tau` is therefore in the corresponding inverse-energy time unit.  The spin
components below are raw Pauli expectation values, not values multiplied by
`hbar/2`.

For site spinor `(alpha_i, beta_i)`, define

```text
p_i      = |alpha_i|^2 + |beta_i|^2
norm     = sum_i p_i
sx       = sum_i 2 Re(conj(alpha_i)*beta_i)
sy       = sum_i 2 Im(conj(alpha_i)*beta_i)
sz       = sum_i (|alpha_i|^2 - |beta_i|^2)
mean_x   = sum_i x_i p_i / norm
mean_y   = sum_i y_i p_i / norm
second_x = sum_i x_i^2 p_i / norm
second_y = sum_i y_i^2 p_i / norm
second_xy= sum_i x_i y_i p_i / norm.
```

Use double precision for construction and output calculations.

## Required output

Place exactly these four regular files at the root of the submission directory.
Do not use symlinks, object arrays, pickles, or extra executable files.

### `basis.npz`

A NumPy NPZ archive loadable with `numpy.load(..., allow_pickle=False)` and
containing exactly:

- `basis`: complex128, shape `(R, M, N, 2)`, in `realizations.csv`, Chebyshev
  order, `sites.csv`, then `(up,down)` order.
- `realization_ids`: one-dimensional Unicode array of length `R`, exactly in
  `realizations.csv` row order.
- `site_ids`: one-dimensional Unicode array of length `N`, exactly in
  `sites.csv` row order.
- `orders`: int64 array equal to `arange(M)`.
- `instance_id`: zero-dimensional Unicode array equal to the value in
  `config.json`.

### `trajectories.csv`

Exactly one row for every realization/public-time pair.  Row order is free;
keys must be unique.  Header:

```text
realization_id,disorder_model,time,norm,sx,sy,sz,mean_x,mean_y,second_x,second_y,second_xy
```

### `ensemble.csv`

For each `disorder_model` and public time, aggregate the three realization rows.
Use arithmetic means and population standard deviations (`ddof=0`) for every
numeric observable.  Row order is free.  Header:

```text
disorder_model,time,count,norm_mean,norm_std,sx_mean,sx_std,sy_mean,sy_std,sz_mean,sz_std,mean_x_mean,mean_x_std,mean_y_mean,mean_y_std,second_x_mean,second_x_std,second_y_mean,second_y_std,second_xy_mean,second_xy_std
```

`count` is the integer number of realizations in the model.

### `analysis.json`

UTF-8 JSON with no non-finite extensions and exactly these top-level members:

- `schema_version`: `spinful-packet-analysis/v1`.
- `instance_id`: the public instance ID.
- `basis_order`: integer `M`.
- `bounds`: an array containing exactly one object per realization, in
  realization order, with exactly the fields
  `realization_id`, `eigenvalue_min`, `eigenvalue_max`, `scaled_radius`, and
  Boolean `within_declared_interval`.
- `contrasts`: an array containing exactly one object per public time, in
  ascending order, with exactly the fields `time`,
  `scalar_sz_mean`, `scalar_ising_sz_mean`, `delta_sz` (Ising minus scalar),
  `scalar_spread_mean`, `scalar_ising_spread_mean`, and `delta_spread` (Ising
  minus scalar).  For a realization define total spatial spread as
  `(second_x-mean_x^2) + (second_y-mean_y^2)` and then average across its model.
- `conclusion`: an object with exactly the fields `comparison_time` (equal to
  the last public time), `smaller_final_abs_sz_model`, and
  `greater_spreading_model`.  `smaller_final_abs_sz_model` is the model with
  smaller absolute model-mean `sz` at the comparison time; it is a literal
  polarization comparison, not a claim about a fitted relaxation lifetime.
  Spreading is greater for the larger model-mean total spread.  Allowed model
  strings are `scalar` and `scalar_ising`; exact ties use `tie`.

## Constraints and evaluation

- Python 3.11+ and `numpy==2.3.5` are available; standard-library tools are allowed.
- CPU only, at most 4 CPU cores, 4 GiB RAM, 10 minutes wall time, and 20 MiB of
  submission storage.
- Network access is disabled.  The source paper, any source repository, private
  evaluator files, and undeclared external data are not available or needed.
- Required artifacts must parse, be complete and finite, respect the schemas,
  and carry the current instance ID.
- Scientific evaluation checks the reusable recurrence basis, contracts it at
  additional times, recomputes public observables, recomputes ensemble
  aggregation, and checks the structured comparison against the numeric
  evidence.  Numerically equivalent double-precision results are accepted with
  absolute and relative tolerances; exact file bytes and row order are not
  graded.
