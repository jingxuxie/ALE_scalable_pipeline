# Independent clean-room solver

`solve.py` creates a participant-shaped submission containing exactly
`output/analyze.py`. The analyzer uses only the public task contract, standard
library modules, and NumPy.

This is intentionally not a restatement of the privileged polynomial-search
oracle. It first reconstructs realization-block statistics, applies weighted
monotone regression separately at each size, and locates robust pairwise size
curve crossings. It estimates leading finite-size drift from the size-wise
central coordinates, selects the positive exponent by leave-one-size-out
non-parametric data-collapse error, and interpolates a monotone universal
response for held-out queries. Transition intervals resample complete
realization blocks and include the requested analysis-grid sensitivity.
It still honors the participant contract's fixed preliminary-center window and
reports the common weighted-cubic residual diagnostic, so its evidence fields
have the same semantics even though its estimator and predictor are independent.

Build and validate from the task root:

```text
python author/alternative_solver/solve.py --participant participant --output <submission-directory>
python participant/software/validate_submission.py --submission <submission-directory> --run-public
```
