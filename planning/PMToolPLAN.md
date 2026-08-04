# PMToolPLAN.md — "Spinner Project Management": a git-native, LLM-first PM tool

> **Status: SPEC + PHASED PLAN. Not yet started. Zero code exists.**
> This document is the agreed specification and build order for a **new,
> separate product** — a project-management tool for *How To Be Human* and
> future projects. It is authored inside the game repo (per the C2 workflow)
> but **the tool is built in its own repository** — **`spinner-project-
> management`** (Spinner Project Management), which Seraphin will create. For now
> this plan lives here in the game repo; it will be moved into that repo once it
> exists. Nothing here targets `game/`, `editor/`, `engine/`, or `data/`. This
> doc is the source of truth until the tool's own repo carries its own `PLAN.md`.
>
> Requirements are numbered `PM-*` (feature/requirement) and phases `P0..P12`.
> When the tool's repo is created, copy this file to its `planning/` and mirror
> it as that repo's active plan.

---

## 0. One-paragraph summary

A **React + TypeScript** web UI (Tailwind + Framer Motion for a clean, modern,
lightly-animated, low-lag feel) backed by a **flat-file git data store** (many
small JSON/Markdown files, one per entity) and driven by a **local companion
process** that owns the working copy, spawns Claude Code on tasks, runs the
tool's own Haiku/Sonnet calls, and **debounce-auto-commits** every edit to a
dedicated data branch with **seniority-ranked conflict resolution**. Identity
is **GitHub** (no bespoke login). The spine is a **WBS builder** that is itself
the structured source of truth, parsed into **epics → user stories → tasks →
subtasks**; every story/epic auto-spawns a "write XP card" task, a completed XP
card auto-generates a `plan.md`, and a task can be handed to a **Claude agent**
(chosen model + effort, plus a responsible human manager) whose work lands as an
**auto-opened PR into the game repo's `Development`**. The design goal is to
spend near-zero time on PM busywork and to **launch Claude on the game without
opening a terminal**.

---

## 1. Goals, non-goals, pillars

### 1.1 Goals
- **G-1** Turn a WBS into a navigable epic/story/task/subtask tree with one
  round-trip of editing, not a data-entry marathon.
- **G-2** Every artifact an LLM needs (task text, XP card, plan, dependency
  graph, roles) is a **plain file on disk**, so agents read the store directly —
  no scraping the app, minimal tokens.
- **G-3** Assign work to **humans or AI agents** from the same board; AI runs
  are one click and produce a reviewable PR.
- **G-4** Give each role the **one view that matters to them** (PM/lead/personal
  dashboards + a personal brief) with zero manual status-chasing.
- **G-5** Make multi-user editing **safe without a server** — auto-sync with
  deterministic, seniority-based conflict resolution.
- **G-6** Be **configurable per project**: pick which tools are enabled, define
  states/departments/estimation at project start.

### 1.2 Non-goals (explicitly out for this iteration)
- **NG-1** Hosting / a cloud backend / real-time CRDT presence server. *Next
  game.* Git is the durable store now; the architecture keeps a clean seam so a
  hosted store can replace the sync engine later (§7.9).
- **NG-2** Open-source / self-hosted models. The tool uses **Haiku** for almost
  everything and **Sonnet** for the blocker analysis; the model layer is
  abstracted so a local model can drop in later, but we don't build that now.
- **NG-3** Real file/media uploads. **External links only** for v1 (§5.6).
- **NG-4** A custom auth system. GitHub identity only (§6).

### 1.3 Pillars (tie-breakers, echoing the game repo's ethos)
1. **LLM legibility over UI convenience** — the on-disk shape is designed for a
   token-cheap agent read first, the UI second. Small single-purpose files;
   schemas over convention.
2. **Data is portable and tool-agnostic** — the UI, the companion, and any agent
   are all just *clients* of the flat-file store. No hidden state lives only in
   the UI.
3. **Deterministic everything** — formatting, ordering, and conflict resolution
   are deterministic and machine-independent, so two people's clones converge to
   byte-identical files.

---

## 2. System architecture

```
                    ┌──────────────────────────────────────────┐
                    │  Browser  (React + TS + Tailwind + Framer)│
                    │  - pure client; never touches git         │
                    │  - talks only to the local companion      │
                    └───────────────▲──────────────────────────┘
                                    │ localhost HTTP + WebSocket (token-authed)
                    ┌───────────────┴──────────────────────────┐
                    │  Local Companion  (Node/TS, per user)     │
                    │  - owns the data-repo working copy         │
                    │  - debounced auto-commit + sync engine     │
                    │  - custom JSON merge driver (seniority)    │
                    │  - spawns Claude Code terminals / headless │
                    │  - runs the tool's Haiku/Sonnet calls      │
                    │  - GitHub identity + API (PRs, roles)      │
                    └───┬───────────────┬───────────────┬───────┘
                        │               │               │
          ┌─────────────▼──┐   ┌────────▼────────┐   ┌──▼───────────────┐
          │ PM DATA REPO    │   │  GAME REPO      │   │ Anthropic API     │
          │ (git, flat files│   │ (Development /   │   │ Haiku (default)   │
          │  on data branch)│   │  PRs from agents)│  │ Sonnet (blocker)  │
          └─────────────────┘   └─────────────────┘   └───────────────────┘
```

- **Browser** renders and edits; all persistence and privileged actions go
  through the companion. This is the seam that lets a *hosted* backend replace
  the companion later without touching the UI (NG-1).
- **Companion** is the only component with filesystem + git + shell + secrets.
  One per user machine. Serves the built web app on `127.0.0.1:<port>` and
  exposes the API/WS (§13). Being local is what makes "spawn a terminal on my
  machine" trivial in v1 (hybrid shape, terminal-now/headless-later).
- **PM data repo** is separate from the game repo. All PM entities live here on
  a dedicated **data branch** (§7.2).
- **Game repo** is only touched for **AI coding runs** (branch + PR into
  `Development`) and for read-only status (CI, PR state) shown on cards.

### 2.1 Stack decisions (locked)
| Layer | Choice | Why |
|---|---|---|
| UI | React 18 + TypeScript + Vite | ecosystem for kanban/timeline/whiteboard, fast HMR |
| Styling/motion | Tailwind + Framer Motion | modern feel + cheap, controllable animation |
| State | TanStack Query (server-state from companion) + Zustand (view/UI state) | clean split of shared data vs per-user view |
| Drag/drop | dnd-kit | kanban, sprint, WBS, timeline dragging |
| Whiteboard | tldraw (embeddable) or excalidraw component | avoid building a canvas from scratch |
| Companion | Node 20 + TypeScript | same language as UI, good git/child-process libs |
| Git | `isomorphic-git` for reads/status + shelling to system `git` for merges/driver | driver + custom merge need real git |
| LLM | Anthropic TS SDK | Haiku default, Sonnet for blocker |

---

## 3. Repository & project layout (the tool's own repo)

```
spinner-project-management/
  apps/
    web/            # React app (built + served by companion in v1)
    companion/      # Node/TS local process: server, sync engine, agent runner
  packages/
    schema/         # zod schemas + TS types for every entity (single source)
    merge/          # the JSON 3-way merge driver + fractional-index lib
    llm/            # model abstraction (Haiku/Sonnet), prompt builders, token meter
    pipeline/       # WBS parse, XP-card gen, plan.md gen, blocker analysis
  planning/PMToolPLAN.md   # this doc, copied over
  README.md
```

The **PM data** is NOT in this repo. It lives in its own git repo (or a data
branch of one) chosen per project (§5.1). The tool code and the tool data are
independent so the same tool binary serves many projects.

---

## 4. Configuration: `project.json` (how "start a new project, pick tools" works)

A project is defined by a single committed file at the data root. The bootstrap
wizard (P11) writes it; nothing else is needed to stand up a project.

