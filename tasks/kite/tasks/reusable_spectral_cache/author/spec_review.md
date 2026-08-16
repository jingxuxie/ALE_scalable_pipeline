# Paper-blind specification review

## Review conditions

- Reviewer: fresh delegated agent with no inherited conversation turns
- Allowed projection: `participant/` only
- Source paper, repository, evaluator, references, author files, and web: not accessed
- Date: 2026-08-15
- Status: PASS

## Restatement

For each of three sparse Hermitian systems, reconstruct the matrix, use the
supplied spectral bounds to scale it, and compute 384 raw Chebyshev moments for
each of four explicit probes. Preserve the probe-resolved cache, take the
equal-weight probe mean only when answering 21 public retarded, advanced, and
spectral-density queries, and report recomputable scaling and cache diagnostics.
The submitted moments must support additional query tuples without another
matrix recurrence.

## Solution-critical decisions found public

The review found the following fully specified: zero-based indexing; upper
triangle and Hermitian conjugation; affine center and half-width; fixed
unnormalized unit-modulus probes; conjugate inner product; exactly one division
by system dimension; recurrence initialization and factor; orders 0 through
383; probe-resolved storage and equal-weight response mean; prefix meaning;
retarded/advanced sign; square-root disk branch; stable `q`; the order-zero and
higher-order factors; physical `1/a`; density sign; all output schemas; numeric
dtypes; file caps; environment; and qualitative success criteria.

## Public asset audit

- Manifest order and dimensions: `sys_alpha` 311, `sys_beta` 529, `sys_gamma` 769.
- All nine manifest SHA-256 digests matched the visible files.
- Onsite indices were complete and unique.
- Edge counts were 797, 1174, and 1973; all were unique canonical `i < j` rows.
- Every probe ID 0 through 3 covered every site exactly once with unit-modulus entries.
- Scaled Gershgorin radii were about 0.822715, 0.826277, and 0.824713.
- All 21 query IDs were unique and within the disclosed energy, eta, and prefix domains.

## Findings and resolution

The initial text implied, but did not literally state, that the NPZ probe-axis
index equals numeric `probe_id`. `TASK.md` now states that mapping explicitly.
Equivalent floating spellings of copied query coordinates remain intentionally
valid because parsed values, not bytes, are authoritative. The public validator
is correctly described as a structural helper rather than a correctness oracle.

No material ambiguity, missing file, or hidden source dependency remains.
