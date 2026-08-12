---
description: Bring every open PR up to date with Development — cross-conflict probe first, then worktree agents that merge, resolve, verify, push and watch CI.
argument-hint: "[PR numbers] — default: every open PR"
allowed-tools: Bash, Agent, Read, Grep, Glob
---

Update the open PRs: **$ARGUMENTS**

Merge `Development` into every open PR, resolve conflicts, verify, push, and
watch CI to a verdict. With no argument this covers every open PR; with numbers
(`/checkallprs 116 117`) it covers only those.

This skill exists because doing it by hand missed two things that cost a full
round trip. Both fixes are Step 1 and Step 3 below — **do not skip them to save
time; they are the reason this file exists.**

---

## Step 0 — Refuse to run on a dirty tree

```bash
git status --short
```

Non-empty → STOP and tell the user. Agents will branch from `origin/*` refs so
uncommitted main-checkout work is not at risk, but a dirty tree here usually
means another session is mid-task, and this skill pushes.

```bash
git fetch origin --prune
gh pr list --state open --limit 50 --json number,headRefName,mergeable,mergeStateStatus \
  -q '.[] | "\(.number)\t\(.headRefName)\t\(.mergeable)\t\(.mergeStateStatus)"'
```

### Step 0b — Clear stale worktree branch locks BEFORE dispatching

**A branch can only be checked out in one worktree at a time.** A leftover
worktree from an earlier round still holds its branch, and the next agent that
tries to work on that branch gets:

```
fatal: 'feature/tile-condition-rework' is already used by worktree at '.../agent-a12149154646f2576'
```

Both agents in the round that produced this skill hit exactly this. Both did the
right thing — branched at the same commit under a scratch name, committed there,
and reported that the PR branch still needed moving — but the result is work
stranded on a side branch that someone then has to fast-forward by hand. Prevent
it instead:

```bash
git worktree list          # which branch is pinned where
git worktree prune         # drop records for directories that no longer exist
```

For each PR in scope, if its branch is held by a **stale agent worktree** whose
work is already committed and pushed, remove that worktree (`/worktreecleanup`,
or `git worktree remove <path>`) before dispatch. If it is held by a worktree
with **uncommitted** changes, or one you cannot account for, do NOT remove it —
leave that PR out of this run and tell the user which worktree is in the way.

If you dispatch anyway and an agent reports the lock, that is a correct report,
not a failure: fast-forward the PR branch onto the agent's scratch commit
yourself, then continue.

## Step 1 — Cross-conflict probe (PR ↔ PR, not just PR ↔ Development)

**This is the step that was missing.** Merging `Development` into N branches in
parallel proves nothing about whether those N branches conflict with *each
other*. It cannot: each agent sees only its own branch. So the moment one PR
lands, every other PR touching the same file flips to `CONFLICTING` — and you
find out after the agents have already reported success.

That happened. PR #119 and PR #117 both touched `tools/tests/test_10j_qol.py`.
Four agents all reported clean merges; #119 landed; #117 immediately went
`DIRTY`. The conflict was **predictable in one command, before any dispatch**:

```bash
git merge-tree --write-tree --name-only <shaA> <shaB>
# exit 0 = clean, exit 1 = conflicts; conflicting paths are listed
```

It needs no worktree, no checkout, and does not touch the index. Run it for
**every unordered pair** of the PRs in scope:

```bash
for a in "${SHAS[@]}"; do for b in "${SHAS[@]}"; do
  [ "$a" \< "$b" ] || continue
  if git merge-tree --write-tree --name-only "$a" "$b" >/dev/null 2>&1
    then echo "CLEAN   $a $b"
    else echo "CONFLICT $a $b:"; git merge-tree --write-tree --name-only "$a" "$b" 2>/dev/null | grep '^CONFLICT' 
  fi
done; done
```

Then build the dispatch plan:

- **Pairs that probe CLEAN** → dispatch in parallel, one worktree agent each.
- **Pairs that probe CONFLICT** → **serialise them.** Dispatch one, let it land
  (or at minimum let it push), then re-probe and dispatch the next against the
  new tip. Never send two mutually-conflicting PRs to concurrent agents: they
  will each resolve against a `Development` that does not yet contain the other,
  and the second one's work is invalidated the moment the first lands.
- Report the matrix to the user **before dispatching** and say which PRs you are
  serialising and why.

Order the serialised chain smallest-conflict-surface first, so the big one
resolves against the most complete tree.

