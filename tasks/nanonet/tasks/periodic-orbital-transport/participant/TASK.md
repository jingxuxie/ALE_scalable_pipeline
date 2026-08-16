# Periodic orbital Hamiltonian and open-boundary transport

## Objective

Implement a reproducible, spinless tight-binding workflow for a one-dimensional
periodic structure described by JSON. Starting from site coordinates, orbital
bases, onsite energies, and two-center hopping parameters, you must:

1. assemble the intra-cell and forward inter-cell Hamiltonians;
2. compute phase-resolved periodic energy bands;
3. construct a finite, cell-dependent device Hamiltonian;
4. solve the retarded surface problem for its two semi-infinite leads; and
5. compute contact self-energies, total and cell-resolved density of states,
   and coherent two-terminal transmission.

Your submission is an executable Python program plus structured numerical
artifacts. Outputs are evaluated from their numerical behavior, not from source
code similarity or self-reported claims.

## Provided files

| Path | Description |
| --- | --- |
| `input/schema.json` | JSON Schema for an input instance. Cross-field semantic constraints are listed below. |
| `input/public_scalar_diatomic.json` | Small scalar-orbital example for exercising the complete file and CLI contract. |
| `input/public_rotated_multispecies.json` | Rotated multi-species `s`/`sp` example for checking directional hopping and basis handling. |
| `software/io_utils.py` | Optional safe JSON/NPZ, validation, atomic-write, and hashing helpers. It contains no scientific implementation. |
| `software/solution.py` | Command-line starter stub. Replace its TODO with your implementation and submit it as `output/solution.py`. |

The evaluator supplies the instance path as the `--input` argument. Do not
assume a particular input filename or working directory.

## Input contract

An input is a UTF-8 JSON object with these fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Input contract version; exactly `periodic-orbital-device/v1`. |
| `model_id` | Opaque instance identifier. Preserve it exactly in diagnostics. |
| `lattice_vector` | Three-component translation vector `a` from cell 0 to cell +1. |
| `neighbor_cutoff` | Positive distance cutoff, in the same units as positions. |
| `species` | Mapping from species name to its orbital list and onsite energies. |
| `sites` | Nonempty ordered list of `{id, species, position}` records for cell 0. |
| `hoppings` | Mapping from an unordered species-pair key to four real hopping integrals. |
| `phase_grid` | Dimensionless Bloch phases `theta`, in the order to be evaluated. |
| `energy_grid` | Real energies `E`, in the order to be evaluated. |
| `eta` | Strictly positive retarded broadening; use `z = E + i eta`. |
| `device` | Number of cells, cell/site potentials, internal bond scales, and contact scales. |

Each species has exactly one of these orbital lists:

```text
["s"]
["s", "px", "py", "pz"]
```

Its `onsite` mapping has exactly the same keys. Every site species must exist in
`species`, site IDs are unique, and `lattice_vector` must have nonzero norm.

A hopping key for species `A` and `B` is
`min(A, B) + "|" + max(A, B)`, where the minimum and maximum use ordinary
case-sensitive lexicographic string order. Every species pair encountered by
the neighbor enumeration below is present. Extra unused pair records may be
ignored. Each record contains the finite real values `ss_sigma`, `sp_sigma`,
`pp_sigma`, and `pp_pi`.

For `C = device.cells` and `S = len(sites)`:

- `site_potential` has shape `(C, S)`;
- `bond_scale` has length `C - 1`;
- `contact_scale_left` and `contact_scale_right` are strictly positive.

All numeric input values are finite. Phase and energy grids need not be sorted
and may contain repeated values; preserve their given order.

The evaluator uses only instances inside this published domain:

- `1 <= len(species) <= 8`, `1 <= len(sites) <= 8`, and consequently
  `1 <= N <= 32`;
- `1 <= len(phase_grid) <= 64`, `1 <= len(energy_grid) <= 64`, and
  `1 <= device.cells <= 10`;
- every Cartesian coordinate and lattice-vector component has absolute value
  at most `1000`, and `neighbor_cutoff <= 1000`;
