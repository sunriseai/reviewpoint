# One synthetic work review

WORK-001 is a generic work package with a summary and expected/supplied counts. All data is invented. The initial mismatch demonstrates Hold; a revision with matching counts demonstrates Proceed. Model-generated answers and human decisions are not fixtures.

Start `reviewpoint demo`, then use the UI or this host client:

```bash
uv run --frozen --offline python examples/work_review/client.py inspect
uv run --frozen --offline python examples/work_review/client.py revise --supplied-items 4
```

Record the human decision in the UI after requesting an evaluation. Then:

```bash
uv run --frozen --offline python examples/work_review/client.py handoff
```

The client uses the private host credential to read/submit/report through the public API. It cannot make a human decision. Handoff checks the latest decision, exact submission and action, then reports only a simulation. The [profile](profile.json) and [initial submission](submission.json) document the input shapes; the client refreshes evidence timestamps for each submitted snapshot.

Use `--help` for workspace and URL options. Core host behavior is independent of the demo UI's optional bridge routes.
