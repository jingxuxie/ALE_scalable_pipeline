# HNN grounded suite build report

Build date: 2026-08-14

Project: `hnn-grounded-suite`

Publication mode: `release`

Full build ID:
`build_b6fd2fe9c21eafd4d3ad24c3173452c8a1fe4d41234dbefad2d47741b38cd99a`

Physical build directory:
`tmp/v03-review-bound-final-20260814/hnn-grounded-suite/b-b6fd2fe9c21eafd4d3ad24c3`

The physical directory is Git-ignored and is not part of a clean clone.
Reproduce the fail-closed release with:

```powershell
paper2ale publish examples/hnn/project.json --out dist --jobs 3
```

## Source locks

- Paper: `arXiv:1906.01563v3`, PDF SHA-256
  `bd83fe321874ddad9471f83a642ae94ab7412fd9eb0add8caae84a0ee20d168b`.
- Official implementation: Git commit
  `bcc362235dc623ffe48f22ccc22417e02e9803b4`.
- ALE runtime contract reference: Git commit
  `75a3f866535946b67f9a57e4f158eb30ad50be8a`.

The paper and code remain author-side provenance. Agent bundles contain the
task specification, generated inputs, and starter software, not the paper or
hidden references.

## Publication verification

All three tasks reported `preflight_passed: true` and
`publication_ready: true` under the current Paper2ALE release gates.

| Task | Task build ID | Golden graders passed | Registered mutants rejected |
| --- | --- | ---: | ---: |
| `hnn-mass-spring` | `task-build_2e3418cd9a1304b950bbc206243d06246830f75791d048268c9cafd06ae8d967` | 3 | 3 |
| `hnn-symplectic-gradient` | `task-build_0741d6c880756cf92fdb83388105b25de508c9cdd718f8c95caba992312b6104` | 3 | 3 |
| `hnn-two-body-audit` | `task-build_4237a8342637c6dab3d3a19cc4388ece985a1fb531c1da1b01a2a2cd5e6aa152` | 3 | 3 |

Every task passed schema, provenance, paper-blind visibility, syntax,
runtime-reference, mutation-resistance, resource-smoke, and reproducibility
gates. The builder inventory was reproduced over two runs. Each golden and
mutant grader execution was also repeated twice and matched in process state,
stdout, stderr, and parsed score payload.

The full repository suite passed 281 tests with one Windows symlink-capability
skip. The complete release directory and its 21 ZIP archives passed
manifest-aware validation. A separate generic build produced byte-identical
build/tree hashes across processes, exercising cross-process compiler identity
stability.

## Primary bundle hashes

| Task | Agent SHA-256 | ALE-local SHA-256 | Author SHA-256 |
| --- | --- | --- | --- |
| `hnn-mass-spring` | `fba8713357953470824e9c7bd5f651e239969c315f525667c94826cde737a894` | `59cb9cd1601a001063d836698da2ad0700f741515d345c492df13c14240fd681` | `7059274b9df9c7485315f221e6058badea24d2d59451087d502112d28d19dbed` |
| `hnn-symplectic-gradient` | `de7bde79b36c3ee496c786853380422f84db49e6182c108d01cca7e5d6b28232` | `7c812cb2c545c3da6cca85bc753625942376cd438e5504f28730e010f20ef998` | `22cf679c1de3975ad2b107a3da371750943179ad82ded938a81ded7a47386aaf` |
| `hnn-two-body-audit` | `74969789bee432100a6e27b8da8f992cef8c7401b6f214d57310331b0aed781a` | `03863250d6df95d1ddba49222b2e9469ded37f489e377c7301b88b348a39c109` | `2f05c8911b72fc6c0df0465c3980dbf2fd236bb674fc52f38896dd41a1fb3e63` |

The authoritative complete archive list, compiler/verifier identities, task QA,
and manifests are in `catalog.json` inside the ignored physical build. A clean
clone must run the reproduction command to create its own current catalog.

## ALE-local projection boundary

Each `<task-id>.ale-local.zip` contains a contract-shaped task-discovery adapter
plus canonical local task data. The hooks and variant metadata were executed
against the repository's contract-compatible runtime stub. This report does
not claim a live Docker, GCE, `cua_bench`, or interactive computer-use run;
those environment-specific checks are outside the v0.3 release scope.