- phases, energies, onsite values, hopping integrals, and site potentials have
  absolute value at most `100`;
- bond scales have absolute value at most `10`, contact scales are in `(0,10]`,
  and `1e-6 <= eta <= 10`.

The JSON file is at most 64 MiB. Cross-field dimensions must still match the
rules above; a schema maximum is not permission to pad an array with unused
entries. JSON Schema treats an exactly integral number such as `4.0` as an
integer, and the optional helper follows that convention for `device.cells`.

## Basis convention

Let `N` be the number of orbitals in one cell. Construct the basis in strict
site-major order:

```text
for site in sites, in JSON list order:
    for orbital in species[site.species].orbitals, in JSON list order:
        append (site, orbital)
```

All matrix indices below refer to this order. The site indices are zero-based
JSON list positions, not values derived from site IDs.

## Neighbor enumeration and hopping blocks

Only two image offsets are enumerated: the same cell and cell +1. A pair is a
neighbor when

```text
0 < distance <= neighbor_cutoff + 1e-12
```

The additive `1e-12` is in the coordinate units of the input and is part of the
contract.

For a row site `i` in cell 0 and a column site `j` in an image translated by
`R`, define

```text
q = position[j] + R - position[i]
d = ||q||_2
u = q / d = (u_x, u_y, u_z)
```

Use `R = (0, 0, 0)` for same-cell pairs and `R = lattice_vector` for +1-image
pairs. Exclude zero-distance pairs.

For same-cell interactions, enumerate each unordered site pair exactly once as
`i < j`. For +1-image interactions, enumerate every ordered `(i, j)`, including
`i == j`. Do not separately enumerate a -1 image.

For a neighbor, select its unordered species-pair parameter record and form the
real row-site-to-column-site hopping block `T`. With
`Vss = ss_sigma`, `Vsp = sp_sigma`, `Vpps = pp_sigma`, and
`Vppp = pp_pi`, its elements are:

```text
T[s, s]       = Vss
T[s, p_a]     = +u_a Vsp
T[p_a, s]     = -u_a Vsp
T[p_a, p_b]   = u_a u_b Vpps + (delta_ab - u_a u_b) Vppp
```

Here `a,b` are `x,y,z`, matching `px,py,pz`, and `delta_ab` is the Kronecker
delta. Use only rows and columns that exist for the two species. The signs are
defined by the row-to-column direction `u`; species-name ordering does not
change them.

## Periodic Hamiltonian

Construct two `(N, N)` matrices:

- `H0` starts with each orbital's onsite energy on its diagonal. For every
  included same-cell pair, add `T` to the `(i,j)` site block and `T.T` to the
  `(j,i)` block.
- `H1` starts at zero. For every included ordered +1-image pair, add `T` to the
  block whose rows are site `i` in cell 0 and columns are site `j` in cell +1.
  Do not symmetrize `H1`.

If multiple enumerated contributions target one matrix element, add them.
There is no overlap matrix and no other interaction term.

For every supplied phase, use

```text
H(theta) = H0 + H1 exp(+i theta) + H1^H exp(-i theta)
```

and report its `N` eigenvalues in nondecreasing order. (`H1` is real under this
input contract, so `H1^H` equals `H1.T`.)

## Finite device

The device basis is cell-major, with the complete one-cell basis repeated for
cells `c = 0, ..., C-1`. Its dimension is `D = C N`.

Build `HD` as follows:

1. Put a copy of `H0` on every diagonal cell block.
2. For each cell `c` and site `i`, add `site_potential[c][i]` to every diagonal
   orbital belonging to site `i` in that cell.
3. For each internal bond `c`, put `bond_scale[c] * H1` in block `(c,c+1)` and
   its Hermitian transpose in block `(c+1,c)`.

There are no other device couplings. The semi-infinite leads use the unmodified
periodic `H0` and `H1`; device potentials and internal bond scales do not alter
the leads.

## Retarded lead surfaces and contacts

Use the following outward lead couplings and device-to-surface contact
couplings:

