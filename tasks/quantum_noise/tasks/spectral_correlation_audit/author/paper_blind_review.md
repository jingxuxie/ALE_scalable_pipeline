# Paper-blind specification review

- Reviewer isolation: fresh agents with `fork_turns=none`
- Allowed projection: `participant/` only
- Paper/source/private access: prohibited and not used
- Final status: pass

## Restatement

The participant must submit one reusable NumPy analyzer. It corrects randomized
binary targets with XOR, pools count histograms, applies an explicitly normalized
character transform, fits nuisance-amplitude decays over actual length values,
inverts and projects the recovered spectrum, computes dependence statistics,
reconstructs a supplied clique-tree local model, quantifies mismatch, and ranks
the strongest nonlocal conditional interactions. The analyzer produces six
strictly specified runtime artifacts on public and unseen valid inputs.

## Review history and resolutions

The first isolated review failed and identified five real issues:

1. exact decay minimizers could be non-unique on degenerate inputs;
2. `0^0` was not explicitly defined;
3. input, topology, count, and ranking validity guarantees were incomplete;
4. hidden dimensions and volume were not bounded against runtime resources;
5. the public validator description overstated its checks.

The task was revised to define a canonical minimizer tie rule, `lambda^0=1`,
positive/well-separated generated fits, full count/topology/ranking invariants,
`n<=8`, bounded lengths/rows/counts/clique width, integer serialization, explicit
MI/CMI/KL zero-mass formulas, public simplex feasibility tolerance, and stronger
public validation.

The second isolated review failed on narrower residual issues: duplicate clique
lists were unbounded, JSON integer coercion was permissive, and the validator did
not compare the ranking against omitted nonlocal pairs. The task was revised
again to bound the manifest and clique count, require unique clique scopes, use
strict JSON number/integer type checks excluding booleans and strings, and
compare the submitted ranking with the global top-k derived from every
`dependence.csv` nonlocal pair.

A later security-focused review found that syntax blacklists both rejected
ordinary Python and could be bypassed through aliases. Source acceptance was
narrowed to exact inventory, regular link-count-one bytes, size, UTF-8, and
syntax. Capability restrictions are now behavioral private-runtime checks, with
ALE OS/container isolation explicitly required for deployment. The public
runner now executes an immutable copy of the bytes it inspected and streams its
console and output-size limits. A final rereview found one atomic-rename race in
the live output scan; the scan now ignores only vanished-entry
`FileNotFoundError`, retries on the next poll, remains fail-closed for other
errors, and performs a strict final inventory.
The last portability check found that Python-valid UTF-8 BOM source was rejected
by plain text decoding; both structural parsers now use `utf-8-sig`, preserve
the original checked bytes for execution, and accept the BOM-bearing valid
probe.

## Final review

A fresh participant-only rereview of the final projection returned an
unconditional pass. The reviewed visible-validator SHA-256 was
`97188585dcef4bce2e7f89ff12505ac945af731e0674c74cb8e0d58f5df24ef3`.
It confirmed that the complete workflow, all mathematical
conventions, canonical fit and ranking rules, output schemas, and hidden-input
validity envelope are solvable without the paper or private evaluator. The last
resource-closure issue was resolved by capping `raw_counts.csv` at 12,000,000
bytes, bounding both identifier fields, checking those public bounds in the
visible validator, and stating explicitly that the validator contains no private
scientific thresholds. The reviewer also confirmed the clean five-file
participant inventory and found no remaining validator-claim mismatch after the
source-policy and atomic-rename repairs.

The post-review generator continues to enforce the disclosed profiled-SSE
separation of at least `1e-10` at an eigenvalue displacement of `1e-4` and a
canonical separator-marginal floor of `1e-3` on every generated case. These are
public validity guarantees, not hidden scoring thresholds. The reviewer found
no remaining paper-blind specification, feasibility, or public-validator-claim
gap.
