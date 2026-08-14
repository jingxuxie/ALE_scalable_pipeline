# Threat model and publication gates

Scientific task generation fails quietly when it confuses a plausible-looking
artifact with a trustworthy evaluation. Paper2ALE therefore treats evaluator
validity as the dominant constraint.

## Threats

### Untrusted source instructions

Papers, HTML, repositories, issue text, notebooks, and datasets may contain
instructions aimed at an extractor. Provider requests delimit source material
as untrusted data. Extracted JSON still has no authority until it passes the
strict schema and evidence-reference checks.

### Paper/code disagreement

A paper is not assumed to dominate code, and code is not assumed to dominate a
paper. Conflicting records share a `conflict_set`, retain both exact locators,
and remain unresolved until a protocol explicitly selects and explains one.
Tasks cannot depend on unresolved high-impact conflicts.

### Reference leakage

Every file is visibility-labeled before packaging. The audit rejects duplicate
paths, evaluator/reference-looking agent paths, empty assets, and configured
private sentinel bytes in agent files. ZIP validation rejects traversal,
absolute and drive paths, duplicate or case-colliding members, links, special
files, and excessive expanded size.

### Self-reported metrics and fabricated truth

Graders must recompute metrics from trusted targets. A submission's own metrics,
ground-truth trajectories, plots, or prose are never authoritative. The HNN
model task exports safe-format MLP weights; the evaluator independently derives
the scalar-Hamiltonian vector field and integrates it on evaluator-held states.

### Degraded comparator

Ratio metrics can be gamed by intentionally worsening a baseline. Evaluation
must gate the absolute accuracy of every compared model and use improvement
ratios only after those gates pass.

### Hard-coded public instances

A workflow owns multiple deterministic instances with different seeds and
parameters. Participant inputs may be visible, while labels and reference
outputs remain evaluator-only. A shared grader must work over the whole family.

### Stochastic reference luck

Thresholds should eventually be calibrated from multiple clean reference runs,
not one successful seed. The schema records seeds and resource limits now; the
task family can add distributional calibration before publication.

### Unsafe participant code

Prefer declarative outputs or portable safe-format weights that a trusted
grader can interpret. If participant code must run, isolate it, disable network
access, bound time/memory/output, pass hidden queries without exposing the full
reference tree, and treat its output as untrusted.

## Hard publication gates

A task is publishable only when all applicable gates pass:

1. project and output schemas validate;
2. every task requirement and score maps to evidence IDs;
3. source versions and licenses are pinned;
4. no unresolved high-impact conflict affects the protocol;
5. agent projection contains no evaluator/reference material;
6. the trusted grader recomputes metrics and handles malformed submissions as
   structured failures;
7. a successful reference implementation passes;
8. registered realistic mutants fail;
9. clean offline execution respects the resource budget;
10. rebuilding produces the same build ID, manifests, and ZIP bytes.

A soft quality score may rank tasks that pass. It must never override a failed
hard gate.