```text
B_left  = H1^H
B_right = H1
C_left  = contact_scale_left  * H1^H
C_right = contact_scale_right * H1
```

For each `z = E + i eta`, obtain the causal retarded solution of the nonlinear
surface Dyson equation separately for each lead:

```text
g = inverse(z I_N - H0 - B g B^H)
```

You may use any numerically stable algorithm that selects the retarded branch.
Do not replace `eta` with another broadening. Define the contact self-energy
and broadening matrix by

```text
Sigma = C g C^H
Gamma = i (Sigma - Sigma^H)
```

The required `sigma_left` and `sigma_right` arrays contain these contact
self-energies, not the surface Green functions and not `B g B^H` unless the
corresponding contact happens to equal `B`.

Embed `Sigma_left` in the first device-cell block and `Sigma_right` in the last
device-cell block. If `C == 1`, both are added to that same block. Then compute

```text
G = inverse(z I_D - HD - embedded(Sigma_left) - embedded(Sigma_right))
```

Let `G_1N` be the `(N,N)` block with rows in the first device cell and columns
in the last device cell. Report the spinless observables

```text
DOS_total(E) = -Im(trace(G)) / pi
LDOS_cell(E,c) = -Im(trace(G[c,c])) / pi
T(E) = Re(trace(Gamma_left G_1N Gamma_right G_1N^H))
```

Do not apply spin degeneracy, normalize by the number of orbitals or cells, or
clip the reported values. Small negative roundoff is handled numerically by the
evaluator.

## Required entry point

Place your completed, self-contained entry point at `output/solution.py`. It is
invoked exactly as:

```text
python output/solution.py --input INPUT.json --output OUTPUT_DIR
```

The program must create `OUTPUT_DIR` if needed and write the four data
artifacts below directly inside it. It must work when the input and output paths
are absolute, contain spaces, and are outside the current working directory.
It must not require network access or files other than the input, its submitted
Python source, the Python standard library, and NumPy.

## Required outputs

Let `P = len(phase_grid)`, `K = len(energy_grid)`, `S = len(sites)`,
`N = basis_size`, `C = device.cells`, and `D = C N`.

Each NPZ must contain exactly the listed keys, with no object arrays or pickled
data. Arrays must have the exact NumPy dtype shown and be C-contiguous before
serialization. Matrix axes are always `(row, column)`, and grid axes preserve
input order.

### `OUTPUT_DIR/hamiltonian.npz`

| Key | Dtype | Shape | Meaning |
| --- | --- | --- | --- |
| `h0` | `complex128` | `(N, N)` | Intra-cell Hamiltonian `H0`. |
| `h1` | `complex128` | `(N, N)` | Forward cell-0-to-cell-+1 Hamiltonian `H1`. |
| `basis_site` | `int64` | `(N,)` | Zero-based input site index for each basis orbital. |

### `OUTPUT_DIR/self_energies.npz`

| Key | Dtype | Shape | Meaning |
| --- | --- | --- | --- |
| `energies` | `float64` | `(K,)` | Exact `energy_grid` values in input order. |
| `sigma_left` | `complex128` | `(K, N, N)` | Left contact self-energy, indexed by energy then row/column. |
| `sigma_right` | `complex128` | `(K, N, N)` | Right contact self-energy, indexed by energy then row/column. |

### `OUTPUT_DIR/spectra.npz`

| Key | Dtype | Shape | Meaning |
| --- | --- | --- | --- |
| `phases` | `float64` | `(P,)` | Exact `phase_grid` values in input order. |
| `bands` | `float64` | `(P, N)` | Ascending eigenvalues for each phase. |
| `energies` | `float64` | `(K,)` | Exact `energy_grid` values in input order. |
| `dos_total` | `float64` | `(K,)` | Spinless total device DOS. |
| `ldos_cells` | `float64` | `(K, C)` | Spinless cell-resolved LDOS, energy first. |
| `transmission` | `float64` | `(K,)` | Spinless Caroli transmission. |

### `OUTPUT_DIR/diagnostics.json`

