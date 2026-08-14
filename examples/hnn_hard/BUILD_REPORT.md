# Hard HNN grounded suite build report

Build date: 2026-08-14
Project: `hnn-hard-grounded-suite`
Difficulty selection: `hard`
Full build ID:
`build_0cf376e7c0768c651ea764eb481f1940698bebc71b90a3442bfd546020cdc624`
Physical build directory:
`tmp/review-descriptions-release-20260814/hnn-hard-grounded-suite/b-0cf376e7c0768c651ea764eb`

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

Each participant package now carries the same full specification in
`description.md` and the ALE runtime task description, including equations,
input and output schemas, constraints, evaluation thresholds, suggested
solution steps, and common mistakes.

| Task | Task build ID | Golden graders passed | Registered mutants rejected |
| --- | --- | ---: | ---: |
| `hnn-hard-coupled-identification` | `task-build_7a91d9183f43862779d49d70bf74053a031711aabdcc5ea5769dbd5c77917570` | 2 | 6 |
| `hnn-hard-variable-nbody` | `task-build_f4c2b72b823dc6bbc6df27b996449cdc785fcd2651223835e958b1a104c2de48` | 2 | 6 |
| `hnn-hard-canonical-recovery` | `task-build_3a10cff7e4b9c5403f483e12c1612fcfebc52539703d58aae96bda073867bc17` | 2 | 6 |

Every task passed schema, provenance, paper-blind visibility, generated Python
syntax, difficulty-consumption, runtime-reference, mutation-resistance,
resource-smoke, and byte-reproducibility gates. Builders were compared over two
runs, and each golden/mutant grader execution was run twice with matching
process state, stdout, stderr, and parsed score payload. Repository verification
passed 285 tests, with one Windows symlink-capability skip. The complete build
directory and all 21 ZIP archives passed manifest-aware validation.

The pipeline regression suite also verifies identical output across worker
counts and refuses to resume missing, altered, or unverified archives.

## Primary bundle hashes

| Task | Agent SHA-256 | ALE-local SHA-256 | Author SHA-256 |
| --- | --- | --- | --- |
| `hnn-hard-coupled-identification` | `289a8e2adbf21909eac973b84a2f56f42d4b2ca5efd121d7ea41dfecac96fe9f` | `5a996a766c230b5e88efb89df413822023b3bd1393b33eb0201c361baab5c744` | `658c65ba08d3d441786c3723bf88ae4d0145b55c9f085ddb4fbfd1e621917c5c` |
| `hnn-hard-variable-nbody` | `d0f2ec7da6ba922084bd1489c06aaacce958353f70f818141e5925ab1cb1dd4d` | `00a96865a4a3b052554fbfc6c46a599ce9041eee96315bceaf7d80075ce71e6a` | `3871a7977c131621b923faa6dc5bc379ce473fae39d1c1f3909baae09fa4c007` |
| `hnn-hard-canonical-recovery` | `9d2796b2ddb4d40a18cdea7d8a5ba1ffa998e2df01ff1c433c2bd032ecfc080e` | `77e68ce4e871297e235f875a513f106066f150242f4fd14a65e2e94ce48563ae` | `907cd09d056cec5ebf6839a9dc9e7d9d8c77477144511cabca149b7cdd41e93a` |

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
