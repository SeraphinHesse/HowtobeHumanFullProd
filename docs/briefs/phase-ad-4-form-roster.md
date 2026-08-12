> **SUPERSEDED — historical record.** This brief predates the ZERO-failure
> gate. Any "baseline", "N pre-existing failures", "no NEW failures vs
> Development" or `unittest discover` instruction below is DEAD: the suite is
> green, the gate is ZERO, and a red test is yours. Which tests you may run is
> role-scoped — §"Test Suite Policy" in the root `CLAUDE.md` is the only
> authority. Do not follow this file's verification section.

# Phase AD-4 — Form roster + suspension cleanup (coder brief)

Source: `planning/AgentDispatchPLAN.md` §6 "Phase AD-4", §2 decision **D6**, §3
(form-spec schema + the `add-enemy.json` example). Branch: off the AD umbrella
(`phase-AD-1-7-umbrella`). Base already contains **AD-1** (schemas,
`data/agent_forms/add-enemy.json`, `editor/agent_forms.py`,
`tools/tests/test_agent_forms.py`, the smoke third-directory exception) and
**AD-3** (launcher + generic form renderer).

**Plan goal (§6/AD-4):** *"every existing add-* skill is reachable from a form;
the old domain flow is visibly suspended."*

---

## 1. Behavioral spec

### 1a. Six new form specs in `data/agent_forms/`

Every spec validates against `data/schemas/agent_form.schema.json` (AD-1) and is
picked up automatically by `agent_forms.load_form_specs()` → the AD-3 launcher
lists one entry per spec, fresh on every dialog open (no editor restart). Because
of AD-1's smoke third-directory exception, each file below is schema-validated by
`py tools/smoke.py` for free.

Rules that shaped every spec (do not deviate):

