---
description: Defer the approved plan to a one-shot cloud routine that executes it at a later time.
argument-hint: <4:30am | +2.5 | +45m>
allowed-tools: Read, Bash(date*), Bash(git remote*), Bash(git rev-parse*), Bash(git ls-remote*)
---

Defer the approved plan to a cloud routine: **$ARGUMENTS**. The routine runs in
Anthropic's cloud on a fresh checkout of this repo — **it cannot see this machine**,
so the plan must travel inside the prompt. Use this right after `ExitPlanMode` is
approved, when the work should land while the user is away.

## Read first
1. The active plan file (path is in the plan-mode system message / the
   `ExitPlanMode` result). That text IS the payload.
2. `CLAUDE.md` §"Working structure" + §"Test Suite Policy" + §"Step 2 —
   Universal exit gate" — all three get restated in the routine prompt, since
   the cloud agent starts blank. The test policy matters most there: an
   unattended agent that re-runs the full suite "to be safe" burns the routine.

## Time grammar
| Input | Mode | Meaning |
|---|---|---|
| `4:30am`, `04:30`, `16:45` | **absolute** | next occurrence of that wall-clock time, local |
| `+2.5`, `+45m`, `+3h` | **relative** | that far from now; a bare number means hours |
| *(omitted)* | — | ask via `AskUserQuestion` |

The leading `+` is the mode switch — that is the whole distinction.

## Steps
1. Parse `$ARGUMENTS` against the table. No argument → ask.
2. **Re-read the clock**: `date -u +%Y-%m-%dT%H:%M:%SZ`. Never infer the date from
   conversation context — a long session makes any earlier anchor stale.
3. Resolve to an RFC3339 **UTC** stamp (user's tz is Europe/Berlin). An absolute
   time already past today rolls to tomorrow. Echo local **and** UTC back before
   creating anything.
4. Build the routine prompt: a self-contained preamble (repo URL, base branch
   `Development`, the C2 agent rules, the exit gate, "**open a PR into
   `Development`; do NOT merge**") + the plan **verbatim** + the caveat below.
5. `ToolSearch select:RemoteTrigger`, then `action: "create"` with `run_once_at`,
   a fresh lowercase v4 uuid for `events[].data.uuid`, `model: "claude-opus-5"`,
   `environment_id: "env_014Fb8WfzXQnhTxMvHePNHGz"`, and
   `allowed_tools: ["Bash","Read","Write","Edit","Glob","Grep"]`.
6. Report the resolved local fire time and `https://claude.ai/code/routines/{id}`.

## Cloud-capability caveat (paste into every deferred prompt)
> You have no display. `py tools/smoke.py` and `py tools/testgate.py check` work;
> `py game/main.py` and `py editor/main.py` do NOT. List every live visual check in
> the PR body under "awaiting your live check" — never claim it as done.

## Avoid
- **Never `CronCreate`** for this — those jobs are session-only and die with the
  session, so a 4:30am wake-up would silently never fire.
- Never point the routine at a local path, or at a branch that was never pushed
  (`git ls-remote --heads origin <branch>` to check; fall back to `Development`).
- Never let the routine merge its own PR, and never grant it a live-run
  verification step it physically cannot perform.

## Verify
- `RemoteTrigger` `action: "get"` on the new id returns the expected `run_once_at`.
- State the resolved local time back to the user.

## Final report
- Routine name, id, link, resolved local + UTC fire time, repo + base branch.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
