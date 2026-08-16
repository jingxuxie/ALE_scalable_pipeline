# Disordered fixed-sector eigensystem audit

## Objective

Implement a reusable full-eigensystem analysis for finite periodic spin chains.
Your program will be run on fresh experiment directories.  It must construct
each fixed-magnetization Hamiltonian once, diagonalize it once, answer every
energy/subsystem query attached to that realization, aggregate by realization,
and issue evidence-linked finite-ensemble conclusions.

The scientific target is deliberately finite: for the supplied ensembles,
weak-disorder packets should generally have larger adjacent-gap ratios,
half-chain-like entanglement, and participation entropies than corresponding
strong-disorder packets.  Do **not** infer or claim a thermodynamic phase
transition or mobility edge.

Submit exactly one regular file:

```text
output/solution.py
```

It is invoked as:

```text
python solution.py --experiment EXPERIMENT_DIRECTORY --output RESULT_JSON
```

The evaluator uses unpublished experiment directories with the same schema but
new lengths, sectors, fields, energy targets, subsystem cuts, packet sizes,
record order, and identifiers.

## 1. Experiment schema

Each directory contains only `experiment.json`, a UTF-8 JSON object with:

- `schema_version`: `sector-audit-experiment/v1`;
- `experiment_id`: unique string;
- `records`: finite-realization records;
- `comparisons`: requested weak-versus-strong evidence comparisons.

Scored inputs contain at most 24 records, at most four queries per record, and
at most eight comparisons.  All identifiers are nonempty ASCII strings made
from letters, digits, `_`, `-`, and `.`, are at most 80 characters, and never
contain the reserved delimiter `::`.  `record_id` and `comparison_id` are
globally unique; `query_id` is unique within each record.  Each
`(condition_id,query_id)` combination denotes exactly one aggregate.

Each record has:

- `record_id`, `condition_id`: strings;
- `L`: integer site count, between 4 and 14;
- `n_up`: integer number of up spins, with `1 <= n_up < L`;
- `exchange`: positive finite exchange coefficient `J`;
- `fields`: `L` finite field values `h_i` in site order `0,...,L-1`;
- `queries`: two or more query objects.

Each query has:

- `query_id`;
- normalized target `epsilon` strictly between zero and one;
- integer `packet_size`, with
  `2 <= packet_size <= min(15,binomial(L,n_up)-2)`;
- integer `subsystem_start`, with `0 <= subsystem_start < L`;
- integer `subsystem_size`, with `1 <= subsystem_size < L`.

For a given `(condition_id, query_id)`, `L`, `n_up`, `exchange`, `epsilon`, and
the subsystem definition are identical across realizations, but `packet_size`
may differ.  A subsystem
contains the periodic contiguous sites

```text
subsystem_start, subsystem_start+1, ..., subsystem_start+subsystem_size-1
```

with indices reduced modulo `L`.

Each comparison has `comparison_id`, `weak_condition`, `strong_condition`, and
`query_id`.  The two referenced aggregate rows always exist and have identical
`L`, `n_up`, `exchange`, `epsilon`, `subsystem_start`, and `subsystem_size`;
only their realizations, fields, and packet sizes may differ.

Every scored Hamiltonian has a nonzero spectral width and simple eigenvalues at
`float64` resolution; all candidate adjacent gaps are strictly positive.  No
degenerate-eigenspace or `0/0` gap convention is therefore required.
Whenever a packet does not consume every interior eigenvalue, the distance from
the target to the first excluded state exceeds that to the last included state
by more than `1e-10*max(1,E_max-E_min)`.  Packet membership is therefore not
decided by an ill-conditioned cutoff tie.

`input/retired_experiment/` is a visible, permanently retired development
instance.  It is not used for private scoring.

## 2. Basis and Hamiltonian

Bit `i` represents site `i`; bit one has `S_i^z=+1/2` and bit zero has
`S_i^z=-1/2`.  Work in the basis of integers with exactly `n_up` set bits,
sorted in increasing integer order.

Use periodic boundary conditions and

```text
H = sum_i [ J S_i . S_(i+1) - h_i S_i^z ],   i+1 modulo L.
```

In the disclosed basis:

- the bond diagonal is `J * S_i^z * S_(i+1)^z`;
- unlike neighboring spins are simultaneously flipped with matrix element
  `J/2`;
- the field diagonal is `-h_i*S_i^z`.

The matrix is real symmetric.  A dense `float64` implementation is acceptable
and expected for these bounded sectors.  Diagonalize with `numpy.linalg.eigh`,
which returns eigenvalues in ascending order.  Cache the full eigensystem per
record and reuse it for all of that record's queries.

## 3. Reversed normalized energy and deterministic packets

Let ascending eigenvalues be `E[0],...,E[D-1]`, with `E_min=E[0]` and
`E_max=E[D-1]`.  This task uses the reversed normalization

```text
normalized(E) = (E - E_max) / (E_min - E_max)
target = E_max + epsilon * (E_min - E_max).
```

Thus `epsilon=0` corresponds to the spectral maximum and `epsilon=1` to the
minimum.

Only indices `1,...,D-2` are packet candidates, because each needs two adjacent
gaps.  Sort candidates by the tuple

```text
(abs(E[index] - target), E[index], index)
```

take the first `packet_size`, then sort those selected indices in ascending
integer order.  Their order after this final sort defines **zero-based**
`state_rank`, beginning at zero.

For a selected index `n`, compute

