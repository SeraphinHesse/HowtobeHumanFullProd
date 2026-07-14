---
description: Shared final-report format — provenance-tagged claims plus the artifact publish rule. Invoke at the end of any orchestrated run, audit, or phase completion; workers report upward instead.
argument-hint: <what finished + audience, e.g. "phases 10G-10I wave results">
allowed-tools: Read, Glob, Artifact
---

Produce the final report for **$ARGUMENTS**.

## Provenance taxonomy (every claim, no exceptions)
- **measured** — you ran a command and got a number; include the command AND
  the number.
- **verified** — you read the code or ran the thing once and saw it happen.
- **inferred** — reasoned but not confirmed; say so explicitly.
Untagged claims don't ship. If a plausible claim matters to the decision,
measure it before asserting it.

## Report shape
1. Outcome first — what happened, one paragraph a human can act on.
2. Results/findings ranked by importance, `file:line` where relevant,
   provenance tag on each.
3. Verification: exactly what was run (smoke / suite vs baseline / live run /
   Quick Test) and what it showed. Summarize — never paste raw gate output.
4. Open items and who decides each.

## Artifact publish rule
Publish an artifact ONLY at the boundary where work returns to a human to
decide or catch up. The orchestrator publishes; workers report upward.
- **Yes:** `/execute-plan-phases` end-of-run, `/processtodo` summary,
  `/execute-phase` completion, audits/investigations.
- **No:** coder/reviewer/scout subagents, `/dispatch`, `/smalltweak` — the PR
  body already does that job.
- **Never:** exit-gate output (the gate's whole point is collapsing to a few
  tokens — publishing it would undo that).
Who reads it next decides where it lives: a future agent, repeatedly → repo
file; a human, once, to decide → artifact. Agents read files, not artifacts.

## The active-plan permanent link
On each phase-status write-back, republish root `PLAN.md` as the artifact
**"How To Be Human — Active Plan"** (favicon 📋 — keep both stable):
- Same session: call Artifact again with the same file path — it redeploys to
  the same URL.
- New session: `Artifact action:list` → find "How To Be Human — Active Plan" →
  pass its `url`. Never mint a second URL for the plan mirror.

## Verify
Every claim in the report carries a tag; if an artifact was published, its URL
is in the report and the title/favicon match the existing artifact's.
