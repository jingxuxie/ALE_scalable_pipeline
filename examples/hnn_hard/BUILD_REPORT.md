# Hard HNN grounded suite build report

Build date: 2026-08-14
Project: `hnn-hard-grounded-suite`
Difficulty selection: `hard`
Full build ID:
`build_6f3d22026d0d82ec98f250c2b46c1c8d7d5633f3b5c16136cb325867c9158305`
Physical build directory:
`tmp/v03-review-bound-final-20260814/hnn-hard-grounded-suite/b-6f3d22026d0d82ec98f250c2`

This is a local verification directory under Git-ignored `tmp/`; its catalog
and archives are not present in a clean clone. Reproduce the current
fail-closed release with:

```powershell
paper2ale publish examples/hnn_hard/project.json --difficulty hard --out dist --jobs 3
```

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

| Task | Task build ID | Golden graders passed | Registered mutants rejected |
| --- | --- | ---: | ---: |
| `hnn-hard-coupled-identification` | `task-build_ab6b077eeb4ee3062bf185835a31aa8c27e010811459ba45d1a459e6d1feac88` | 2 | 6 |
| `hnn-hard-variable-nbody` | `task-build_37bf3cadff160cae56e05fcd654341c51528eb7c7a5f60d0c7b5a5ddcf72874b` | 2 | 6 |
| `hnn-hard-canonical-recovery` | `task-build_b898028188fd78012ab82acef34a76ac2a5efc464ae8572c98e102db9eb9ea12` | 2 | 6 |

Every task passed schema, provenance, paper-blind visibility, generated Python
syntax, difficulty-consumption, runtime-reference, mutation-resistance,
resource-smoke, and byte-reproducibility gates. Builders were compared over two
runs, and each golden/mutant grader execution was run twice with matching
process state, stdout, stderr, and parsed score payload. Repository verification
passed 281 tests, with one Windows symlink-capability skip. The complete build
directory and all 21 ZIP archives passed manifest-aware validation.

The pipeline regression suite also verifies identical output across worker
counts and refuses to resume missing, altered, or unverified archives.

## Primary bundle hashes

| Task | Agent SHA-256 | ALE-local SHA-256 | Author SHA-256 |
| --- | --- | --- | --- |
| `hnn-hard-coupled-identification` | `dcb04d032170fa70e7fb6255860a9619a77415df909460ecea2a873ce9519a67` | `e2534a190df546bc60d51b24e665876df772b28febb0bf8c1214316ff502b936` | `cd983550c31c4398bccdf3b017a38b04b5b2602a05996919661210fda77916f2` |
| `hnn-hard-variable-nbody` | `143a4e43f8cb6ef96649e02aab467d98b27a3e0223288f8eb4d7b2b071023a19` | `68fa8247979799525ff069cb36022caddb0d74edf97ad6d7f2158039776312fa` | `7651b2c5736f090816c3227ee87f94b9bc11a8ba32e545c5db6eb439a5f9ab3d` |
| `hnn-hard-canonical-recovery` | `7fa9f530d076325d710c0cffedfcf6de02356a50287e5c87360a004324ddac4a` | `ea01cf8790c598fb9705b8aac0202d70cbe4bdaed750baad51f8a8a25ea1e95d` | `b6ac670f89008916842a04137110d378f67159dfd7301e8d369ccbd5a94795b6` |

For the recorded local build, the authoritative archive list, including
evaluator and compatibility bundles, is `catalog.json` in the ignored physical
build directory. The reproduction command writes a reviewable local catalog
under `dist/` and prints its build result.

## Difficulty claim and remaining benchmark step

`hard` is an enforced structural profile, not merely a label. It changes
noise, masked information, problem complexity, OOD ranges, hidden-case counts,
rollout horizons, tolerances, body cardinality, and adversarial cases. Public
training-label counts stay fixed across levels so a harder label never grants
more supervision. The author projection contains the exact resolved control
manifest.

The suite has not yet been empirically calibrated against a matrix of frontier
models and agent scaffolds. To claim a measured solve rate, run episodes and
record strict v2 rows with a unique `trial_id`, seed, attempt, normalized score,
task-build-bound semantic ID, and pinned agent system. Verify the report against
this build's exact `project.lock.json` and sibling `catalog.json`; a no-catalog
summary cannot set `verified_claim_ready: true`. Likewise, the resource gate is
bounded smoke evidence, not peak-memory or full participant-training profiling.
A live Docker/GCE or interactive computer-use episode remains outside this
v0.3 release report.
