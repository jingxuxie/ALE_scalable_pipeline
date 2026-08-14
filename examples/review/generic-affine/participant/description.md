# Structured research workflow task

Infer the numeric transformation from public examples, then predict all query outputs.

Each variant provides `input/instances/<NNN>/input.json`. The file is the
complete participant specification and contains an explicit JSON output
contract. Write only the requested bounded data artifact to
`output/<NNN>/submission.json`. Submitted Python, commands, pickles, and
executable objects are not accepted or loaded by the evaluator.
