---
description: Sweep the codebase with 10 parallel read-only reviewers for bugs, performance and cleanup, then publish one ranked triage Artifact with per-issue checkboxes and copy buttons.
argument-hint: "[scope — default: the game runtime (engine/ + game/)]"
allowed-tools: Agent, Artifact, Skill, Read, Write, Glob, Grep, Bash(find*), Bash(wc*), Bash(ls*)
---

Audit the codebase: **$ARGUMENTS**. Ten read-only reviewers, ten disjoint
slices, one consolidated Artifact. **Nothing is edited and no tests are run** —
this skill only reads and reports.

Default scope is the game runtime (`engine/` + `game/`). `editor/`, `tools/`
and `data/` are only in scope when the user names them; say which you excluded.

## Read first (token-light)

Nothing. The main session slices by file inventory; each reviewer reads the ONE
package doc for its own slice (`engine|game|editor/<sub>/CLAUDE.md`). Do not
pre-read architecture you are about to delegate.

## Steps

1. **Inventory, then slice.** `find <scope> -name '*.py' -not -path '*__pycache__*' | xargs wc -l | sort -rn`.
   Cut **10 disjoint slices** balanced by line count, splitting on subsystem
   boundaries and giving any file over ~2k lines its own slice. Every file in
   scope lands in exactly one slice — overlap wastes a reviewer, a gap hides bugs.
2. **Dispatch all 10 `reviewer` agents in ONE message** so they run concurrently.
   Each brief names: its slice (and "do NOT review files outside it — other
   agents own them"); the three categories (correctness **bugs**, **performance**,
   **cleanup**); the ONE package doc to read; `file:line` on every finding; a
   provenance tag per `/report` (measured / verified / inferred); a cap of ~14
   findings, ranked, nitpicks skipped; and a scratchpad path to write its full
   report to. **State explicitly that the agent runs no tests, no `smoke.py` and
   no gate, and makes no edits** — see §"Test Suite Policy" in the root
   `CLAUDE.md` for why a subagent may not, and note the reviewer agent is
   read-only by definition.
3. **Consolidate as the reports land.** Merge into one ranked list; call out
   findings two or more reviewers reached independently (that convergence is the
   most valuable signal the fan-out produces). Where two reviewers disagree,
   list the issue once and say what they actually differed on.
4. **Publish the Artifact** (load `artifact-design` first). Findings live in a JS
   array rendered to DOM, filterable by kind / severity / area, and each issue card carries:
   - a **checkbox** that greys the card out (reduced opacity, strike-through
     title) and marks it handled — persist through `localStorage` in a
     `try`/`catch`, since the sandbox may refuse it;
   - a **copy button** writing the issue's full text (title, `file:line`,
     description, fix, provenance) to the clipboard via `navigator.clipboard`
     with a `document.execCommand` fallback, confirming with a transient
     "Copied" state on the button itself.
5. **Report** per `/report`: the convergent finding first, then the top fixes
   ranked by harm × likelihood ÷ cost, then the Artifact URL and what was
   out of scope.

## Avoid

- **Sequential dispatch.** Ten separate messages serialises a 10-minute job into
  an hour. One message, ten tool calls.
- **Letting a reviewer edit or test.** This is an audit; a fix here is scope
  creep with no branch, no PR and no gate behind it.
- **Publishing ten agent dumps.** The consolidation *is* the deliverable — an
  unmerged pile of reports is the raw output the reader hired you to rank.
- **Treating a report as verified.** Reviewers occasionally over-claim; anything
  tagged **inferred** stays inferred in your report too.

## Verify

No tests. §"Test Suite Policy" in the root `CLAUDE.md` is the only authority on
when tests run, and a read-only audit that changed nothing has nothing to gate.
Confirm instead: all 10 slices reported, slices were disjoint and covered the
scope, every finding carries `file:line` + a provenance tag, and the published
page's checkbox and copy button both work.

## Final report

Slice map and any scope excluded; count of findings by severity; the convergent
findings; the Artifact URL; and whether anything found warrants a durable update
to a package `CLAUDE.md` (report it — do not make the edit from this skill).