```text
delta_lower = E[n]   - E[n-1]
delta_upper = E[n+1] - E[n]
r = min(delta_lower,delta_upper) / max(delta_lower,delta_upper).
```

## 4. Eigenstate observables

Normalize every selected eigenvector in `float64` before computing observables.
Let `p_b = abs(c_b)^2` in the disclosed fixed-sector basis.

### Participation entropies

Use natural logarithms:

```text
S1 = -sum_(p_b>0) p_b * ln(p_b)
S2 = -ln(sum_b p_b^2).
```

### Contiguous-subsystem entanglement

The subsystem sites are taken in periodic traversal order beginning at
`subsystem_start`; complement sites are taken in increasing global-site order.
Compress the selected subsystem bits into a row integer and the complement bits
into a column integer.  Scatter the fixed-sector amplitudes into a zero-filled
coefficient matrix of shape

```text
(2**subsystem_size, 2**(L-subsystem_size)).
```

If its singular values are `s`, normalize `lambda=s**2` to sum to one and
compute the natural-log von Neumann entropy

```text
S_E = -sum_(lambda>1e-15) lambda * ln(lambda).
```

### Subsystem magnetization moments

For basis state `b`, define

```text
m_A(b) = number_of_up_spins_in_A - subsystem_size/2.
```

Report

```text
mean_mz = sum_b p_b*m_A(b)
variance_mz = sum_b p_b*m_A(b)^2 - mean_mz^2.
```

Roundoff-scale negative variances may be clipped to zero.

## 5. Realization-first aggregation

Create a state row for every selected state.  For each
`(condition_id,query_id)`, first average each numeric metric separately within
each `record_id`.  Then average those per-record means with equal realization
weight.  Do not weight a realization more heavily because it has a larger
packet.

For realization means `x_1,...,x_R`, report

```text
mean = sum(x_r)/R
sem  = sample_standard_deviation(x_r, ddof=1)/sqrt(R).
```

Use `sem=0` only when `R=1`.  `state_count` remains the actual total packet-row
count.

## 6. Required result JSON

The top-level object must contain exactly:

- `schema_version`: `sector-audit-result/v1`;
- `experiment_id` copied from the input;
- `state_rows`;
- `aggregate_rows`;
- `conclusions`.

Every number must be a finite JSON number.  Duplicate IDs or keys are invalid.

### State rows

One row per selected state, containing exactly:

```text
record_id, condition_id, query_id, state_rank, eigen_index,
eigenvalue, normalized_energy, gap_ratio, entanglement,
participation_s1, participation_s2,
subsystem_mz_mean, subsystem_mz_variance
```

Sort by `(record_id,query_id,state_rank)`.

### Aggregate rows

One row per `(condition_id,query_id)`, containing exactly:

```text
aggregate_id, condition_id, query_id, epsilon,
subsystem_start, subsystem_size, realization_count, state_count,
mean_gap_ratio, sem_gap_ratio,
mean_entanglement, sem_entanglement,
mean_participation_s1, sem_participation_s1,
mean_participation_s2, sem_participation_s2,
mean_subsystem_mz_mean, sem_subsystem_mz_mean,
mean_subsystem_mz_variance, sem_subsystem_mz_variance
```

`aggregate_id` is exactly `condition_id + "::" + query_id`.  Sort by
`(condition_id,query_id)`.

### Evidence-linked conclusions

Sort comparisons by `comparison_id`.  For every comparison, emit four rows in
metric order

```text
gap_ratio, entanglement, participation_s1, participation_s2.
```

Each row contains exactly:

```text
claim_id, metric, direction, positive_effect, effect,
weak_aggregate_id, strong_aggregate_id
```

Use:

```text
claim_id = comparison_id + "::" + metric
direction = "weak_greater_than_strong"
effect = weak mean - strong mean
positive_effect = (effect > 0)
```

The evaluator recomputes every conclusion from the aggregate evidence; it does
not trust self-reported claims.

## 7. Qualitative success criteria

- Hamiltonians respect the fixed sector, spin-one-half coefficients, and
  periodic bond.
- One eigensystem is reused for all energy and subsystem queries on a record.
- Reversed energy normalization and symmetric nearest-target packets are exact.
- Entanglement is a real-space Schmidt entropy, not computational-basis
  Shannon entropy.
- Participation and subsystem-magnetization observables use the disclosed
  natural-log and variance conventions.
- Aggregates give equal weight to realizations and SEM is clustered by
  realization.
- Conclusions are finite-ensemble statements linked to recomputable evidence.
- Equivalent `float64` implementations are accepted with elementwise scales of
  the form `max(absolute_tolerance, relative_tolerance*abs(reference))`; exact
  private tolerance values and score weights are withheld.  Exact source text
  or eigenvector signs are never graded.

## 8. Environment and limits

- Python 3.11 or newer; standard library plus `numpy==2.3.5` only.
- CPU only, at most 4 logical CPUs, 8 GiB RAM, and 20 minutes total.
- Network access and subprocess creation are disabled during evaluation.
- `solution.py` may read only its supplied experiment directory and write only
  the requested result path.
- `solution.py` must be at most 200,000 bytes.  Each result JSON must be at most
  8 MiB.
- Pickle, object arrays, links, hard links, extra submission files, and stale
  precomputed result files are not accepted.

Run `software/validate_submission.py output` for public structural validation.
It contains no hidden values and does not certify scientific correctness.
