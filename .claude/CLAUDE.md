# Constitution

Every non-trivial task runs through four phases:

- **P1 — Plan.** You (the main agent) reason about the task and log the plan before acting.
- **P2 — Broad research.** `researcher` maps the relevant landscape (files, existing behavior, prior art).
- **P3 — Targeted research.** `researcher` answers the narrow follow-up questions P1 or P2 raised.
- **P4 — Verify.** `verifier` checks the finished change against the logged plan before it ships.

Skip P2-P4 only for trivial one-line changes where research and verification are pure overhead. Never skip P1, and never skip P4 on anything that changes behavior.

## P1: reasoning + logging rules

1. State the plan in 2-5 bullets before acting: what, in what order, why.
2. Decide which phases the task needs.
3. Append a decision-log entry to `.claude/logs/decisions.md` before executing the plan, then fill in the outcome after.
4. The log is append-only — never rewrite or delete a past entry.

### Decision log format

```
## <YYYY-MM-DD HH:MM> — <short task title>
**Plan:** <1-3 sentences: what & why>
**Phases used:** P1 [P2] [P3] [P4]
**Outcome:** <filled in after completion: what shipped, what changed>
```

## Non-negotiables

- Only P1 (the main agent) writes or edits files. `researcher` and `verifier` are read-only — they never gain Edit/Write access.
- `verifier` reports problems; it does not fix them. Fixes happen back in P1.
- If `verifier` returns FAIL, the task is not done — loop back to P1.
