# Scalable local binary noise model

## Objective

Implement a deterministic program that reconstructs a normalized binary joint
model from independently sampled, overlapping local count tables on a disclosed
junction tree. Use the model to answer arbitrary partial-assignment probability
queries and to rank validation parity interactions that the local model fails to
explain.

The same program is run on unseen instances. A full table over all `2**n`
binary states cannot fit the resource contract; inference must scale with the
disclosed local width. The public instance already has 47 variables.

Submit one regular file named `solution.py`. The evaluator invokes it as

```text
python -B solution.py --input <input-directory> --output <new-empty-directory>
```

Your program must create exactly these four regular files:

```text
model.json
query_results.jsonl
audit.json
diagnostics.json
```

## Scientific model and reconstruction target

All variables are binary with values `0` and `1`. The manifest gives a rooted
junction tree. Its running-intersection property is guaranteed. The root clique
introduces all variables in its scope. Every other clique `C` has a parent,
an ordered separator `S = C intersect parent(C)`, and ordered new variables
`U = C minus S`. Every global variable is introduced exactly once.

Return a root probability table and one conditional table per non-root clique:

```text
q(x) = K_root(x_root) * product_C K_C(x_U | x_S).
```

The root table must sum to one. For each non-root factor and each fixed
separator assignment, summing over all new-variable assignments must give one.
These conditions make `q` a normalized joint distribution without enumerating
global states.

Each supplied clique count table is an independent multinomial observation of
the corresponding marginal of an unknown distribution `q*` in this disclosed
model family. Therefore finite-shot separator marginals disagree. Estimate a
single coherent `q` from all training count tables. This is a predictive target:
there is no hidden requirement to reproduce one canonical projection algorithm.
The private evaluator interprets your submitted factors and measures their
probabilities and clique marginals against new instances' latent `q*`.

The manifest gives a strictly positive `smoothing_pseudocount`. Adding it to every
cell before estimating probabilities is a documented baseline and prevents
zero-probability failures, but other statistically sound estimators are allowed.
Count-table totals can differ by clique and are the multinomial shot counts.
Validation records are held-out audit measurements and must not be used to fit
`model.json`.

## Table convention

Every clique and factor table uses that record's `variables` list. For an
assignment with values `value[j]`, its flat table index is

```text
index = sum(value[j] * 2**j for j in range(len(variables))).
```

Thus the first listed variable is the least-significant bit. Variable IDs,
clique record order, local axis order, and tree topology vary between instances.
Never infer semantics from an ID or record position.

For example, scope `["A","B"]` has indices `0:(0,0)`, `1:(1,0)`,
`2:(0,1)`, `3:(1,1)`. If child scope `["C","B"]` has separator `["B"]`
and new variables `["C"]`, conditional cells at indices `0,1` normalize for
`B=0`, and cells `2,3` normalize for `B=1`.

## Provided files

### `manifest.json`

Top-level fields are:

- `schema_version`: `local-noise-input/v1`.
- `instance_id`, `variable_count`, and unique `variable_ids`.
- `root_clique_id`.
- `table_encoding`, which restates the authoritative convention above.
- `smoothing_pseudocount`.
- `cliques`, in an arbitrary record order. Each record has exactly
  `clique_id`, nullable `parent_id`, ordered `variables`, ordered
  `separator_variables`, and ordered `new_variables`.
- relative filenames for counts, queries, and validation records.
- `audit_top_k`, an integer in `[0,M]` where `M` is the validation row count.
- `declared_bounds`, exactly
  `{"maximum_variables":96,"maximum_clique_size":7,"maximum_queries":64,
  "maximum_validation_interactions":64}`. It repeats a subset of the
  authoritative task limits below; these are not instance-specific sizes.

The root record has `parent_id: null`, an empty separator, and
`new_variables == variables`. In a child, `separator_variables` and
`new_variables` preserve their relative order in the child's `variables` list.

### `clique_counts.json`

This `local-count-tables/v1` object contains `instance_id` and `tables` in an
arbitrary order. It has exactly one table for every manifest clique, with no
duplicate or unknown `clique_id`. Each table has `clique_id`, positive integer `shots`, and
nonnegative integer `counts` of length `2**len(clique.variables)`. Counts sum
exactly to `shots`. No cells are missing and counts are never negative.

### `queries.jsonl`

Each input-order record has

```json
{"query_id":"...","assignment":{"variable-id":0,"another-id":1}}
```

The requested result is the joint evidence probability
`q(all listed variables equal their listed values)`. Unmentioned variables are
marginalized. The empty assignment has probability one. IDs are unique; an
assignment never repeats a variable, contradicts itself, or names an unknown
variable. Preserve query IDs and input order.

### `validation.jsonl`

Each input-order record has

```json
{
  "interaction_id":"...",
  "variables":["...","..."],
  "parity":1,
  "shots":4000,
  "successes":2173
}
```

It is an independent binomial measurement of the event

```text
XOR(x[v] for v in variables) == parity.
```

Interaction IDs are unique. `variables` is a nonempty list of at most seven
distinct known variable IDs. `parity` is integer `0` or `1`; `shots` is a
positive integer; and `successes` is an integer in `[0,shots]`.

