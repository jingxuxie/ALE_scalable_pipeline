# Alternative valid solver

This builder keeps the disclosed parsing and artifact conventions but replaces
both important numerical choices. It uses multi-start damped Gauss-Newton in
amplitude/log-decay coordinates rather than a profiled grid search, and locates
the simplex threshold by bisection rather than sorting. It reads no hidden
inputs or reference values.