```jsonc
// project.json  — the project's constitution
{
  "schema_version": 1,
  "id": "htbh",
  "name": "How To Be Human — Full Production",
  "data_repo": "github.com/SeraphinHesse/HowtobeHuman-pmdata", // or same repo, data branch
  "data_branch": "pm-data",
  "linked_code_repos": [
    { "id": "game", "remote": "github.com/SeraphinHesse/HowtobeHumanFullProd",
      "default_pr_base": "Development" }
  ],
  "enabled_tools": [            // toggles every optional tool (PM-* below)
    "kanban", "sprints", "epics", "wbs", "design_docs", "plans",
    "dashboards", "brief", "blocker", "whiteboard", "timeline",
    "bugs", "enhancements", "ai_runs", "notifications", "activity", "tokens"
  ],
  "workflow_states": ["New","In Progress","Blocked","Ready for Test","Done"],
  "ai_substates": ["Agent Running","Agent Needs Review"],
  "work_unit_for_sprints": "story",      // "story" | "task" — set at project start
  "estimation": {
    "enabled": true, "optional": true,   // points are OPTIONAL
    "scale": "benchmark",
    "anchor": "1 point = writing one A4 design doc based on research + testing"
  },
  "disciplines": [             // WBS work-item tag axis — matches the Miro production board exactly
    "tech","ui-fx","sprite","anim","sound","balance"
  ],
  "priorities": ["MUST","SHOULD","NICE"],   // MoSCoW; the card border color on the board
  "departments": [             // ownership axis (roles/dashboards/notifications), the 9 you named
    "gameplay-tech","engine-tech","sound","ui-art","game-art",
    "game-design","marketing","producing","business"
  ],
  "discipline_department_map": {  // routes a discipline-tagged card to a lead + dashboard (§8.4)
    "tech":"gameplay-tech","ui-fx":"ui-art","sprite":"game-art",
    "anim":"game-art","sound":"sound","balance":"game-design"
  },
  "seniority_ranks": { "pm": 100, "lead": 50, "member": 10 } // conflict policy (§7.4)
}
```

`enabled_tools` is read by the UI to show/hide tools and by the companion to
enable/disable event hooks. For **this** project instance, P11 seeds
`project.json` with everything enabled and pre-loads the current dev status.

---

## 5. Data model — the flat-file store

### 5.1 Directory layout (on the data branch)
```
project.json
roles.json                        # github-handle → roles/departments/leads (§6)
counters.json                     # id allocation high-water marks (§5.3)
epics/<epicId>.json
stories/<storyId>.json
tasks/<taskId>.json
subtasks/<subtaskId>.json
sprints/<sprintId>.json
bugs/<bugId>.json
enhancements/<enhId>.json
docs/xp/<storyId>.md              # XP card (design doc) per story/epic
docs/plans/<storyId>.md           # generated coding plan per story/epic
whiteboards/<boardId>.json        # tldraw/excalidraw document
timeline/<viewId>.json            # timeline bars (date ranges, colors)
comments/<entityId>/<commentId>.json
notifications/<handle>/<notifId>.json
tokens/pm/<yyyy-mm>.jsonl         # PM-tool LLM ledger (append-only, §11)
tokens/game/<yyyy-mm>.jsonl       # game coding-agent ledger (append-only, §11)
.pm/conflicts/<uuid>.json         # conflict-override records (§7.6)
.pm/agents/<runId>.json           # AI run records (§9.4)
.gitattributes                    # binds *.json entities to the merge driver
```

**One entity = one file** is the core decision: it means two people editing
different entities produce commits that git merges with **zero** content
conflict (disjoint file sets), so the only real conflicts are same-entity edits,
which the driver resolves field-by-field (§7).

### 5.2 The entity envelope (every JSON entity)
Every entity file is `{ "_meta": {...}, ...domain fields }`:

```jsonc
{
  "_meta": {
    "id": "STORY-0042",
    "type": "story",
    "rev": 7,                       // monotone per entity, bumped on each write
    "created_by": "seraphinhesse",
    "created_at": "2026-08-04T10:11:00Z",
    "updated_by": "seraphinhesse",  // drives seniority conflict policy (§7.4)
    "updated_at": "2026-08-04T12:33:04Z",
    "order": "0|hzzzzz:"            // fractional index among siblings (§7.5)
  },
  // ...domain fields (see 5.4)
}
```

`updated_by`/`updated_at` are the **conflict inputs**; `order` is the fractional
sort key; `rev` supports optimistic-concurrency detection in the UI. Timestamps
are UTC ISO-8601; the companion is the only writer, so clocks are that machine's,
and ties are broken deterministically (§7.4) rather than trusting clocks.

### 5.3 IDs
Human-legible, type-prefixed, zero-padded, monotonic: `EPIC-0007`,
`STORY-0042`, `TASK-0311`, `SUB-0090`, `SPR-0004`, `BUG-0021`, `ENH-0012`. The
next number per type lives in `counters.json`. Allocation is **conflict-prone by
nature** (two people create a story at once → both grab 42); mitigation in §7.7
(client-side ULID shadow id + rename-on-merge, or reserve-ranges per user).

### 5.4 Domain schemas (abridged; full zod in `packages/schema`)
All entities share: `title`, `description` (Markdown), `assignees[]` (github
handles), `attachments[]` (external URLs, §5.6), `links[]`, and — mirroring the
production board's two axes — `discipline` (one of `disciplines`) and
`priority` (MoSCoW, one of `priorities`). `discipline` is what the board calls
the card's *fill color*; `priority` is its *border*; `discipline` also routes
the item to a department/lead via `discipline_department_map` (§8.4).

- **Epic** `{ color, story_ids[], department }` — a board *section* (`#8f7fee`).
- **Story** `{ epic_id, state, task_ids[], acceptance_criteria[], points?,
  priority, xp_card_path, plan_path, dependencies{ blocks[], blocked_by[] } }`
  — a board *feature block* (`#6631d7`). The board has **32** of these.
  - `points?` optional (estimation.optional). `acceptance_criteria[]` = list of
    `{id, text, done}`.
- **Task** `{ parent_type:"story"|"epic", parent_id, state, subtask_ids[],
  discipline, priority, points?, assignment: HumanOrAI, dependencies{...} }`
  — a board *work-item card* (Tech/UI-FX/Sprite/Anim/Sound/Balance).
- **Subtask** `{ task_id, state, assignment }`
- **Assignment** (`HumanOrAI`):
  ```jsonc
  { "kind": "human", "handle": "alice" }
  // or
  { "kind": "ai",
    "model": "haiku|sonnet|opus", "effort": "low|medium|high|max",
    "manager": "bob",            // human responsible for the agent
    "run_id": "RUN-0007" }       // links to .pm/agents/<runId>.json
  ```
- **Sprint** `{ start, end, item_type:"story"|"task", item_ids[], goal }`
- **Bug** `{ severity, status, repro, expected, actual, source:"form"|"chat",
  linked_entity? }`
- **Enhancement** `{ target_entity_id, rationale, size, status }`
- **XP card** = `docs/xp/<id>.md` — a **structured** doc in the team's supplied
  template (§5.8), YAML front-matter + fixed sections. Authored by **filling out
  the template form in the tool**, freehand Markdown, or Claude-assisted — all
  three write this one file (§12.6).
- **Plan** = `docs/plans/<id>.md` (generated from the XP card, §8.3).

### 5.5 Dependency edges (feed the blocker tool)
Stored **denormalized on both endpoints** (`blocks[]` / `blocked_by[]`) for
cheap UI reads, but the **canonical** edge set is derivable and the blocker
analysis (§12.9) rebuilds/validates it. Edge = `{from, to, type:"blocks",
created_by}`. Set-merge semantics (§7.5) make concurrent edge edits union
cleanly.

### 5.6 Attachments (external links only, v1)
`attachments[] = [{ id, label, url, added_by }]`. No bytes in git. A later
milestone swaps this for real upload against a blob store (NG-3).

