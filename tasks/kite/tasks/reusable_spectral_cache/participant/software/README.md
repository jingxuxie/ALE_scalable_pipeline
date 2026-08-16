# Public validation helper

Run:

```text
python validate_submission.py --participant .. --submission OUTPUT_DIRECTORY
```

The helper checks the visible inventory, array shapes and dtypes, response row
metadata, finite values, and diagnostics schema. It deliberately does not
compute reference moments or hidden scores.