## Step 2 — Dispatch

One agent per PR, **`isolation: "worktree"` on every single one, without
exception.** Concurrent agents sharing a checkout has already produced one
incident in this repo (a `git restore` that reverted a parallel agent's
uncommitted work). A file-scope fence in prose is honour-based; a worktree is
enforced.

Give each agent, verbatim:

- Its branch name and the `origin/Development` SHA to merge.
- **Its test target list, computed by you in Step 3** — not left to its judgement.
- The conflict doctrine (Step 4).
- The hard rules (Step 5).

## Step 3 — Compute each agent's test targets YOURSELF

**This is the other step that was missing.** An agent asked to run "the tests
for the files the merge touched" selects targets from the *textual* diff. That
is wrong whenever a change's blast radius is behavioural rather than textual —
and a `data/` change is always behavioural.

It happened exactly this way on PR #116. Its whole contribution was three files:

```
.claude/commands/add-vfx.md   | 134 +
CLAUDE.md                     |   1 +
data/agent_forms/add-vfx.json |  59 +
```

Zero test files. The agent ran `tools/tests/test_agent_forms.py`, reported
green, and was right about what it ran. CI then failed on the `editor-panels`
shard:

```
FAILED TestSelectorContextMenu::test_category_without_a_spec_offers_no_menu
AssertionError: Lists differ: [('Add New VFX Effect…', 'add-vfx')] != []
```

**There was no local-vs-CI discrepancy. The test was simply never run locally.**
Five other modules read the `agent_forms` roster; the failing one was
`tools/tests/test_editor_panels.py`, which no textual diff would ever surface.

So the orchestrator computes targets, because the orchestrator is the only role
allowed to use the tool that knows:

```bash
py tools/testgate.py check --affected      # main session, mid-task: ALLOWED
```

A subagent may not run `--affected` — the hook denies it — so an agent
**structurally cannot** compute its own blast radius. Do not ask it to.

`--affected` aborts rather than silently widening, so trust its `GATE INFO`
line. When it prints `GATE ABORT`, fall back to naming targets by hand:

1. Every test file in the diff.
2. For every non-test file in the diff, its consumers:
   `graphify affected "<symbol>"`, or for a data file, the crude and reliable
   `grep -rl "<data-dir-or-key>" --include=*.py editor/ game/ tools/tests/`.
3. Map to shards with `tools/ci_shards.py` so you can see which CI shard each
   target belongs to — a target list that touches no editor shard on a change
   that adds a form spec is a target list that is wrong.

Hand the agent the resulting explicit file list. Its allowed commands are then:

```bash
py tools/smoke.py
py -m pytest <the files you were given> -q
```

Never the full suite, never `testgate check`, never `--affected`, never a tier
sweep (`-m core` / `-m editor` / `-m meta`). Run each target once per edit;
re-running an unchanged target is denied and the denial is correct.

## Step 4 — Conflict doctrine (put this in every agent brief)

- **Root `CLAUDE.md` §"Test Suite Policy" / §"Step 2"** — Development wins
  outright; it is the canonical role table. Re-apply the feature's additions to
  the sections around it.
- **Package/subsystem `CLAUDE.md`** — keep Development's `## Verify` block
  (targeted `pytest` line + role note); re-apply the feature's own prose.
- **Test files** — Development de-fragilised tests by *stating the premise* they
  depend on. Keep that pinning; re-apply the feature's assertions on top. If
  either side carries a hardcoded roster, count, or balancing literal, convert
  it to the derived form — that pattern is what put 18 tests permanently red.
- **A test whose premise the feature legitimately deleted** — fix the test to
  derive its premise, or, if the quantity it pinned no longer exists at all,
  remove it and record why in the surviving class docstring. Never weaken the
  feature to satisfy a stale test. Say so loudly in the report either way.
- **Two features' tests in one file** — keep BOTH sides. Independent features do
  not supersede each other; the conflict is positional. Only a genuine semantic
  contradiction justifies picking a winner, and that one goes back to the user.
- **`.test-baseline.json`** — take Development's. Never hand-edit.
- **`data/ui/screen_defaults.json` / `screen_previews.json`, live AND the
  fixture copies** — GENERATED. Never hand-merge, and note they auto-merge
  *silently stale*. Take either side, then regenerate and commit:
  `py tools/export_ui_layouts.py` and
  `py tools/export_ui_layouts.py --data-root tools/tests/fixtures/data`.
  Verify with `git diff --stat origin/Development HEAD -- data/ui/`.
