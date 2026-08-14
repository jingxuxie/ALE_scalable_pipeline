# HNN grounded suite build report

Build date: 2026-08-13
Project: `hnn-grounded-suite`
Full build ID:
`build_ea5d1601cdcff2cedab919b3ece4b2a962cbf99c5a63ba92bede0241ae818f3b`
Physical build directory: `dist/hnn-grounded-suite/b-ea5d1601cdcff2cedab919b3`

## Source locks

- Paper: `arXiv:1906.01563v3`, PDF SHA-256
  `bd83fe321874ddad9471f83a642ae94ab7412fd9eb0add8caae84a0ee20d168b`.
- Official implementation: Git commit
  `bcc362235dc623ffe48f22ccc22417e02e9803b4`.
- ALE runtime contract checked against Git commit
  `75a3f866535946b67f9a57e4f158eb30ad50be8a`.

## Publication verification

All three tasks report `preflight_passed: true` and
`publication_ready: true` under the checked Paper2ALE gate set.

| Task | Private instances | Golden graders passed | Registered mutants rejected |
| --- | ---: | ---: | ---: |
| `hnn-symplectic-gradient` | 3 | 3 | 3 |
| `hnn-mass-spring` | 3 | 3 | 3 |
| `hnn-two-body-audit` | 3 | 3 | 3 |

Every task also passed source-lock provenance, paper-blind visibility, generated
Python syntax, a byte-identical repeated builder run, and wall-time/package-size
resource smoke checks. The resource gate is intentionally labeled smoke
evidence: it does not measure peak memory or benchmark a participant's full
training procedure.

Repository verification: 81 unit/integration tests passed. The completed build
directory and all 21 emitted ZIP archives passed manifest-aware validation.
Re-running the build with a different worker count resumed the same full build
ID only after validating the catalog, full directory manifest, sizes, hashes,
and embedded ZIP manifests.

## Primary bundle hashes

| Task | Agent SHA-256 | ALE-local SHA-256 | Author SHA-256 |
| --- | --- | --- | --- |
| `hnn-symplectic-gradient` | `7d7962e040695a33a7d287cb5c8b52d447dc0a8275e8dd307f0ad51b1e7a6185` | `a282b3ef4c791f522e5acc037cb0a593de863473bd68db6f930b91e9fbc46ac7` | `d9acbcf41573c9d077dffa3af92e41fe201b6f4eac2e58eae21879b50e58ce9e` |
| `hnn-mass-spring` | `d946436d94112c46978afec99927aee54325253e991fcc7eaa2ae446a56c1a2a` | `f3dfd31e95dc4c31056f8f4a08c234f5bc82c00b0a1372a0620f18c99e6435bf` | `cdfbfa635b8088d2ca0e2dfd0ca37d3be021c4b409c970350ab4a7b9d21b2772` |
| `hnn-two-body-audit` | `8267d0abae410aac18079d7ae31e28aa66a619c96e835b160089e7304bd863b8` | `c30984432c3f9c5ef1385b3454de6c4c66517d8a2ce9c2ed3d3cd530217dcf8c` | `1615e49ade8955d7e5399a15dbfabb98f938bb9270b9289ed87862b559b3bd09` |

The authoritative list, including evaluator and compatibility archives, is
`catalog.json` inside the build directory.

## ALE-local deployment

Each `<task-id>.ale-local.zip` contains:

```text
tasks/physical_sciences/<task-id>/{main.py,task_card.json,README.md}
task-data/physical_sciences/<task-id>/<000|001|002>/{input,software,reference}
```

Extract the bundle, merge its `tasks/` tree into an ALE checkout, and configure
`task_data_source: local:<extracted-root>/task-data`. The bundle is benchmark
operator material because it contains plaintext evaluator references; ALE's
local provider stages them only after the agent phase.

The generated `load()` hooks and all variant metadata were executed against a
contract-compatible runtime stub, and public runners were exercised from the
canonical variant layout. A live Docker/GCE ALE episode remains the final
environment-specific smoke test because this workspace does not have ALE's
`cua_bench` runtime installed.
