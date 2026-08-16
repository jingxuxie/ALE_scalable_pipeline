# Public validation software

Run `validate_submission.py <submission-directory>` with the declared Python
environment. The command executes the submitted analyzer on the retired public
instance, so run it only for code you trust. It performs structural checks and
checks that the packaged public input respects its disclosed byte and identifier
bounds. It does not contain hidden inputs, references, private scientific
thresholds, score weights, or scientific answers, and a pass is not a private
scientific-accuracy result.

The source check is deliberately structural: exact one-file inventory, regular
link-count-one source, byte limit, UTF-8 decoding, and Python syntax. It runs an
immutable copy of the checked bytes and bounds console and output growth, but it
does not sandbox untrusted Python or enforce OS CPU/memory/network isolation.
Private evaluation applies runtime capability checks as defense in depth, and
the ALE service must use its normal OS/container isolation. No private
scientific thresholds, score weights, or hidden answers are present here.