Write a UTF-8 JSON object with exactly these fields. JSON numbers must be
finite; arrays and NumPy scalar encodings are not accepted in this file.

| Field | Type | Definition |
| --- | --- | --- |
| `schema_version` | string | Exactly `periodic-orbital-transport-output/v1`. |
| `model_id` | string | Exact input `model_id`. |
| `input_sha256` | string | Lowercase SHA-256 hex digest of the raw input file bytes. |
| `basis_size` | integer | `N`. |
| `device_cells` | integer | `C`. |
| `max_surface_residual` | number | Maximum normalized lead surface-equation residual defined below. |
| `max_hermiticity_residual` | number | Maximum normalized `H0`/`HD` Hermiticity residual defined below. |

For each energy and lead, with
`A = z I_N - H0 - B g B^H`, define

```text
r_surface = ||A g - I_N||_F /
            max(||I_N||_F, ||A||_F ||g||_F)
```

`max_surface_residual` is the maximum of `r_surface` over all energies and both
leads. Compute it from the same surface solutions used for the submitted
self-energies.

Define

```text
r0 = ||H0 - H0^H||_F / max(1, ||H0||_F)
rD = ||HD - HD^H||_F / max(1, ||HD||_F)
max_hermiticity_residual = max(r0, rD)
```

All norms here are Frobenius norms. Diagnostics are evidence and must agree
with the submitted matrices and spectra; the evaluator independently
recomputes scientific checks.

The required submission source remains at `output/solution.py`. The data output
directory may be cleared between runs, so do not depend on stale artifacts.

## Public success criteria

Evaluation emphasizes the following qualitative dimensions:

- correct basis ordering, inclusive cutoff handling, signed directional
  hopping blocks, and `H0`/`H1` orientation;
- accurate periodic bands, retarded contact self-energies, DOS/LDOS, and
  transmission across held-out geometries and device parameters;
- robustness to rigidly rotated geometries, reordered site lists, renamed or
  permuted species combinations, and multi-cell heterostructure potentials;
- causal and numerically converged surface solutions, Hermitian Hamiltonians,
  positive-semidefinite broadening matrices up to numerical roundoff, and small
  surface/Dyson residuals;
- consistency among intermediate Hamiltonians, self-energies, final spectra,
  diagnostics, and identities such as `sum_c LDOS_cell(E,c) = DOS_total(E)`;
- deterministic, finite, schema-valid outputs within the resource limits.

Additional evaluation instances and their reference results are not part of
the public package.

Numeric behavior is compared with combined absolute and relative tolerances
calibrated against independent double-precision implementations. This does not
change the formulas, schemas, or qualitative success criteria above.

## Environment and limits

- Python: 3.11 or newer
- Available numerical package: NumPy 1.26 through 2.x
- CPU: at most 4 cores
- GPU: unavailable
- Memory: 8 GB
- Wall time: 120 seconds per instance and 30 minutes for the complete evaluator invocation
- Network: disabled
- Input JSON: at most 64 MiB
- Submitted `output/solution.py`: at most 200 KiB
- Combined stdout and stderr: at most 1 MiB per instance
- Generated artifacts: at most 50 MiB over the complete evaluator invocation

The solution must be cross-platform and must not rely on shell-specific
commands, native compilation, SciPy, external executables, or nondeterministic
parallel reductions.

## Constraints

- Treat all input labels and IDs as opaque data; do not special-case known
  examples or hard-code grid values.
- Do not read files other than the declared input and submitted Python source.
- Use one Python process; do not spawn subprocesses or use multiprocessing.
- Do not emit pickle, object-dtype arrays, executable binary payloads, symlinks,
  or files outside the requested output directory.
- Reject malformed input clearly rather than silently guessing a missing
  convention.
- Use stable numerical linear algebra and the supplied positive `eta`; singular
  zero-broadening limits are outside the task.

## Reproducibility

The workflow is deterministic. If your chosen solver has optional random
initialization, fix and document the seed in `output/solution.py`; randomness is
not needed. Re-running the entry point on identical raw input bytes must produce
numerically identical parsed arrays and diagnostics.
