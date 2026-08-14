# Generic compiler example

This fixture proves that a new task can be compiled without adding a
paper-specific Python family. The task protocol selects only allowlisted
generator, solver, output, metric, and gate primitives. The participant sees
worked examples and queries; evaluator-owned files retain exact answers.

```powershell
paper2ale inspect examples/generic/project.json
paper2ale audit examples/generic/project.json
paper2ale publish examples/generic/project.json --out dist --jobs 2
```

The source file is also recorded as a content-bound asset snapshot, including
its file-tree digest. Changing its bytes or manifest invalidates the project.

The 2026-08-14 release audit passed all five hard instances, accepted the
independent visible-information baseline, and rejected 15 submissions spanning
the template-specific scientific error plus extra-key and missing-output
contract violations. The deterministic release build ID was
`build_73367a43f8f79044e2ec9864b4cc2025251c21236bbfab187f4451ce444bd187`,
and its task build ID was
`task-build_29ef8077e8fe6fea53a8602c85008de2a009257ee9cd0f581d19eb06c298c85c`.
Primary archive hashes were:

- agent: `6b9cf61b9b8bd2c3b39ca5f20228c8a8d81f514d010cbe5be0ec2fe579967ab9`;
- ALE-local: `5ead2eff77dd0e934b17de21a6c7907229de101163cdc3ecd7d71327b9526385`;
- author: `736954bf62fbfad608fb097a2b8fa0323e3d6254a005e099dc436e8b87bedfac`.

The builder inventory was reproduced over two runs, and every golden/mutant
grader execution was repeated twice with matching process output and parsed
score payload. The full repository suite passed 281 tests with one Windows
symlink-capability skip. Separate processes produced the same generic build ID
and tree hashes.

The catalog used for that statement is a local Git-ignored verification
artifact, not a file carried by a clean clone. Run the `publish` command above
to recreate the catalog and release evidence from the checked-out compiler and
project inputs.
