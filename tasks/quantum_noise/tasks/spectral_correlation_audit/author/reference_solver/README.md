# Clean-room reference solver

From the task root, construct a participant submission with:

```text
python author/reference_solver/solve.py --participant participant --submission <submission-directory>
```

The command reads the participant manifest only to verify the public schema. It
copies a NumPy-only analyzer into the requested submission directory. The
verification script runs this command in a temporary directory containing only
the participant package and this solver.