- **`data/balancing/*.json`** — the feature's data intent wins. Fix the TEST to
  state its premise; never revert the designer's data.

## Step 5 — Hard rules for every agent brief

- **Never run destructive git**: no `git reset --hard`, `git clean`,
  `git checkout -- <file>`, `git restore`, `git stash`, no `--amend`, and
  **never `--force`/`--force-with-lease`**. HEAD is not a safe restore point.
  Undo by editing FORWARD.
- **Push is allowed and expected in this skill** (see Step 6) — plain
  `git push` to the PR's own branch, nothing else.
- Do not merge, close, or comment on any PR. Landing is the user's call.
- Never commit `build/`, `dist/`, `*.exe`, `graphify-out/`.
- **Never set `TESTGUARD_OFF`.** A denial means the command was wrong.
- Tests must never write into `data/` — use `TempDataCase`. Never assert against
  live `data/` — pin the fixture.
- `configure_fonts` / `configure_palette` / `configure_strings` mutate module
  globals IN PLACE. Anything that boots the game or calls
  `export_ui_layouts.main()` must restore them or it poisons every later test in
  the same xdist worker — this bug has been found four times. See
  `tools/tests/test_game_boot.py::_restore_font_state_after` and
  `export_ui_layouts._string_table_restored`.
- CI shards run `-n0`. A green local run does NOT prove ordering-independence.

## Step 6 — Push, then read CI correctly

Each agent pushes its own branch when its targets are green. **Stagger the
pushes** — do not let four land in the same few seconds.

Then the orchestrator watches, and this is where the third trap lives:

**A `cancelled` CI job is usually not a broken branch.** This should now be
rare — `.github/workflows/tests.yml` sets
`cancel-in-progress: ${{ github.event_name == 'push' }}`, so pull_request runs
are never evicted. If you see it anyway, that guard has regressed; check the
workflow before blaming the branch.

The failure mode it prevents: for a `pull_request` event `github.ref` is
`refs/pull/N/merge`, and GitHub recomputes that merge ref for **every open PR**
each time the base branch moves. Each recompute enqueues a fresh run in the same
concurrency group; an unconditional `cancel-in-progress` then evicts the run
already in flight:

```
Canceling since a higher priority waiting request for tests-refs/pull/118/merge exists
```

The `gate` job is a pure aggregator with `if: always()`, so it survives, sees
`smoke: cancelled` / `suite: cancelled`, and prints `GATE FAIL` in ~2 seconds.
That looks exactly like a red branch and is not one. Landing three PRs in a row
turned every other open PR red this way, for reasons unrelated to their code.

Before treating any red as real, check what actually executed:

```bash
gh run view <id> --json jobs -q '.jobs[] | "\(.conclusion)\t\(.name)"'
gh api repos/:owner/:repo/actions/runs/<id>/jobs \
  -q '.jobs[] | "\(.name) \(.conclusion) steps_run=\([.steps[]|select(.conclusion!=null)]|length)"'
```

- `suite` shards with `steps_run=0` and a 2–6s `gate` failure → **eviction**.
  The run normally re-dispatches itself under the same run ID; wait and re-read.
  `gh run rerun` will refuse with "already running" — that refusal is the proof.
- A named `FAILED tools/tests/...` line in a `suite` shard → **a real defect.**
  Only then dispatch a fix agent, and put the actual failing test name and
  assertion text in its brief, never a guess.

Read the shard log for the real failure:

```bash
gh run view <id> --log-failed | grep -E "FAILED|AssertionError|passed|failed"
```

## Step 7 — Verify the agents, then report

**Do not trust an agent's own account of whether it pushed.** On the run that
produced this skill, three agents pushed and then reported "I did not push."
Check the refs yourself:

```bash
git fetch origin --prune
git ls-remote origin 'refs/heads/feature/*'
git reflog show origin/<branch> | head -2      # "update by push" is the evidence
```

Also re-run the Step 1 probe after the pushes: PRs that were CLEAN against each
other before may not be now.

Give the user ONE table:

| PR | branch | merge | files resolved | targets run + result | CI verdict | unresolved |

Tag every claim **measured** (command + number) / **verified** (read or ran it)
/ **inferred**, per `/report`. State plainly anything an agent left with
conflict markers in, and anything you could not resolve.

**Do not run the full suite** and do not land anything. The single
`py tools/testgate.py check` and the merge decision both belong to the user.
