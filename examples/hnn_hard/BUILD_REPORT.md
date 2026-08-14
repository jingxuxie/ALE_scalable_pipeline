# Hard HNN grounded suite build report

Build date: 2026-08-13
Project: `hnn-hard-grounded-suite`
Difficulty selection: `hard`
Full build ID:
`build_cfbe63579e1199673d13e41c38912c5012d100ad2617429c0cf15dd0530554a5`
Physical build directory:
`dist/hnn-hard-grounded-suite/b-cfbe63579e1199673d13e41c`

## Source locks

- Paper: `arXiv:1906.01563v3`, PDF SHA-256
  `bd83fe321874ddad9471f83a642ae94ab7412fd9eb0add8caae84a0ee20d168b`.
- Official implementation: Git commit
  `bcc362235dc623ffe48f22ccc22417e02e9803b4`.

The paper and code are author-side provenance only. Agent bundles contain the
task specification and generated observations, not the source paper or hidden
truth.

## Publication verification

All three tasks report `preflight_passed: true` and
`publication_ready: true` under the Paper2ALE gate set.

| Task | Private instances | Golden graders passed | Registered mutants rejected |
| --- | ---: | ---: | ---: |
| `hnn-hard-coupled-identification` | 2 | 2 | 2 |
| `hnn-hard-variable-nbody` | 2 | 2 | 2 |
| `hnn-hard-canonical-recovery` | 2 | 2 | 2 |

Every task passed schema, provenance, paper-blind visibility, generated Python
syntax, difficulty-consumption, runtime-reference, mutation-resistance,
resource-smoke, and byte-reproducibility gates. Repository verification passed
127 unit and integration tests. The complete build directory and all 21 ZIP
archives passed manifest-aware validation.

A second build with a different worker count validated and resumed the same
full build ID. It did not silently reuse unverified output.

## Primary bundle hashes

| Task | Agent SHA-256 | ALE-local SHA-256 | Author SHA-256 |
| --- | --- | --- | --- |
| `hnn-hard-coupled-identification` | `7f2d644dccbffe6075093a120fa7e11c7b9b7e0633edf9c04dcf749477819547` | `90c70ee168484c0520f948e70ab4f846f1940cf7d6d05ab3b2ee1dc37f94460e` | `86917e6318af30a191400811078c138032a7b4ecb76277d6aaf7dea5dab1cebf` |
| `hnn-hard-variable-nbody` | `8881f2043d73d1465f80df90b93830356210de3b45e2b39b7274525ef6d2bdce` | `1c16914cd332e3f3a4ff532fbbaf49e41961ec0d580a0e38f4460cecfac57d53` | `1e846f96414f36943f596ae294172cdedc98234b3128746ddfb7c424c6f70628` |
| `hnn-hard-canonical-recovery` | `7a46ab62d15bdbea2049c6eecf02c08a8767186c41721a2a3053aae77fc4df31` | `49f8b5465f2be90a393769aa78b110713fb4757a1dd80d3056bcfc122874c1fa` | `f17c8aee283f900144e31ca30039fcf29b8857095400dd60134eaf114268760a` |

The authoritative archive list, including evaluator and compatibility bundles,
is `catalog.json` in the physical build directory.

## Difficulty claim and remaining benchmark step

`hard` is an enforced structural profile, not merely a label. It changes
training density, noise, masked information, OOD ranges, hidden-case counts,
rollout horizons, tolerances, body cardinality, and adversarial cases. The
author projection contains the exact resolved control manifest.

The suite has not yet been empirically calibrated against a matrix of frontier
models and agent scaffolds. To claim a measured frontier solve rate, run ALE
episodes, record pass/fail trials, and feed them to `paper2ale calibrate`.
Likewise, the resource gate is bounded smoke evidence; it is not peak-memory or
full participant-training profiling. A live Docker/GCE ALE episode remains the
final environment-specific deployment check when `cua_bench` is available.
