# Fresh-agent difficulty prompt

Give the fresh agent only the task's `participant/` directory, then use this prompt.

```text
You have at most 10 minutes to complete the task in this directory.

Read TASK.md and inspect all provided inputs and starter files. Solve the task and place the required deliverables under output/ exactly as requested.

You do not have access to the source paper, author solution, hidden evaluator, or authoring conversation. Do not ask for them.

Use the available tools actively. Run your code and inspect its outputs. Prioritize a complete, working submission over a long explanation.

Stop when the task is complete or when the time limit is reached. In your final response, state what you produced and any known remaining issue.
```

Record the model/harness, start time, end time, and whether the evaluator passed. No other review is required for the fast screen.