- **The free-text description box is built into the dialog** (§3, "The free-text
  description box is built into the dialog, not a spec field"). **Never** add a
  `description`/`notes`/`behavior` field to a spec.
- **Fields are grounded in what the target skill actually consumes.** Every field
  below traces to a concrete line in its `.claude/commands/<skill>.md` (cited
  inline). Do not invent fields the skill cannot use.
- `id` **must equal the filename stem** (schema pattern `^[a-z][a-z0-9-]*$`).
- `context` paths were each verified to exist on disk (2026-07-14).
- `selector_context` is only set where the form genuinely belongs to one
  `data/slots.json` category (AD-6 turns it into a right-click on that category
  node). Valid keys: `buildings, enemies, map, ui, core, vfx, deco, backgrounds`.
  **Only `add-building` gets one** (`"buildings"`, mirroring add-enemy's
  `"enemies"`). The other five are cross-category or category-creating — omit the
  key rather than force a bad mapping.

#### `data/agent_forms/add-building.json`

Fields trace to `.claude/commands/add-building.md` step 1 (leaf module +
`BUILDING_TYPE` + `TIER_SPRITES`), step 3 (the `ResearchSpec` row — fields
confirmed in `game/buildings/research.py:53-62`: `starts_unlocked`,
`starts_with_tier`, `gate_kind` ∈ `None|min_village_level|min_round`), step 5
(slots/tier prefixes) and step 6 (`Attacker` component + `"combat"` tag).

```json
{
  "schema_version": 1,
  "id": "add-building",
  "title": "Add New Building",
  "description": "Spawns an agent that adds a new building type: leaf class + research row + registry + balancing subtree + slots (10B-10E pattern).",
  "skill": "add-building",
  "context": ["game/buildings/CLAUDE.md", ".claude/commands/add-building.md"],
  "git_default": "branch",
  "slug_field": "name",
  "selector_context": "buildings",
  "fields": [
    { "key": "name", "label": "Building name", "type": "string", "required": true,
      "placeholder": "Sun Scorcher",
      "description": "Display name; drives the leaf class name, BUILDING_TYPE, balancing subtree key and branch slug." },
    { "key": "parent_family", "label": "Parent family", "type": "enum",
      "options": ["defence", "economy", "boost", "structure"], "default": "defence",
      "description": "Which parent/module the leaf hangs off (defence.py / economy.py / boost.py-style / structure.py). The parent computes derived stats." },
    { "key": "is_combat", "label": "Combat building", "type": "boolean", "default": false,
      "description": "Advertises via the Attacker component + the 'combat' tag (never an IS_COMBAT flag) so the combat sweep stays type-agnostic." },
    { "key": "starts_unlocked", "label": "Starts unlocked", "type": "boolean", "default": true,
      "description": "ResearchSpec.starts_unlocked. False = earned via a level-up unlock reward." },
    { "key": "starts_with_tier", "label": "Starts with tier", "type": "integer",
      "minimum": 0, "maximum": 3, "default": 1,
      "description": "ResearchSpec.starts_with_tier. 0 means even tier 1 must be researched." },
    { "key": "gate_kind", "label": "Unlock gate", "type": "enum",
      "options": ["none", "min_village_level", "min_round"], "default": "none",
      "description": "ResearchSpec.gate_kind. The spec stores WHERE in buildings.json the gate value lives, never the value." },
    { "key": "tier_count", "label": "Tier count", "type": "integer",
      "minimum": 1, "maximum": 3, "default": 3,
      "description": "How many tier sprite prefixes (TIER_SPRITES) and slots.json tier groups to add." }
  ]
}
```

#### `data/agent_forms/add-balancing-value.json`

Fields trace to `.claude/commands/add-balancing-value.md`: the five domains
(`buildings/enemies/map/ui/core` — matches `data/balancing/*.json` on disk),
step 1 (nested key path, ×10 combat scale on HP/DMG), step 2 (schema mirror:
`type`, `description`, `minimum`/`maximum` → the editor's spinbox bounds, ED-30).

`bounds` is deliberately a **string**, not two numeric fields: the schema forces
`minimum`+`maximum` on every numeric field, so a numeric "minimum" field would
need arbitrary sentinel bounds of its own and would render a spinbox that cannot
express "unbounded". A `"0..100"` / blank string is honest and the skill reads it
directly.

```json
{
  "schema_version": 1,
  "id": "add-balancing-value",
  "title": "Add Balancing Value",
  "description": "Spawns an agent that adds a gameplay tunable to data/balancing/<domain>.json and mirrors it in the schema; the recursive editor form renders it for free.",
  "skill": "add-balancing-value",
  "context": ["data/CLAUDE.md", ".claude/commands/add-balancing-value.md"],
  "git_default": "current",
  "slug_field": "key_path",
  "fields": [
    { "key": "domain", "label": "Domain", "type": "enum",
      "options": ["buildings", "enemies", "map", "ui", "core"], "default": "core", "required": true,
      "description": "Target data/balancing/<domain>.json + data/schemas/<domain>.schema.json." },
    { "key": "key_path", "label": "Key path", "type": "string", "required": true,
      "placeholder": "Rewards.xp_per_boss_kill",
      "description": "Dotted path into the nested subtree where the new key belongs (place it beside its siblings, not at the root)." },
    { "key": "value_type", "label": "Value type", "type": "enum",
      "options": ["integer", "number", "boolean", "string", "array"], "default": "integer",
      "description": "JSON type of the value and of the schema mirror. Lists are real JSON arrays, never stringified." },
    { "key": "default_value", "label": "Initial value", "type": "string", "required": true,
      "placeholder": "50",
      "description": "The value to write into the balancing JSON (typed per Value type)." },
    { "key": "bounds", "label": "Schema bounds (min..max)", "type": "string",
      "placeholder": "0..1000",
      "description": "minimum/maximum for the schema mirror — the editor spinbox reads these so invalid input is unrepresentable (ED-30). Blank = unbounded." },
    { "key": "combat_scale", "label": "Combat stat (x10 scale)", "type": "boolean", "default": false,
      "description": "HP/DMG value: apply the x10 combat scale. (base_hp stays 10 — the documented exception.)" }
  ]
}
```

#### `data/agent_forms/add-editor-feature.json`

Fields trace to `.claude/commands/add-editor-feature.md`: step 1 (hang it off the
single-selection model), step 3 (`write_validated` for any `data/` write), step 5
(Qt-free pure helper) — and the panel list quoted in its "Read first" §2
(*selector / balancing / details / palette / map-details / viewport*).

```json
{
  "schema_version": 1,
  "id": "add-editor-feature",
  "title": "Add Editor Feature",
  "description": "Spawns an agent that adds an editor feature/panel: hung off the single-selection model, one render path (ED-22), all writes via write_validated, registered in TestPurity.",
  "skill": "add-editor-feature",
  "context": ["editor/CLAUDE.md", "editor/panels/CLAUDE.md", ".claude/commands/add-editor-feature.md"],
  "git_default": "branch",
  "slug_field": "name",
  "fields": [
    { "key": "name", "label": "Feature name", "type": "string", "required": true,
      "placeholder": "Per-level balancing focus",
      "description": "Short feature name; drives the branch slug." },
    { "key": "panel", "label": "Panel area", "type": "enum",
      "options": ["selector", "balancing", "details", "palette", "map-details", "viewport", "new panel"],
      "default": "details",
      "description": "Which existing panel the feature lives in (its conventions in editor/panels/CLAUDE.md govern), or a new panel." },
    { "key": "writes_data", "label": "Writes to data/", "type": "boolean", "default": false,
      "description": "Feature writes JSON: it MUST go through engine.data_io.write_validated with schema-derived bounds (ED-30/31)." },
    { "key": "needs_pure_helper", "label": "Needs a Qt-free helper module", "type": "boolean", "default": true,
      "description": "Logic goes in a Qt-free/pygame-free editor/*.py helper and is registered in test_editor_viewport.TestPurity." }
  ]
}
```

#### `data/agent_forms/add-engine-component.json`

Fields trace to `.claude/commands/add-engine-component.md`: step 1 (declared
JSON-safe fields — carried by the free-text box, per the skill's
`argument-hint: <component name + what state it holds>`), step 2 (`on_added`
owner seam), step 3 (`update(dt)` / `render_items(transform)`), step 4 (which
engine subpackage; `engine/` subpackages on disk: `assets`, `coords`, `core`,
`physics`, `render`).

```json
{
  "schema_version": 1,
  "id": "add-engine-component",
  "title": "Add Engine Component",
  "description": "Spawns an agent that adds an engine Component: declared JSON-safe fields, on_added seam, auto-registration, module stays pure (E-11/E-15).",
  "skill": "add-engine-component",
  "context": ["engine/core/CLAUDE.md", ".claude/commands/add-engine-component.md"],
  "git_default": "branch",
  "slug_field": "name",
  "fields": [
    { "key": "name", "label": "Component name", "type": "string", "required": true,
      "placeholder": "Shield",
      "description": "Class name; also the auto-registration key for component_from_dict. Describe the state it holds in the box above." },
    { "key": "subpackage", "label": "Engine subpackage", "type": "enum",
      "options": ["core", "physics", "render", "assets"], "default": "core",
      "description": "Where the module lands. Components live in engine/core; a physics primitive it wraps goes in engine/physics (like Movement)." },
    { "key": "needs_owner", "label": "Needs owner access", "type": "boolean", "default": false,
      "description": "Override on_added(owner) and cache self._owner (transient underscore) to reach the owner's transform." },
    { "key": "is_visual", "label": "Visual component", "type": "boolean", "default": false,
      "description": "Defines render_items(transform) -> iterable[RenderItem] (pure data; engine.core never imports pygame)." },
    { "key": "has_update", "label": "Per-frame update", "type": "boolean", "default": true,
      "description": "Has per-frame logic in update(dt)." }
  ]
}
```

#### `data/agent_forms/add-asset-importer.json`

Fields trace to `.claude/commands/add-asset-importer.md`: step 1 (new
`data/slots.json` category: key, frame size, `animations` vocabulary), step 2
("If it should ALSO be a balancing domain, it needs a `data/balancing/<domain>.json`"),
step 3 (the import path forks on idle-only vs multi-row animated — that fork *is*
the `animated` boolean). Frame-size defaults match the existing categories
(buildings/enemies/core/deco 64×96).

No `selector_context`: this form **creates** a category, so there is no existing
category node to hang it off. (AD-6's `add-category` form overlaps this skill;
AD-4 ships the form for the skill that exists today and leaves the overlap to
AD-6.)

```json
{
  "schema_version": 1,
  "id": "add-asset-importer",
  "title": "Add Asset Category / Importer",
  "description": "Spawns an agent that wires a new renderable category into the editor's asset pipeline: slots.json category + selector node + the right import path.",
  "skill": "add-asset-importer",
  "context": ["editor/panels/CLAUDE.md", "engine/assets/CLAUDE.md", ".claude/commands/add-asset-importer.md"],
  "git_default": "branch",
  "slug_field": "category_key",
  "fields": [
    { "key": "category_key", "label": "Category key", "type": "string", "required": true,
      "placeholder": "projectiles",
      "description": "New data/slots.json category key (lowercase, snake_case). Sets the selector tree node and the branch slug." },
    { "key": "display_name", "label": "Display name", "type": "string", "required": true,
      "placeholder": "Projectiles",
      "description": "Label shown on the selector tree node." },
    { "key": "frame_w", "label": "Frame width", "type": "integer",
      "minimum": 8, "maximum": 512, "default": 64,
      "description": "Frame width in px for the category's slots (buildings/enemies 64, map tiles 64, ui/vfx 64)." },
    { "key": "frame_h", "label": "Frame height", "type": "integer",
      "minimum": 8, "maximum": 512, "default": 96,
      "description": "Frame height in px (buildings/enemies/deco/core 96, map tiles 32, ui/vfx 64)." },
    { "key": "animated", "label": "Animated (multi-row)", "type": "boolean", "default": false,
      "description": "False = idle-only slot (imported via asset_import.import_idle_sheet). True = real animation vocabulary, imported through the DetailsPanel rows. List the animation names in the box above." },
    { "key": "is_balancing_domain", "label": "Also a balancing domain", "type": "boolean", "default": false,
      "description": "True = also needs data/balancing/<key>.json + data/schemas/<key>.schema.json. Asset-only categories (like vfx) do not." }
  ]
}
```

#### `data/agent_forms/replace-visual.json`

Fields trace to `.claude/commands/replace-visual.md`: `argument-hint:
<slot-key> <path-to-sheet.png>` (the two required fields), and step 2 vs step 3
(the idle-only helper path vs the multi-animation manifest-v2 entry). Its step 5
commits "per whatever branch you're on" — so `git_default` is **`current`**, not
`branch`.

No `selector_context`: the form applies to a slot in **any** category, and the
schema allows only one key.

```json
{
  "schema_version": 1,
  "id": "replace-visual",
  "title": "Replace a Visual",
  "description": "Spawns an agent that replaces a slot's grey-X placeholder with a real spritesheet via the manifest-v2 asset pipeline (no code change, no procedural fallback).",
  "skill": "replace-visual",
  "context": ["engine/assets/CLAUDE.md", ".claude/commands/replace-visual.md"],
  "git_default": "current",
  "slug_field": "slot_key",
  "fields": [
    { "key": "slot_key", "label": "Slot key", "type": "string", "required": true,
      "placeholder": "deco_rock",
      "description": "An existing slot key in data/slots.json. Its category fixes the frame size." },
    { "key": "sheet_path", "label": "Spritesheet path (.png)", "type": "string", "required": true,
      "placeholder": "C:/art/deco_rock.png",
      "description": "Source sheet. It is copied to data/sprites/imported/<slot>.png (committed content, D-31)." },
    { "key": "multi_animation", "label": "Multi-animation sheet", "type": "boolean", "default": false,
      "description": "False = idle-only slot (import_idle_sheet writes one row). True = one manifest row per animation, row 0 always idle (schema-forced)." }
  ]
}
```

### 1b. Suspension cleanup (D6)

Plan §2 **D6**: *"The domain-flow skills (`start-domain`, `resume-domain`,
`finish-domain`, `merge-domain`) stay on disk with a `SUSPENDED —` description
prefix. `editor/locks.py` stays … `.claude/hooks/scope_guard.py` stays fail-open
and untouched."*

- All four skill files **stay on disk** — do not delete, do not rename, do not
  rewrite their bodies beyond the one added note.
- Each gets a `SUSPENDED — ` prefix on its frontmatter `description:` line plus a
  short body note pointing at `/dispatch` (exact text in §2 below).
- **`editor/locks.py` and `.claude/hooks/scope_guard.py` are NOT touched by AD-4.**
  The `_lock` key stays in the schemas and the balancing panel keeps reading it.
- Root `CLAUDE.md`'s **branch + lock protocol section is NOT touched** — it already
  carries the TEMPORARY OVERRIDE callout. AD-4 only updates the **spawn-mode**
  mentions (§2 below).

---

## 2. Architecture plan

### 2a. Authoring the six specs

Copy the **shape** of `data/agent_forms/add-enemy.json` (AD-1) — same key order,
same style of `description` strings (one sentence, agent-readable). Hard schema
constraints from `agent_form.schema.json`'s `$defs.field.allOf` (plan §3):

- `type: "enum"` → **`options` is required** (`minItems: 1`).
- `type: "integer"` or `"number"` → **`minimum` AND `maximum` are required**.
  (Every numeric field above carries both — the AD-3 renderer turns them into
  spinbox ranges so invalid input is unrepresentable, ED-30.)
- `additionalProperties: false` at both levels — no keys beyond
  `key/label/type/description/required/default/placeholder/options/minimum/maximum`.
- Top-level `required`: `schema_version, id, title, description, skill, context,
  git_default, fields`. `slug_field` and `selector_context` are optional.

Write them with `engine.data_io.write_validated` (the sanctioned write path;
deterministic sorted-keys / 2-space indent / trailing newline), e.g.
`py -c "from engine import data_io; data_io.write_validated('data/agent_forms/add-building.json', payload, 'data/schemas/agent_form.schema.json')"`,
or hand-write and let `py tools/smoke.py` catch drift. **Do not hand-format.**

No editor code is needed: the AD-3 launcher enumerates specs on every open.

### 2b. The four domain skills — exact edits

For each file, prefix the frontmatter `description:` and add one body note
directly under the frontmatter (above the existing first paragraph). Nothing else
in these files changes.

`.claude/commands/start-domain.md` — current line 2:

```
description: Start a scoped domain session — pull, lock the domain's balancing JSON, branch off main, scope this session.
```

→

```
description: SUSPENDED — the branch+lock protocol is on hold (see root CLAUDE.md). Do not run. Use the editor's Summon a Drunken Robot forms (/dispatch) instead.
```

`.claude/commands/resume-domain.md` — current line 2:

```
description: Resume an already-started domain session — pull, switch to the feature branch, re-scope. Does NOT touch the lock.
```

→

```
description: SUSPENDED — the branch+lock protocol is on hold (see root CLAUDE.md). Do not run. Use the editor's Summon a Drunken Robot forms (/dispatch) instead.
```

`.claude/commands/finish-domain.md` — current line 2:

```
description: Wrap up the active domain session — run the exit gate, then (on confirmation) commit, push, and open a PR into main. Does NOT unlock.
```

→

```
description: SUSPENDED — the branch+lock protocol is on hold (see root CLAUDE.md). Do not run. Use the editor's Summon a Drunken Robot forms (/dispatch) instead.
```

`.claude/commands/merge-domain.md` — current line 2:

```
description: Merge a finished domain into main — the ONLY place the _lock clears and the feature branch goes away.
```

→

```
description: SUSPENDED — the branch+lock protocol is on hold (see root CLAUDE.md). Do not run. Use the editor's Summon a Drunken Robot forms (/dispatch) instead.
```

Body note — insert this identical block immediately after the closing `---` of
the frontmatter in **each** of the four files (keep each file's original prose
below it, verbatim):

```md
> ⚠️ **SUSPENDED.** The branch + lock protocol is on hold for the engine
> migration (root `CLAUDE.md` → "Branch + lock protocol"). Do **not** run this
> command: it is no longer reachable from the editor's spawn dialog, and
> `/dispatch` never writes `.claude/active_domain` or any `_lock`. Spawn work
> from the editor's **Summon a Drunken Robot** launcher ("Add new X…" forms →
> `/dispatch`), or branch per plan phase. This file is kept intact so the
> protocol can be restored unchanged when the migration lands.
```

Keep the original `description:` semantics recoverable: the note's last sentence
is the restore hint. Do **not** touch each file's `argument-hint`/`allowed-tools`
lines.

### 2c. Doc updates — spawn-mode mentions only

**Finding (contradicts the plan's assumption — see the closing summary):** a sweep
of root `CLAUDE.md` + `docs/prompt-templates.md` found **no stale "the spawn
dialog offers /start-domain" text to delete**. `/start-domain` appears in root
`CLAUDE.md` only inside the branch + lock protocol section (lines 140, 150),
which is explicitly out of scope. The spawn-mode surface in these two docs is
therefore *under*-documented rather than wrong, and the AD-4 edit is **additive**:
state that the add-* skills are now reachable as forms and that the dialog's
`/start-domain` mode is gone.

**Root `CLAUDE.md`** — current text (lines 112-114, the tail of the "If your task
matches one of these, INVOKE the skill" section, immediately after the skill
table):

```md
Copy-paste task openers (that themselves point at these skills) live in
[`docs/prompt-templates.md`](docs/prompt-templates.md).
```

→ replace with:

```md
Every skill in this table is **also a form** in the editor: **Summon a Drunken
Robot** → *Add new X…* → fill the fields + the free-text box → Dispatch. The
editor writes a schema-validated handoff and opens a terminal on
`/dispatch <handoff>`, which runs the same skill unmodified, on a new branch off
`Development` (ending in a PR) or in place on the current branch — your choice in
the form (`planning/AgentDispatchPLAN.md`). The dialog's old **`/start-domain`
mode is gone** (the lock protocol is suspended); **Small tweak** and **Admin**
are unchanged.

Copy-paste task openers (that themselves point at these skills) live in
[`docs/prompt-templates.md`](docs/prompt-templates.md).
```

Do **not** touch root `CLAUDE.md`'s "Branch + lock protocol" section or its
Graphify section.

**`docs/prompt-templates.md`** — insert a new block between `## Add an engine
component` (ends line 92) and `## Switch the active plan` (starts line 94):

```md
## Dispatch a skill from the editor (no prompt to write)

```txt
Every /add-* opener above is also an "Add new X…" form in the editor: Summon a
Drunken Robot → pick the form → fill the structured fields + the free-text box →
Dispatch. The editor writes .claude/dispatch/<ts>-<form>.json and opens a
terminal on `/dispatch <that file>`, which runs the same skill for you — new
branch off Development + PR, or in place on the current branch (chosen in the
form). The old /start-domain spawn mode is gone: the lock protocol is suspended.
```
```

Leave `docs/prompt-templates.md` line 101 ("…the editor's Summon a Drunken Robot
screen all follow it") as-is — it is about the active-plan mirror (AD-7), not a
stale spawn mode.

---

## 3. File scope + shared-file contract

**New (6):**

- `data/agent_forms/add-building.json`
- `data/agent_forms/add-balancing-value.json`
- `data/agent_forms/add-editor-feature.json`
- `data/agent_forms/add-engine-component.json`
- `data/agent_forms/add-asset-importer.json`
- `data/agent_forms/replace-visual.json`

**Modified (7):**

- `.claude/commands/start-domain.md`, `resume-domain.md`, `finish-domain.md`,
  `merge-domain.md` — frontmatter `description:` prefix + the body note (§2b).
  **Nothing else in these files.**
- `CLAUDE.md` (root) — the one additive paragraph in §2c. **Spawn-mode mentions
  ONLY**: do not touch the "Branch + lock protocol" section or the Graphify
  section.
- `docs/prompt-templates.md` — the one new block in §2c.
- `tools/tests/test_agent_forms.py` — **APPEND ONE NEW `unittest.TestCase` CLASS.**

### Shared-file contract on `tools/tests/test_agent_forms.py`

This file is created by **AD-1** and also appended to by **AD-5**. AD-4 must
**append a new class at the end of the file and touch nothing else** — do not
edit, reorder, rename or "tidy" AD-1's classes or imports, and do not remove the
`if __name__ == "__main__": unittest.main()` tail (append the class *above* it).
If AD-5's class is already present, append below it. Merge conflicts are avoided
only by strict append-only discipline.

The new class is an **all-specs sweep** (plan §6/AD-4 "Tests"), running over every
`data/agent_forms/*.json` (via `agent_forms.load_form_specs`, so new specs are
covered automatically — including AD-5's `add-form-spec.json` and AD-7's
`create-plan.json` when they land):

1. `spec["id"] == <filename stem>` for every spec.
2. `.claude/commands/<spec["skill"]>.md` exists for every spec.
3. Every path in `spec["context"]` exists (repo-relative, from the repo root).
4. `spec["selector_context"]`, **when present**, is one of the `key` values in
   `data/slots.json`'s `categories` list (today: `buildings, enemies, map, ui,
   core, vfx, deco, backgrounds`) — read it from the file, don't hardcode the
   list.
5. (Cheap bonus, same class) at least the six AD-4 ids + `add-enemy` are present,
   so a deleted spec is caught.

Content/type validation is already free via smoke + `load_form_specs` — do not
re-implement schema validation here.

### HARD BOUNDARY — do not touch

- `editor/**` (any file) — AD-3 owns the renderer/launcher; the specs need zero
  editor code.
- `tools/smoke.py` — AD-1 added the `data/agent_forms/` directory exception.
- `data/schemas/**` — the form schema is AD-1's and is final for this phase.
- `data/agent_forms/add-enemy.json` — AD-1's template; read it, copy its shape,
  do not edit it.
- **Any `add-*.md` skill body** — per **D4** ("Existing `add-*` skills already
  take free-text `$ARGUMENTS`, so they need **no changes**"). This includes their
  stale "Respect the `_lock`…" lines: leave them.
- `editor/locks.py`, `.claude/hooks/scope_guard.py`, `data/slots.json`,
  `data/balancing/**`.

---

## 4. Exit gate + Quick Test

### Automated (must be green before the PR)

1. `py tools/smoke.py` — the six new specs are validated for free by AD-1's
   third-directory exception. **Expected count: `smoke: 25 data file(s)
   schema-valid`.** (Today on `Development` it prints **18**; AD-1 adds
   `add-enemy.json` → 19; AD-4's six → **25**. If the number is not 25, a spec
   file is missing or an unexpected `data/**/*.json` landed — investigate, do not
   paper over it.) Smoke must also still run its 5 headless gameplay frames + the
   shell boot and print `OK`.
2. `py -m unittest discover -s tools/tests -t .` — full suite, **zero NEW
   failures** vs. the base branch. There are 17 known pre-existing failures on
   `Development`; capture the base count first (`git stash` / a clean checkout)
   and diff against it. The new sweep class must pass.
3. Sanity check the schema gate really fires: temporarily break one spec (drop a
   numeric field's `maximum`, or add an unknown key) and confirm `py
   tools/smoke.py` fails loudly — then revert. Report that you did this.

### Quick Test for the user (put this in the PR body)

The live spot-check in plan §6/AD-4 ("spot-live-check one new form … through the
dialog to terminal launch") **cannot be run headlessly** — it opens a real
Windows Terminal. Hand it to the user in the PR:

> **Quick Test**
> 1. `py editor/main.py` → toolbar → **Summon a Drunken Robot**.
> 2. The launcher now lists **7** form entries: Add New Enemy, Add New Building,
>    Add Balancing Value, Add Editor Feature, Add Engine Component, Add Asset
>    Category / Importer, Replace a Visual — plus **Small tweak** and **Admin**.
>    There is **no** domain/`/start-domain` option any more.
> 3. Click **Add New Building**. The form shows the free-text description box, a
>    required *Building name*, a *Parent family* combo (defence/economy/boost/
>    structure), *Combat building* / *Starts unlocked* checkboxes, a *Starts with
>    tier* spinbox clamped to 0–3, an *Unlock gate* combo, and a *Tier count*
>    spinbox clamped to 1–3. **Dispatch is disabled** until *Building name* is
>    filled.
> 4. Type a name (e.g. `Sun Scorcher`), leave git mode on **New branch** — the
>    branch field should live-slug to `agent/add-building-sun-scorcher`. Press
>    **Dispatch**.
> 5. A terminal opens running `/dispatch .claude/dispatch/<ts>-add-building.json`.
>    Confirm the agent echoes the payload summary (form, skill, values, git mode).
>    **You may Ctrl-C at the git step** — this test only proves the form reaches
>    the terminal.
> 6. Open **Replace a Visual** and confirm its git mode defaults to **Work on
>    current branch** (art swaps land in place). Cancel.
> 7. `/start-domain` in a Claude session still lists, but its description now
>    starts with `SUSPENDED —`.

### Report exactly what you verified

State in the PR: smoke (with the data-file count), the full suite (base-vs-head
failure counts), the deliberate-breakage schema check — and that the dialog→
terminal path is **unverified by you** and is the user's Quick Test.