Validation scopes may span distant cliques. Some private cases contain process
changes outside the disclosed local model, while ordinary cases contain none.
For a model probability `p`, compute

```text
z = (successes - shots*p) / sqrt(max(shots*p*(1-p), 1.0)).
```

Higher `abs(z)` is more anomalous. Compute probabilities and `z` in IEEE-754
binary64 arithmetic. Rank descending by the evaluator-recomputed binary64
`abs(z)` value; values tie only when those computed floats compare exactly
equal, then break the tie by ascending `interaction_id` code-point order.
Preserve interaction input order in the record list. Validation content may
affect `audit.json` and the `diagnostics.json` interaction inventory count only;
it must never affect the fitted model, query results, or other diagnostics.

## Output schemas

All numbers must be finite JSON numbers, not quoted strings. Extra keys, rows,
or files are rejected.

### `model.json`

The top-level object has exactly:

```json
{
  "schema_version":"rooted-junction-model/v1",
  "instance_id":"...",
  "root_clique_id":"...",
  "factors":[]
}
```

`factors` follows the manifest's clique record order. Every record copies
exactly `clique_id`, `parent_id`, `variables`, `separator_variables`, and
`new_variables`, and adds `probabilities`, a list of length `2**len(variables)`
using the disclosed flat index. Values must lie in `[0,1]`. Root and conditional
normalization error must be at most `2e-7`.

The evaluator treats this artifact, not self-reported query values, as the
authoritative model and runs its own sum-product calculations on held-out
queries.

### `query_results.jsonl`

One input-order line per query, with exactly:

```json
{"query_id":"...","probability":0.125}
```

The value must agree with the probability induced by `model.json`. Do not emit
conditional probabilities or log probabilities.

### `audit.json`

The top-level object has exactly:

```json
{
  "schema_version":"local-noise-audit/v1",
  "instance_id":"...",
  "interactions":[],
  "flagged_interaction_ids":[]
}
```

`interactions` follows validation input order. Each record has exactly
`interaction_id`, `predicted_probability`, signed `z_score`, nonnegative
`absolute_z`, and one-based integer `rank`. Ranks are a permutation of `1..M`.
`flagged_interaction_ids` contains the first `audit_top_k` IDs in rank order.
All audit numbers are recomputed from `model.json` during evaluation.

### `diagnostics.json`

The object has exactly:

```json
{
  "schema_version":"local-noise-diagnostics/v1",
  "instance_id":"...",
  "factor_max_normalization_error":0.0,
  "weighted_clique_tv_to_smoothed_counts":0.0,
  "max_raw_separator_tv":0.0,
  "max_model_separator_tv":0.0,
  "query_count":0,
  "interaction_count":0
}
```

For a clique table, smooth and normalize its observed counts using the manifest
pseudocount. Let `b_C` be the marginal induced by the submitted global model.
Total variation is `0.5 * sum(abs(b_C-r_C))`. The weighted clique value is the
shot-weighted mean of this quantity. Each separator TV is computed after
marginalizing the two incident clique tables to the child's ordered separator;
report the maximum separately for smoothed raw tables and for the two adjacent
clique marginals induced by the single submitted global model. Thus
`max_model_separator_tv` audits junction-tree consistency, not factor-row
normalization. The normalization field is the maximum absolute error of any root
sum or conditional separator-row sum from one. Counts are JSON integers.
Every field is recomputed and checked.

## Qualitative evaluation

Private evaluation uses several ordinary, distribution-shift, and anomaly
instances. It varies variable count, chain versus branching topology, clique
width, clique and variable ordering, bit-axis permutations, shot counts, query
scope, and validation interactions.

Continuous scientific scores reward:

- accurate submitted-model clique marginals and held-out evidence probabilities
  relative to the latent local model;
- query, audit, and diagnostic sidecars that agree with the submitted model;
- correct standardized-residual ranking and recovery of injected validation
  discrepancies;
- robust behavior on lower-shot and wider-clique instances.

Cases and metric groups are macro-averaged so one easy instance cannot conceal
a failed topology or anomaly case. Exact hidden cases, tolerances, thresholds,
and weights are private. Numerically equivalent float64 message-passing or
variable-elimination implementations are accepted; source similarity is not
evaluated.

## Environment and resource limits

- `solution.py` is UTF-8 source of at most 512,000 bytes. Python 3.11 or newer,
  the standard library, and `numpy==2.3.5` are the only dependencies.
- CPU only, one process, at most 4 logical CPUs, 4 GiB RAM, 45 seconds per
  instance, and 12 minutes total evaluator wall time.
- Network and subprocess creation are disabled. The solve process can read only
  its source, declared Python installation, and provided input directory, and
  can write only its output directory.
- Hidden bounds: 40-96 variables, clique size at most 7, at most 48 cliques,
  64 queries, 64 validation rows, 20 assigned variables per query, and 7
  variables per validation parity.
- Total per-instance output is at most 2,564,000 bytes. Individual decimal-byte
  caps are 1,500,000 for `model.json`, 500,000 each for query and audit output,
  and 64,000 for diagnostics.
- Output links, hard links, extra files, pickle/object formats, code-generated
  outputs after the solve exits, and nondeterministic results are rejected.

`software/validate_submission.py` checks public source/output structure. It has
no hidden answers and does not certify scientific accuracy.