### 5.7 Formatting (deterministic, non-negotiable)
Every JSON write goes through **one writer**: UTF-8, `\n` newlines, 2-space
indent, **keys sorted**, arrays in canonical order (fractional-index order for
ordered lists, id-sorted for sets), trailing newline. This guarantees the merge
driver diffs cleanly and two machines produce byte-identical files. (Mirrors the
game repo's "validating, deterministic writer" rule.)

### 5.8 XP-card structure (the team's supplied template)
The XP card is a **fixed-shape** doc so designers can fill it in like a form and
so an LLM (or the auto-plan generator) can read any section by name. On disk it
is `docs/xp/<id>.md`: readable YAML front-matter for the header/metadata, then
the template's sections as `##` headings (empty sections are allowed and render
as prompts in the form). The form UI (§12.6) is a two-way binding over exactly
these fields — editing the form writes the file, editing the file re-hydrates the
form.

```markdown
---
epic: "X.0 <Epic name>"          # header row on the card
user_story: "EPIC#.X <story>"    # the feature block this card explains
last_update: 2026-08-04
date: 2026-08-04
change: "<what changed this revision>"
author: "<name / github handle>"
status: draft                    # draft | ready  (ready → auto-plan, §8.3)
---

## Intention | Requirements
- What is the point of this feature?
- What does this feature do in general terms?
- What needs to happen in game for this feature to happen?
- What requirements must the player meet?

## Player Interaction
- How does the player interact with this feature?

## World / Feature / Physics Interaction
- How does this feature interact with other game features?

## Vision Statement (Feel)
- How is this feature supposed to make the player feel?
- How does it align with the overall feeling of the game?

## References
<!-- table: Media | Mechanic | Description | Picture -->
- Similar mechanics from other games; visual references from film / art / media.

## Required Feedback
- **Animations:** which animations & FX are needed to bring the feature to life?
- **Sound:** which sound FX are needed?

## Balancing Variables
- List every number / data point that can be tuned in balancing
  **[with a suggested value]**.

## Mechanic Description
- Room for more notes.

## Sketch
<!-- optional external image link (§5.6) -->
```

This mirrors the uploaded *XP card template* one-to-one. The `## References` and
`## Sketch` blocks may carry external media links (§5.6). The **Balancing
Variables** section is deliberately structured — the auto-plan step (§8.3) reads
it to pre-list the tunables the coding plan must expose.

---

## 6. Identity & permissions

### 6.1 Identity = GitHub, no login screen
The companion resolves the current user from local GitHub credentials
(`gh auth token` / a stored OAuth token via device flow the first run) and calls
the GitHub API `GET /user` to get the handle. The browser gets identity from the
companion; there is no username/password UI. (Matches the "fully GitHub" call.)

### 6.2 `roles.json`
```jsonc
{
  "departments": [
    { "id":"gameplay-tech", "name":"Gameplay Tech", "lead":"alice" },
    { "id":"engine-tech",   "name":"Engine Tech",   "lead":"bob" },
    { "id":"sound", "lead":"carol" }, { "id":"ui-art", "lead":"dan" },
    { "id":"game-art", "lead":"eve" }, { "id":"game-design", "lead":"seraphinhesse" },
    { "id":"marketing", "lead":"..." }, { "id":"producing", "lead":"seraphinhesse" },
    { "id":"business", "lead":"..." }
  ],
  "users": [
    { "handle":"seraphinhesse", "roles":["pm","lead:producing","lead:game-design",
      "member:business"], "display":"Seraphin" },
    { "handle":"alice", "roles":["lead:gameplay-tech","member:engine-tech"] }
  ]
}
```
- A user can hold **many roles**; departments each have exactly one **lead**.
- Roles map 1:1 to `departments`; a board **discipline** routes to a department
  via `discipline_department_map` (a *Sprite/Anim* card ↔ `game-art` ↔ its
  members), so disciplines, roles, and the WBS stay coordinated (§8.4).
- **Seniority rank** of a user = max over their roles using
  `project.json.seniority_ranks` (`pm` 100 > any `lead:*` 50 > `member:*` 10).
  This single number drives conflict resolution (§7.4).

### 6.3 Permission matrix
| Action | PM | Lead | Member | AI agent |
|---|---|---|---|---|
| Edit **WBS** structure (add/move/delete epics/stories) | ✅ | ✅ | ❌ | ❌ |
| Edit task/subtask fields, move on kanban | ✅ | ✅ | ✅ (own/dept) | via manager |
| Assign work to a human | ✅ | ✅ (dept) | ❌ | — |
| Assign work to an **AI agent** | ✅ | ✅ | ✅ (with a manager) | — |
| Edit `roles.json` / departments / leads | ✅ | ❌ | ❌ | ❌ |
| Approve/merge an agent PR | ✅ | ✅ (dept) | ❌ (manager only) | ❌ |
| See token usage (both ledgers) | ✅ | ✅ | ✅ | — |

Permissions are **enforced in the companion** (the only writer), not just hidden
in the UI. A denied write returns a structured error the UI surfaces. WBS-edit =
PM + leads only, as specified.

---

## 7. Sync engine & conflict resolution  *(the technical core)*

### 7.1 Debounced auto-commit
The companion watches the working copy (chokidar) **and** receives explicit
"entity changed" events from the UI. On change it:
1. runs the entity through the deterministic writer (§5.7) and bumps
   `_meta.rev`, `updated_by`, `updated_at`;
2. **debounces**: coalesce edits until **750 ms idle** or **5 s max** since the
   first pending change;
3. `git add` the touched files and commit with a structured message
   `pm: <actor> <verb> <ids>` (feeds the activity feed, §12.13);
4. hands the commit to the **sync worker** (7.3).

No manual save/push anywhere — exactly the "users don't push manually" ask.

