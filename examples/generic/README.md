# Generic compiler example

This fixture proves that a new task can be compiled without adding a
paper-specific Python family. The task protocol selects only allowlisted
generator, solver, output, metric, and gate primitives. The participant sees
worked examples and queries; evaluator-owned files retain exact answers.

For a browsable generated instance with public inputs and reviewer-only grading
references, see the [generic affine review example](../review/generic-affine/README.md).

```powershell
paper2ale inspect examples/generic/project.json
paper2ale audit examples/generic/project.json
paper2ale publish examples/generic/project.json --out dist --jobs 2
```

The source file is also recorded as a content-bound asset snapshot, including
its file-tree digest. Changing its bytes or manifest invalidates the project.

The generated participant specification now explains the equation, input
fields, exact JSON output, scoring thresholds, suggested method, and common
mistakes. The same full specification is used by the ALE runtime adapter.

The 2026-08-14 release audit passed all five hard instances, accepted the
independent visible-information baseline, and rejected 15 submissions spanning
the template-specific scientific error plus extra-key and missing-output
contract violations. The deterministic release build ID was
`build_152d13a0aee52641a6aded28564bfd508ef3536940d84fd57469becf3b0262fc`,
and its task build ID was
`task-build_93e633ede1300b8058ed1df6835c2569d18a40b8d5ad29a08a52f9810947e5f6`.
Primary archive hashes were:

- agent: `052a8743143686c37ebbd590b1a911f567c348629770f5ed21f143e505684c61`;
- ALE-local: `ac54ae59dd84f36419dcf56e52c721db52d220c84b2a983a52942741c38ed4f5`;
- author: `cd7f03eed88fed691d7fd5a4aad0707d7b998eacd2fde84729afada42b54981f`.

The builder inventory was reproduced over two runs, and every golden/mutant
grader execution was repeated twice with matching process output and parsed
score payload. The full repository suite passed 285 tests with one Windows
symlink-capability skip. Separate processes produced the same generic build ID
and tree hashes.

The catalog used for that statement is a local Git-ignored verification
artifact, not a file carried by a clean clone. Run the `publish` command above
to recreate the catalog and release evidence from the checked-out compiler and
project inputs.