### 7.2 Branch model
All PM data lives on one long-lived **data branch** (`pm-data`). Everyone commits
to it and syncs. No feature branches for data (they'd defeat the "always-fresh
for the LLM" goal). History is an append-only stream of small merges; the tool
never rebases the shared branch.

### 7.3 Sync worker (push loop with lease + backoff)
```
loop (triggered after each local commit, and on a 20s heartbeat):
  git fetch origin pm-data
  if remote is ahead:
      git merge origin/pm-data        # uses the custom driver (7.4) — never stops for manual resolve
  git push origin HEAD:pm-data --force-with-lease
  on push-rejected (someone pushed in between):
      backoff 0.5s,1s,2s,4s… fetch+merge+push again (max ~6 tries)
```
Because the merge driver **always resolves** (exit 0) and is **deterministic**,
`git merge` never drops into a conflicted state requiring a human. `--force-with-
lease` protects against clobbering an unseen push (the lease fails → we re-fetch).

### 7.4 The custom JSON merge driver (seniority-ranked, deterministic)
`.gitattributes` binds every entity path to a driver:
```
epics/*.json   merge=pmjson
stories/*.json merge=pmjson
tasks/*.json   merge=pmjson
...            merge=pmjson
```
`git config merge.pmjson.driver "pm-merge %O %A %B %P"`. The driver
(`packages/merge`) does a **recursive 3-way merge** of base `%O`, ours `%A`,
theirs `%B`:

```
merge3(base, ours, theirs, schemaNode):
  # leaves
  if all scalars:
    if ours == theirs: return ours
    if ours == base:   return theirs        # only theirs changed
    if theirs == base: return ours          # only ours changed
    return resolveConflict(ours, theirs, oursMeta, theirsMeta)   # both changed

  # objects: union keys, recurse (missing side = base's value)
  if objects:
    return { k: merge3(base[k], ours[k], theirs[k], schemaNode[k]) for k in keys }

  # arrays: semantics come from the schema node
  if array and schemaNode.kind == "set":     # tags, dependency edges, criteria
    return unionById(base, ours, theirs, recurse=merge3)   # element conflicts recurse
  if array and schemaNode.kind == "ordered": # kanban order, sprint order
    return mergeByFractionalIndex(base, ours, theirs)      # 7.5
  # fallback: whole array is a value
  return resolveConflict(ours, theirs, oursMeta, theirsMeta)
```

**`resolveConflict` is commutative** — it decides purely from author metadata,
never from the ours/theirs *position*, so both sides of the merge (and every
machine) compute the same winner:
```
resolveConflict(a, b, aMeta, bMeta):
  ra, rb = rank(aMeta.updated_by), rank(bMeta.updated_by)   # §6.2, from roles.json
  if ra != rb:      winner = higher-rank side               # PM > lead > member
  elif aMeta.updated_at != bMeta.updated_at:
                    winner = later timestamp
  else:             winner = side whose updated_by sorts greater  # final deterministic tie-break
  log override(loser value, winner value, reason) → .pm/conflicts/<uuid>.json   # 7.6
  return winner.value
```
`rank()` reads the **merged `roles.json`** (roles is itself an entity; it merges
first because the driver loads a fresh copy at process start). Result: a
**producer's edit beats a lead's beats a dev's**, ties fall to newest, final ties
are deterministic — no human ever hand-resolves a data conflict.

> Determinism proof-obligation (P1 test): for any base/ours/theirs,
> `merge3(base,ours,theirs) == merge3(base,theirs,ours)` byte-for-byte. This is
> what guarantees clones converge.

### 7.5 Ordered lists & fractional indexing
Sibling order (kanban column order, WBS sibling order, sprint order) uses a
**fractional index string** (LexoRank/`fractional-indexing` style) stored in
`_meta.order`. Inserting between A and B mints a key strictly between them;
moving one card rewrites **only that card's** `order`. Concurrent inserts at the
"same" slot yield two adjacent-but-distinct keys → both survive, ordered
deterministically; identical keys (astronomically rare) tie-break by id. Net:
reordering essentially never hard-conflicts.

### 7.6 Conflict transparency (nothing is silently lost)
Each override writes `.pm/conflicts/<uuid>.json`:
`{ entity, field_path, kept:{value,by,at}, dropped:{value,by,at}, reason, at }`.
Unique filename ⇒ these records themselves never conflict (union-merge). The UI
shows a **"Sync conflicts" tray**: "Your change to STORY-0042 title was
superseded by Seraphin (PM)." The dropped value is preserved so it can be
re-applied manually. Overrides also surface in the activity feed (§12.13).

### 7.7 ID-allocation races
Two users creating an entity offline can grab the same `STORY-0042`. Mitigation:
the UI mints a client-side **ULID** as the *real* key at creation; the friendly
`STORY-00xx` number is assigned by the companion from `counters.json` and, on a
merge collision, the **lower-rank/later** creator's entity is auto-renumbered
(its file renamed, references updated) by a post-merge fixup pass. `counters.json`
uses a set of `{handle: high_water}` so its own merge is a per-key max, never a
conflict.

### 7.8 Offline & catch-up
The companion queues commits offline; on reconnect it runs the sync worker
(7.3). Because merges are deterministic and commutative, a long offline stretch
resolves the same as if edits had been live.

### 7.9 The hosting seam (future, NG-1)
Everything above lives behind a `SyncBackend` interface (`read(entity)`,
`write(entity)`, `subscribe(onChange)`, `resolveConflict(...)`). The git
implementation is `GitFlatFileBackend`. A future hosted backend implements the
same interface; the UI and pipeline don't change. Kept explicit so "we'll host it
next game" is a backend swap, not a rewrite.

---

## 8. The planning pipeline (WBS → structure → XP card → plan)

### 8.1 WBS builder is the source of truth (PM-WBS)
The visual WBS builder **is** the structured data — nodes are epics/stories/
tasks/subtasks written straight to the flat files, colored on two axes: **fill =
discipline** (Tech/UI-FX/Sprite/Anim/Sound/Balance) and **border = MoSCoW**
(MUST/SHOULD/NICE).

> **Miro is retired.** The production board was exported from Miro **once**; from
> then on this WBS builder is the **sole** workflow — there is no ongoing Miro
> sync, and nothing depends on re-opening the Miro board. The export files below
> are a one-time seed, not a live source.

"Parsing" only matters for the **one-time seed import**:
- **Structure (epics) comes from `docs/Feature list.pdf`** — it groups the ~44
  features into **6 gameplay epics**: **Buildings** (13 stories), **Enemies &
  Combat** (8), **Map** (5), **Progression** (7), **UI** (10), **Effects** (1).
  These become the epic layer (§19.1).
- **Stories + tasks come from `docs/PRODUCTION_BOARD.md`** (the Miro export: 32
  feature blocks / ~1010 discipline-tagged, MoSCoW cards). The `pipeline` package
  ships a **deterministic parser**: each `### <Feature block> · *PRIORITY*` →
  **Story**; each table row → **Task** with `discipline` + `priority`; the Legend
  defines the taxonomy. Stories are parented into the 6 epics by name; any
  feature in the status docs but absent from the 32-block export (e.g. Storm
  Priest, Game Over, Decoration) is created as a story from `FEATURE_STATUS.md`.
- **Current state comes from `docs/FEATURE_STATUS.md`** — its Logic/Art/Audio
  columns set each item's initial workflow state instead of all-New (§15, §19).
- **Beyond gameplay**, the seed also creates the **Engine**, **Editor**, and
  **PM Tool** epics (§19.2–19.4).
- **Secondary import paths** (for future projects): an indented outline
  (Markdown/YAML) or a spreadsheet, parsed the same way. After any import the
  builder owns the data — no external board.
- WBS edits (structure) are **PM + leads only** (§6.3); anyone can edit leaf
  fields per their scope.

### 8.2 Auto "write XP card" task (PM-XP-AUTO)
On creation of any **story or epic**, an event hook in the companion auto-creates
a linked task **"Write XP card for `<id>`"** (tagged to the owning department,
unassigned). This is a data mutation like any other (auto-committed, synced). It
is **idempotent**: keyed on `xp:<id>` so re-runs don't duplicate it, and it
auto-closes when `docs/xp/<id>.md` gains real content.

### 8.3 XP card → auto plan.md (PM-PLAN-AUTO)
The **design-doc creator** (§12.6) produces `docs/xp/<id>.md` — by a designer
filling out the template form by hand, or via a Claude conversation (Haiku), or
a mix. On XP-card completion (front-matter `status: ready`), a
hook enqueues an LLM job that reads the XP card + the story's acceptance criteria
+ linked code-repo context and writes `docs/plans/<id>.md` — a detailed coding
plan in the game repo's plan-doc house shape (phases, file scope, verify gate).
Both files are just Markdown in the store; the story's `xp_card_path` /
`plan_path` point at them, and the UI shows **"Open XP card"** / **"Open plan"**
buttons on the story.

### 8.4 Discipline / department / WBS consistency (PM-TAGS)
Two coordinated axes, one taxonomy each, no free-text tags:
- **Discipline** (§4 `disciplines`) is the **work axis** — the board's fill
  color (Tech/UI-FX/Sprite/Anim/Sound/Balance). The UI only offers these; every
  card carries exactly one.
- **Department** (§4 `departments`, §6.2) is the **ownership axis** — the 9
  roles/leads. A card's department is **derived from its discipline** via
  `discipline_department_map` (e.g. an *Anim* card → `game-art` → Eve's
  dashboard + notifications), and can be overridden per item when a card crosses
  disciplines. Marketing/Producing/Business are departments with no board
  discipline (they own non-board work: sprints, briefs, business tasks).
- **MoSCoW priority** (§4 `priorities`) is the board's border color, a
  first-class field on stories and tasks (drives sort, filters, the blocker's
  "unblock MUST-first" ordering).
Defined once in `project.json`, consumed by the WBS colors, kanban filters,
dashboards, and notification routing — no drift.

---

## 9. AI integration (launch Claude without opening a terminal, mostly)

### 9.1 The spawn contract
Assigning a task to an AI (`Assignment.kind == "ai"`) and pressing **Run** posts
to the companion `POST /agent/spawn`:
```jsonc
{ "task_id":"TASK-0311", "model":"sonnet", "effort":"high",
  "manager":"alice", "mode":"terminal"|"headless" }
```
The companion builds a **run context** = task description + the story's XP card +
`plan.md` + acceptance criteria + linked-repo remote + the branch name to use,
and:
- **v1 `terminal` mode**: opens a real terminal running Claude Code in the game
  repo clone, pre-seeded with the context as the opening prompt and the target
  branch checked out. (This is the "for now, just launch the terminal" path.)
- **`headless` mode (later)**: runs Claude Code / Agent SDK headless and streams
  events to the UI's run panel — no visible terminal. The run context is
  identical, so terminal→headless is a mode flag, not a redesign
  (your "both — terminal now, headless later" choice).

### 9.2 Branch + PR flow
Each run works on `pm/<task-id>-<slug>` off `Development` and, on completion,
**auto-opens a PR into `Development`** (matching the game repo's existing
branch→PR→CI flow). The card moves **New → Agent Running → Ready for Test**; the
PR URL + CI status are shown on the card (read via the GitHub API). The **human
manager** is the PR reviewer/merger.

### 9.3 Model + effort
Per-task pick of **model** (`haiku`/`sonnet`/`opus`) and **effort**
(`low`→`max`), stored on the assignment. A human **manager** is mandatory for AI
tasks (your requirement): they own review/merge and appear on the card.

### 9.4 AI-run monitor ("My Agents", PM-AIMON)
`.pm/agents/<runId>.json` records `{task_id, model, effort, manager, mode,
branch, pr_url, state, started_at, ended_at, ci_status, tokens_in, tokens_out}`.
The **My Agents** view lists every run with live status, links to the terminal/
stream and the PR, and the token cost (§11). Essential once cards can launch
agents.

### 9.5 Token capture — honest limits
- **Headless mode** yields exact usage from the SDK response → written to the
  game ledger (§11) precisely.
- **v1 terminal mode** can't always intercept usage cleanly; the companion
  captures what Claude Code reports (session usage), else records an
  **estimate flagged `approx:true`**. Precision arrives with headless mode. This
  limitation is called out so the token dashboard never over-claims.

---

## 10. The tool's own LLM usage (token-frugal)

- **Default model: Haiku** for WBS parsing, XP-card conversation, plan.md
  generation, personal-brief synthesis, bug intake, notification summaries.
- **Sonnet only** for the **blocker dependency analysis** (§12.9), where
  reasoning over the whole graph benefits from a stronger model.
- **Agents read the flat files directly** — the pipeline hands the model **file
  paths / small file contents**, not scraped UI state, and never the whole
  store. This is the point of the flat-file design (G-2): minimal tokens, code
  budget preserved. The `llm` package centralizes model choice so a local model
  can replace Haiku later (NG-2) without touching callers.

---

## 11. Token tracking (two ledgers, per-user, visible to all)

Two **append-only JSONL** ledgers, monthly-rotated:
- `tokens/pm/<yyyy-mm>.jsonl` — the **PM tool's own** Haiku/Sonnet spend.
- `tokens/game/<yyyy-mm>.jsonl` — the **game coding agents'** spend (§9.5).

Each line: `{ ts, user, scope:"pm"|"game", model, purpose, tokens_in,
tokens_out, approx?, ref }`. Append-only + unique lines ⇒ ledgers **union-merge**
with zero conflict. A **Token dashboard** (PM-TOKENS) shows per-user and
per-scope totals, **visible to everyone** (your requirement), with the game vs
PM split kept separate so "tokens spent building the tool" never muddies "tokens
spent building the game."

---

## 12. Tool specs (each optional, gated by `enabled_tools`)

### 12.1 Kanban (PM-KANBAN)
Columns = `workflow_states` (+ AI substates). Cards = stories/tasks. Drag =
dnd-kit; position persists via fractional `_meta.order`. Card front shows title,
tags (colored), assignees/avatars, points (if set), blocker badge, PR/CI badge
for AI runs. Card back (detail drawer): description (Markdown), acceptance
criteria checklist, external attachments, dependency editor, **Open XP card /
Open plan** buttons (stories), **Assign to AI** (model+effort+manager) and
**Run**. Filter by department/tag/assignee/sprint.

### 12.2 Sprints (PM-SPRINTS) + estimation
Drag `work_unit_for_sprints` items into sprint lanes (Taiga/Jira feel). Sprint =
`{start,end,goal,item_ids}`. **Estimation is optional**, benchmark-anchored
(1 pt = one researched+tested A4 design doc); velocity = summed points of Done
items per sprint, shown only when points are used.

### 12.3 Timeline builder (PM-TIMELINE)
Whiteboard-like canvas: drag an epic/story onto it, drag its start/end handles to
set dates; bars **color-coded by epic**. Stored in `timeline/<viewId>.json` as
`{bars:[{entity_id, start, end, color, row}]}`. Dates here can (optionally)
write back to the entity, or stay view-only — configurable.

### 12.4 Whiteboard (PM-WB)
Embedded tldraw/excalidraw; each board = one document file. Freeform ideation;
can drop links to entities. (No conflict driver — whiteboard docs use the
library's own store, snapshotted into git on debounce; last-writer-by-seniority
at the document level.)

### 12.5 WBS builder (PM-WBS) — see §8.1
Color-coded tree matching your existing WBS (fill = discipline, border = MoSCoW);
PM/leads edit structure.

**MoSCoW composition readout.** The builder computes, live, the **percentage of
each MoSCoW priority** (MUST / SHOULD / NICE, plus an `unset` bucket) as a
share of items — shown as a stacked bar + numbers, recomputed on every edit. It
is available at multiple scopes:
- **whole project** (the board headline — e.g. the current seed skews NICE-heavy:
  MUST 151 · SHOULD 353 · NICE 464 · unset 42 across ~1010 cards);
- **per epic** and **per selected subtree** (select any node → its descendants'
  split);
- **counted by items by default, or weighted by points** when estimates exist
  (§12.2) — a toggle, since a NICE-heavy *count* can still be a MUST-heavy
  *effort*.
Percentages are a pure derived view (no stored state); the same helper feeds the
dashboards' scope-composition widgets (§12.8) so the number is identical
everywhere. Useful as a scope-balance gut-check ("are we over-investing in NICE
before MUST is done?").

### 12.6 Design-doc / XP-card creator (PM-XP)
**Three co-equal authoring modes over one file** (`docs/xp/<id>.md`, §5.8) —
manual is the default; AI is optional assist, never required:
1. **Template form (primary).** A structured form with the exact template
   sections (Intention/Requirements, Player Interaction, World/Feature/Physics,
   Vision/Feel, References, Required Feedback → Animations/Sound, Balancing
   Variables, Mechanic Description, Sketch) plus the header/metadata row.
   Designers **fill it out themselves**; each field two-way-binds to its `##`
   section so saving the form writes the Markdown and opening an existing card
   re-hydrates the form. Empty sections render as greyed prompts (the template's
   guiding questions) — you can complete a card entirely by hand, no LLM.
2. **Raw Markdown.** Toggle to edit the file directly (same file), for people who
   prefer writing prose; also what a Claude Code terminal edits.
3. **Claude-assisted (optional).** A chat side-panel: give notes and Haiku drafts
   or fills sections *into the same form*, which you then edit/approve. Assist,
   not autopilot.

Front-matter `status: draft|ready` drives the auto-plan hook (§8.3); flipping to
`ready` is an explicit human action regardless of authoring mode.

### 12.7 plan.md creator (PM-PLAN) — see §8.3
Auto on XP-card `ready`, re-runnable on demand.

### 12.8 Dashboards (PM-DASH) — **role-scoped**
One view engine, three scopes:
- **PM/producer**: project-wide health (state counts, sprint burndown, blocked
  items, active AI runs, token spend) **plus** their own personal tasks — the
  producer also carries department tasks (game-design/producing), so their
  dashboard is project + personal.
- **Lead**: identical shape to the PM dashboard but **filtered to their
  department** only (their team's stories/tasks/agents/blockers) — not the whole
  project.
- **Member**: personal — my tasks, my AI runs, my mentions, my sprint.
Scope is derived from the viewer's roles (§6.2).

### 12.9 Blocker tool (PM-BLOCK) — Sonnet
A button that spawns a **Sonnet** agent to read the dependency edges + task
states + descriptions and report **which tasks block which** — validating the
declared `blocks/blocked_by`, inferring *undeclared* blocks from the text, and
returning an ordered "unblock this first" list + a rendered graph. Output is
written back as edge suggestions (accept/dismiss) and a report entity. Sonnet
(not Haiku) because it reasons over the whole graph.

### 12.10 Personal brief (PM-BRIEF)
A **daily**, Haiku-generated narrative digest for the individual: "what's on you
today, what changed, what's blocked on you, what your agents did overnight, what
needs review." Distinct from the live dashboard (the dashboard is the
at-a-glance board; the brief is the written summary). Both exist (your call).

### 12.11 Bugs (PM-BUGS)
Report via a **form** (severity/repro/expected/actual) **or** by **describing it
to Claude**, which fills the form. Bugs link to entities and can spawn a fix
task/AI run.

### 12.12 Enhancements (PM-ENH)
Lightweight planner for small changes to existing stories/epics; each enhancement
targets an entity, carries rationale + size, and can graduate into a task.

### 12.13 Notifications & @mentions (PM-NOTIF) + Activity feed (PM-ACT)
- **Notifications**: `notifications/<handle>/…`; routed on assignment, mention,
  **"Agent needs review"** (pings the manager), state change on watched items,
  and **sync overrides** (§7.6). @mention anyone on any item.
- **Activity feed**: the **git commit log of the data branch**, rendered as a
  human timeline ("who changed what, when") — nearly free, since every edit is
  already a structured commit (§7.1).

---

## 13. Web UI ↔ Companion contract (localhost, secure)

Companion serves the built web app and a JSON API on `127.0.0.1:<port>`, guarded
by a per-launch **bearer token** (written to a file only the local user can read;
the served page reads it). Bound to loopback only. Key endpoints:
```
GET  /identity                     → {handle, roles, rank}
GET  /entities/:type               → list (from working copy)
GET  /entity/:id                   → one
PUT  /entity/:id                   → validated write (permission-checked) → debounced commit
POST /wbs/import                   → parse outline/sheet → entities
POST /agent/spawn                  → §9.1 ; GET /agent/:runId , WS /agent/:runId/stream
POST /xp/:id/generate-plan         → §8.3
POST /blocker/run                  → §12.9 (Sonnet)
GET  /sync/status                  → {ahead, behind, last_push, conflicts[]}
GET  /tokens/:scope                → aggregated ledger
WS   /events                       → live entity-changed / sync / notification push
```
All privileged actions (git, shell, GitHub API, Anthropic API, secrets) live in
the companion; the browser is a pure client. This boundary is also the hosting
seam (§7.9).

---

## 14. Liquid UI (LAST, nice-to-have)

Per-user layout/appearance (panel arrangement, density, theme, which widgets on a
dashboard) stored **per GitHub handle** in a **user-scoped prefs file** that is
**never** part of shared entity data and **never** affects how data is processed.
Changing your layout changes only your view. Explicitly the **final milestone**,
built only after everything functional is done.

---

## 15. Bootstrapping this project (P11)

The **New Project wizard** writes `project.json` (tool toggles, states,
disciplines, priorities, departments, estimation, ranks) and `roles.json`. For
**this** instance it seeds:
- every tool enabled;
- the discipline taxonomy (Tech/UI-FX/Sprite/Anim/Sound/Balance) + MoSCoW
  priorities + the 9 departments/leads + the discipline→department map;
- **the real WBS**, parsed from `docs/PRODUCTION_BOARD.md` (§8.1): 32 stories /
  ~1010 discipline-tagged, MoSCoW-prioritized tasks;
- **current dev status** cross-walked from `docs/FEATURE_STATUS.md` + the game
  repo (open PRs, `Development` state, active `planning/` docs) so cards start at
  the right workflow state instead of all-New — the board reflects reality on
  day one.

---

## 16. Risks & mitigations
| Risk | Mitigation |
|---|---|
| Git as a live store feels laggy for multiplayer | debounce + small files + `/events` WS for optimistic UI; hosting seam later (NG-1) |
| Merge driver non-determinism → divergent clones | commutative `resolveConflict`; P1 property test (§7.4) |
| ID races on offline creation | ULID real-key + renumber-on-merge (§7.7) |
| Terminal-mode token capture imprecise | flag `approx`, exact in headless (§9.5) |
| Data-branch history bloat | squash/rotate policy; ledgers monthly-rotated |
| Secrets in the data repo | companion holds tokens; nothing secret is ever written to the store |

---

## 17. Inputs — PROVIDED

Both content inputs are now in hand and encoded above:
1. **XP-card format** — the uploaded *XP card template*, transcribed section-for-
   section into §5.8 and wired as the template form (§12.6).
2. **The real WBS** — `docs/PRODUCTION_BOARD.md` (the Miro production board: 32
   feature blocks / ~1010 cards, discipline + MoSCoW). It is the seed for P2/P11
   and defines the discipline + priority taxonomies (§4, §8.1, §15).

3. **Epic grouping** — `docs/Feature list.pdf`: the 6 gameplay epics (§19.1).
4. **Current state** — `docs/FEATURE_STATUS.md` (Logic/Art/Audio per feature),
   used to seed initial workflow states (§15, §19).

The full seed tree — all **9 epics** (6 gameplay + Engine + Editor + PM Tool),
their stories, and task patterns — is enumerated in **§19**.

Repo name is decided: **`spinner-project-management`** (Seraphin creates it and
moves this plan over). *Miro is not an open item — it is retired
(§8.1); no future workflow touches it.*

---

## 18. Phased build plan

Base: the tool's own repo; each phase is independently shippable and ends at a
green check (typecheck + unit tests + a named manual scenario). Dependencies in
brackets.

- **P0 — Scaffold & seam.** Monorepo (§3), Vite React app, companion server on
  localhost + bearer token, `schema` package with zod for the envelope +
  `project.json` + `roles.json`, CI (typecheck/lint/test). *Verify:* app loads,
  `/identity` returns the GitHub handle.
- **P1 — Data store, writer, merge driver, sync engine.** [P0] Deterministic
  writer (§5.7); `merge` package with the 3-way seniority driver (§7.4),
  fractional indexing (§7.5), conflict logs (§7.6); debounced auto-commit + sync
  worker (§7.1–7.3); `.gitattributes` wiring. *Verify:* **the determinism
  property test passes**; two companions editing the same story converge with the
  PM's field winning and a conflict record written.
- **P2 — WBS builder + entity tree + taxonomies.** [P1] Epics/stories/tasks/
  subtasks CRUD through the store; **`PRODUCTION_BOARD.md` parser** (§8.1) +
  outline/sheet fallback; color-coded builder (fill=discipline, border=MoSCoW);
  discipline→department derivation; **live MoSCoW % readout** at project/epic/
  subtree scope (§12.5); **WBS edit = PM/leads only**. *Verify:* parse the real
  board → 32 stories + ~1010 tasks render with correct colors; the MUST/SHOULD/
  NICE percentages match the board's headline (151/353/464/42); a member cannot
  alter structure.
- **P3 — Kanban + item detail + assignment.** [P2] States, dnd-kit board,
  detail drawer, human + AI assignment (model/effort/manager), dependency editor.
  Auto "write XP card" task on story/epic create (§8.2). *Verify:* drag persists;
  AI assignment stored; XP task auto-appears once.
- **P4 — Design-doc/XP creator + auto plan.md.** [P3] Haiku chat → XP card;
  `ready` → auto plan.md (§8.3); Open XP/Open plan buttons. *Verify:* card →
  plan generated; buttons open the files.
- **P5 — AI runs + My Agents + game-token ledger.** [P4] `/agent/spawn`
  terminal mode, branch + auto-PR into `Development`, run records, My Agents view,
  game token ledger (approx-flagged). *Verify:* Run on a trivial task opens a PR;
  run shows in My Agents with status.
- **P6 — Sprints + estimation.** [P3] Sprint lanes, drag items, optional
  benchmark points, velocity. *Verify:* item into sprint; velocity when points on.
- **P7 — Timeline + Whiteboard.** [P2] Date-drag timeline colored by epic;
  embedded whiteboard. *Verify:* bar drag persists; board saves.
- **P8 — Dashboards + Personal brief + Blocker.** [P3,P5] Role-scoped dashboards
  (PM/lead/personal, §12.8), Haiku daily brief, **Sonnet** blocker analysis
  (§12.9). *Verify:* lead sees only their dept; blocker returns an ordered list +
  graph.
- **P9 — Bugs + Enhancements.** [P3] Form + Claude intake for bugs; enhancement
  planner. *Verify:* bug via chat fills the form; enhancement graduates to a task.
- **P10 — Notifications, activity feed, token dashboard.** [P5] Mentions +
  routed notifications (incl. agent-needs-review + sync overrides); commit-log
  activity feed; two-ledger token dashboard visible to all. *Verify:* mention
  notifies; override shows in tray + feed; token split renders.
- **P11 — Project bootstrap wizard + seed this project.** [P2] New-project wizard
  writes `project.json`/`roles.json`; seed HTBH to current dev status. *Verify:*
  a fresh project stands up from the wizard; HTBH board reflects real repo state.
- **P12 — Headless AI runs + Liquid UI.** [P5,all] Headless run panel with exact
  token capture; per-user liquid layout (§14). *Verify:* headless run streams +
  exact tokens; layout change affects only that user.

**Suggested MVP cut** if you want something usable fast: **P0–P5 + P8** (store +
WBS + kanban + XP/plan + AI runs + dashboards/blocker) is the smallest set that
delivers "plan the WBS, hand tasks to Claude, watch the board." Everything else
layers on without rework.

---

## 19. Seed WBS — the initial epic → story → task tree

The one-time seed the bootstrap wizard (P11) writes into the store. **9 epics.**
Gameplay epics come from `Feature list.pdf` (grouping) + `PRODUCTION_BOARD.md`
(stories/tasks) + `FEATURE_STATUS.md` (state); the Engine, Editor, and PM-Tool
epics are authored here from the completed `EngineBuildPLAN.md` and the live
packages. After seeding, the WBS builder owns all of it — **no Miro** (§8.1).

**State-seeding rule.** Each story's initial workflow state is derived from
`FEATURE_STATUS.md`: Logic **Shipped** → `Done` for the tech tasks; **Partial**
→ `In Progress`; **Not started** → `New`. Art/Audio become their own
discipline tasks (Sprite/Anim/Sound) carrying their own state, so a feature
whose logic is done but art is idle-only is `Done` on tech and `In Progress` on
art. Discipline → department routing per §8.4.

### 19.1 Gameplay epics (6) — from `Feature list.pdf`
Each **story** below is a board feature block; its **tasks** are that block's
discipline cards (Tech / UI-FX / Sprite / Anim / Sound / Balance @ MoSCoW) — the
recurring per-feature card set is *sprite (per era/tier) · idle/walk/attack/
death anim · spawn/attack/damage FX · the matching SFX · the tech logic ·
balancing values*. Not re-enumerated card-by-card here (the parser emits ~1010);
the notable current-state facts that become tasks are called out.

- **Buildings** *(13 stories · 13/13 logic Shipped)* — Stone Thrower, Flute
  Player, Meditator, Sun Scorcher, AOE Mortar, Storm Priest, Blocker, Wall
  Builder, Base Building (the hole), Painter, Speed Booster, Damage Booster,
  Health Booster. *Logic all Done. Art: only Stone Thrower + Flute Player are
  full sets (Done); Meditator/Sun Scorcher/AOE Mortar/Storm Priest/Blocker/Wall
  Builder are idle-only (Anim tasks `In Progress`); Base Building + Painter +
  all three Boosters are placeholder (Sprite/Anim tasks `New`). All Sound tasks
  `New`.*
- **Enemies & Combat** *(8 stories · 8/8 logic Shipped)* — Normal Soldier, Small
  Raider, Siege Cannon, Boss, Formation, Kidnap, Corpses, Pathfinding. *Every
  enemy carries an **art-rework** story-task (Needs rework). Formation has **no
  sprite slots** (Sprite task `New`, blocker on its art); Boss **era-4 slot
  missing**; **`kidnap` row never imported**. Pathfinding is logic-only, Done.*
- **Map** *(5 stories)* — Tile Map, Tile Conditions, Tile Unlocking, Decoration,
  **Seasons**. *Seasons is the one feature **Not started on all axes** — its
  story fans out to tasks: season state (Tech), seasonal tiles (Sprite),
  change-transition (Anim/FX), seasonal music (Sound), all `New`, all MUST-to-
  scope. 4 Grass conditions + every spawning variant are empty Sprite tasks.*
- **Progression** *(7 stories · 7/7 logic Shipped)* — Waves, Currency (love),
  Levelup & XP, Lightning Strike, Boss Bonuses, Tutorial, Cutscenes. *Lightning
  Strike + Tutorial draw procedurally / have empty marker slots (Sprite tasks
  `New`). **Cutscenes: 2 of 6 videos exist** → 4 outstanding video tasks.*
- **UI** *(10 stories · 10/10 logic Shipped)* — HUD, Upgrade Menu, Main Menu,
  Pause Menu, Settings Menu, Credits, Game Over, Game Log, Cheat Menu, Name
  Entry. *Every screen carries a **UI-reimport** task (Needs reimport). Main
  Menu **background slot empty**.*
- **Effects** *(1 story · Shipped logic)* — Procedural VFX (10 kinds / 10
  triggers, data-driven). *All **8 VFX sprite slots empty** — bespoke VFX art is
  the open task set; today everything draws procedurally.*

> **Cross-cutting: Audio is one system, not forty.** `engine/audio.py` is
> music-only; there is **no SFX API**. Rather than 41 orphan Sound tasks, the
> seed creates a single **Engine story "Sound-effect layer"** (§19.2) that every
> per-feature Sound task **depends on** (blocked_by) — so the blocker tool (§12.9)
> immediately shows it gating the whole Sound column.

### 19.2 Engine epic (NEW) — from completed `EngineBuildPLAN.md` + current state
Discipline: mostly `tech`. Most stories are **Done** (the engine rebuild is
complete and archived); audio is the live gap.

- **Coordinate system** (`engine/coords/`) — world↔screen iso authority. *Done.*
- **GameObject / Component / Scene model** (`engine/core/`) — components-are-what-
  the-editor-sees; serializable. *Done.* Tasks: add-component seam (`/add-engine-
  component`) is an ongoing pattern, not a story.
- **Render pipeline** (`engine/render/`) — 3-layer, headless-testable, RenderItem
  → renderer → pygame backend. *Done.*
- **Physics** (`engine/physics/`) — waypoint movement, range/radius spatial-grid
  queries, tile occupancy. *Done.*
- **Asset system** (`engine/assets/`) — universal slot registry, manifest v2,
  grey-X placeholder. *Done.* Ongoing: per-category frame-size overrides
  (see `EnemyReworkPLAN.md`) — task `In Progress`.
- **Audio engine** (`engine/audio.py`) — *Partial.* Music playback **Done**;
  **Sound-effect layer `New` / MUST** — the project-wide blocker. Tasks:
  design SFX API over `engine/audio.py`; `data/audio/` schema for per-event
  clips; trigger wiring for place/attack/damage/death/repair/upgrade; volume/mix.
- **VFX system** (`engine/vfx/`) — procedural effect kinds. *Done (logic).*

### 19.3 Editor epic (NEW) — from `EngineBuildPLAN.md §5` + `editor/panels/`
Discipline: `tech` + some `ui-fx`. Editor is shipped and under active expansion
(active plans: `UI_EDITOR_PLAN.md`, `SoundEditorPLAN.md`, `UiEditorHonestyPLAN`).

- **Selector panel** — Map/Buildings/Enemies/UI/VFX tree; selection drives all
  panels. *Done.*
- **Tilemap editor** (viewport) — Godot-style paint/erase/line/rect/bucket/
  picker, layers, pan/zoom, undo, active-map. *Done.*
- **Entity preview** — real-engine render of the selection, animation dropdown,
  range overlay, grey-X. *Done.*
- **Balancing form** — schema-generated recursive form → `write_validated`.
  *Done.* (`/add-balancing-value` pattern.)
- **Asset import** — manifest-v2 importer: sheet PNG, per-row anim/fps/hidden/
  loop, offset nudge, animated preview, clear-to-placeholder. *Done.*
  (`/add-asset-importer`, `/replace-visual`.)
- **Screen / UI layout editor** — screen primitives/rules, anchors, strings,
  game-theme, screen/map details panels. *Done / In Progress* per
  `UI_EDITOR_PLAN.md`.
- **Sound editor** — *In Progress* (`SoundEditorPLAN.md`); pairs with §19.2's SFX
  layer (blocked_by it).
- **Cutscene editor** — player + registry + video authoring. *Done (2/6 videos).*
- **Tutorial editor** — director, tooltips, forced click targets. *Done.*
- **Agent dispatch — "Summon a Drunken Robot"** — form roster
  (`data/agent_forms/*.json`) → schema-valid handoff → `/dispatch` on a branch or
  in place; active-plan switch. *Done* (`AgentDispatchPLAN.md`). **This is the
  bridge the PM tool's AI-run feature (§9) generalizes** — a task-worth noting
  as a dependency/link between the Editor and PM-Tool epics.
- **Run / Build controls** — Play (`py game/main.py`), Build (PyInstaller),
  Playbuild. *Done.*

### 19.4 PM Tool epic (NEW) — this tool tracks its own construction
Discipline: `tech` (+ `ui-fx` for the polished UI). The tool is self-hosted: its
**stories are the build phases P0–P12** (§18) and its **tasks are those phases'
deliverables**, so building the planner is itself on the planner. All `New` at
seed (nothing built yet).

- **Foundation** — P0 scaffold, P1 store + merge driver + sync. *(MUST)*
- **Planning spine** — P2 WBS builder + taxonomies + MoSCoW %, P3 kanban +
  assignment, P4 XP-card form + auto plan.md. *(MUST)*
- **AI runs** — P5 spawn + auto-PR + My Agents + game token ledger. *(MUST)*
- **Delivery views** — P6 sprints + estimation, P7 timeline + whiteboard,
  P8 dashboards + brief + blocker. *(SHOULD)*
- **Intake & signal** — P9 bugs + enhancements, P10 notifications + activity +
  token dashboard. *(SHOULD)*
- **Bootstrap & polish** — P11 project wizard + seed this project, P12 headless
  runs + liquid UI. *(P11 MUST · liquid-UI NICE, last.)*

Each story here auto-spawns its "write XP card" task (§8.2) like any other — so
the PM tool's own features get XP cards and generated plans through the very
pipeline they implement.

---

## 20. Governance — making spawned agents obey the repo's rules

Spinner's core promise is launching agents that respect *How To Be Human*'s
rules. Those rules come from **two independent sources**, each needing its own
strategy. **Model compliance is the weakest layer — every rule that can be
enforced by tooling is.**

### 20.1 Two rule-sources (and the gap)
- **Repo-resident (the CLAUDE.md world) — inherited for free.** The router +
  package `CLAUDE.md`s, `.claude/agents/`, the `.claude/commands/` skills, and
  the hooks in `.claude/settings.json` (`PreToolUse`→C2, `SessionStart` /
  **`SubagentStart`**→`orient.py`, which hands each subagent the CLAUDE.md + code
  graph) **auto-load in any Claude Code session launched in the repo**. CI
  (`.github/workflows/tests.yml`) enforces the testgate on every PR. Spinner
  inherits all of it **as long as** it launches with the game-repo clone as cwd,
  **never sets `WORKFLOW_HOOK_OFF=1`**, and seeds the prompt to invoke the right
  skill + read the one package doc.
- **Harness-injected (git/GitHub conventions) — the gap.** Branch-per-feature
  off `Development`, PR-into-`Development`, the attribution footer, PR-template
  use, "never push to `Development` directly", no `build/`/`dist/`/`*.exe`, push
  retry/backoff — today these live **only in the runtime's system prompt, not in
  the repo**. A plain `claude` Spinner launches would not know them. **Closing
  this gap is Spinner's job**: make them repo-resident and tool-enforced.

### 20.2 Encode once — a policy manifest the repo owns
`.claude/policy.json` (added to the game repo, and to Spinner's own repo):
```jsonc
{ "default_pr_base": "Development",
  "protected_branches": ["Development", "main"],
  "branch_pattern": "spinner/<task-id>-<slug>",
  "attribution_footer": "…the required footer text…",
  "forbidden_paths": ["build/", "dist/", "**/*.exe"],
  "required_checks": ["tests"] }
```
Mirrored in prose in a `CONTRIBUTING.md` / a CLAUDE.md "GitHub rules" section so
an agent reads them too. One source; every enforcer below reads it.

### 20.3 Enforce deterministically (belt and suspenders)
1. **Server-side — GitHub branch protection on `Development`:** require a PR,
   require the `tests` check green, require the PR template, block direct pushes.
   An agent **cannot** merge red or push to `Development`.
2. **Client-side — git hooks Spinner installs in every managed clone** (the repo
   ships none today): `pre-push` rejects protected-branch pushes; `commit-msg`
   rejects a missing footer; `pre-commit` blocks `forbidden_paths` and runs
   `py tools/testgate.py check --affected`.
3. **In-session — the C2 `PreToolUse` hook** already hard-denies wrong agent
   types; Spinner never disables it.

### 20.4 Compliant by construction — the tool does the ceremony
Per §9 the **model writes code; the companion performs the git/PR mechanics**
from `policy.json`, so nothing depends on the agent remembering them:
- *Before launch:* `git fetch` + branch `spinner/<task-id>-<slug>` off fresh
  `Development`; cwd = the clone; hooks on; prompt seeded with the matching skill
  (`/add-building`…), the ONE package doc, and the task's XP card + plan.
- *After the agent reports done:* commit with the footer, push with retry/
  backoff, open the PR into `Development` with the template — all by the tool.
- The agent still runs `py tools/testgate.py check` before handback (the in-repo
  exit gate); CI re-checks on the PR.

### 20.5 Verify, then let a human gate
- **Deterministic post-run compliance check** — right branch, footer present, no
  forbidden paths, CI status — surfaced on the card; a violation blocks
  `Ready for Test → Done`.
- **`reviewer` agent** pass over the diff against the brief + design pillars
  (C2's review step), attached to the card.
- **PR-activity subscription** drives card state (CI red → back to the manager;
  merged → `Done`).

### 20.6 Human override is explicit and logged
The rules can be overridden (e.g. a PM committing a plan straight to
`Development`, as was done for *this* doc) — but in Spinner that is a **PM-only,
per-action, logged** escape written to the activity feed, **never** something an
agent self-authorizes.

### 20.7 Spinner's own repo eats its own dog food
`spinner-project-management` ships the **same** stack — its own `CLAUDE.md` +
`.claude/policy.json` + hooks + CI — so the tool enforcing the rules is itself
built under them.

**Phase mapping:** the policy manifest + git-ceremony + client hooks + compliance
check land in **P5** (AI runs); GitHub branch protection is a one-time setup in
**P11** (bootstrap). Adding `.claude/policy.json` + a `CONTRIBUTING.md` to the
game repo is a small **prep task** that can precede Spinner itself.
