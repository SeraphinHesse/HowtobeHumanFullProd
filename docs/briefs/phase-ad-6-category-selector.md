> **SUPERSEDED — historical record.** This brief predates the ZERO-failure
> gate. Any "baseline", "N pre-existing failures", "no NEW failures vs
> Development" or `unittest discover` instruction below is DEAD: the suite is
> green, the gate is ZERO, and a red test is yours. Which tests you may run is
> role-scoped — §"Test Suite Policy" in the root `CLAUDE.md` is the only
> authority. Do not follow this file's verification section.

# Phase AD-6 — Category addition + selector integration + DOMAINS derivation

**Plan**: `planning/AgentDispatchPLAN.md` §3 (form-spec system, `selector_context`)
and §6 → *Phase AD-6* (incl. its **Explicitly deferred** note).
**Branch**: off `phase-AD-1-7-umbrella` (which is off `Development`).
**Depends on (merged before you start)**: AD-1 (`data/schemas/agent_form.schema.json`,
`editor/agent_forms.py`, the `data/agent_forms/` smoke exception), AD-3
(`editor/agent_form_dialog.py::AgentFormDialog`, the `SpawnClaudeDialog` launcher,
injectable `detach`), AD-4 (six more form specs, several carrying
`selector_context`, plus the all-specs sweep test in `tools/tests/test_agent_forms.py`
that will validate YOUR new spec for free).

You are the CODER for AD-6. Do not touch anything outside §3's file scope.

---

## 1. Behavioral spec

Plan §6 / AD-6 goal, verbatim: *"'Add new category/subcategory' works end-to-end;
context-sensitive 'Add new X…' on the selector tree; one hardcoding site fixed."*
Three strands, all required.

### (a) `/add-category` — the skill + its form spec

Two new files: `.claude/commands/add-category.md` and
`data/agent_forms/add-category.json`. Together they let a designer press
**Add New Category…** in the editor, fill a form, and get an agent that adds a whole
new slot-registry category — optionally a **balancing domain** — and walks an
**enumerated hardcoding checklist** so nothing is silently left stale.

**Why the checklist is the point.** `data/slots.json` is data, but seven *other*
places in this repo hardcode either the five domain names or the eight category
keys. Adding a category without touching them produces a green-looking repo with a
red test suite (`test_assets_registry` asserts the literal 8-tuple) or, worse, a
domain the *game* never loads (`game/core/balance.py::DOMAINS` drives `load_all`).
Every site is named explicitly in the skill below — I grepped them; the list is
complete as of this branch.

**The complete intended spec JSON** — write it exactly (it is deterministic-format:
sorted keys, 2-space indent, trailing newline; author it through
`engine.data_io.write_validated` against `data/schemas/agent_form.schema.json`,
never by hand-formatting):

```json
{
  "context": [
    "data/CLAUDE.md",
    "editor/panels/CLAUDE.md",
    ".claude/commands/add-category.md"
  ],
  "description": "Spawns an agent that adds a new slot-registry category to data/slots.json — optionally a full balancing domain (balancing file + schema) — and walks the hardcoded-domain-list checklist so the game, the tests and the skills all learn about it.",
  "fields": [
    {
      "description": "Registry key, snake_case: the slots.json category key, the balancing file stem, and the branch slug.",
      "key": "key",
      "label": "Category key",
      "placeholder": "projectiles",
      "required": true,
      "type": "string"
    },
    {
      "description": "Label the editor tree shows for this category.",
      "key": "display_name",
      "label": "Display name",
      "placeholder": "Projectiles",
      "required": true,
      "type": "string"
    },
    {
      "default": false,
      "description": "True = also a balancing domain: creates data/balancing/<key>.json (_lock UNLOCKED) + data/schemas/<key>.schema.json, and the category gets a balancing form in the editor. False = asset-only (like vfx/deco/backgrounds).",
      "key": "is_balancing_domain",
      "label": "Is a balancing domain",
      "type": "boolean"
    },
    {
      "default": 64,
      "description": "Sprite frame width in px for every slot in this category (how the SHEET is sliced, not how it draws).",
      "key": "frame_w",
      "label": "Frame width (px)",
      "maximum": 1024,
      "minimum": 1,
      "type": "integer"
    },
    {
      "default": 96,
      "description": "Sprite frame height in px for every slot in this category.",
      "key": "frame_h",
      "label": "Frame height (px)",
      "maximum": 1024,
      "minimum": 1,
      "type": "integer"
    },
    {
      "default": "idle",
      "description": "Comma-separated animation vocabulary offered by the importer. MUST start with idle (row 0, E-35). Single-frame art (tiles, deco, backgrounds) uses just 'idle'.",
      "key": "animations",
      "label": "Animations",
      "placeholder": "idle, fly, impact",
      "type": "string"
    }
  ],
  "git_default": "branch",
  "id": "add-category",
  "schema_version": 1,
  "skill": "add-category",
  "slug_field": "key",
  "title": "Add New Category"
}
```

> `agent_form.schema.json` is `additionalProperties: false` — the spec must contain
> exactly the keys above, no more. Run `py tools/smoke.py`: it validates the spec for
> free (AD-1's `data/agent_forms/` directory exception).

**Deliberate spec decisions:**
- **No `selector_context` key.** A `selector_context` binds a form to ONE existing
  category node; add-category *creates* a category, so it belongs to no node. It is
  reachable from (i) the launcher dialog (AD-3, one entry per spec — automatic) and
  (ii) a right-click on **empty tree space** (strand (c)). The AD-4 sweep only checks
  `selector_context` *when present*, so omitting it is legal.
- **`animations` is a comma-separated `string`**, not an array: the AD-1 field-type
  enum is `string|text|boolean|integer|number|enum` — there is no array type, and
  `data/schemas/agent_form.schema.json` is **out of your file scope** (§3). The skill
  splits/strips it.
- **`frame_w`/`frame_h` need `minimum`+`maximum`** — the agent-form schema's `allOf`
  requires them on numeric fields, and `1..1024` mirrors `slots.schema.json`'s own
  bounds so an invalid frame size is unrepresentable in the dialog (ED-30).
- **`git_default: "branch"`** — a new category touches game/tests/skills; it wants a
  PR, not an in-place edit.

**Complete DRAFT of `.claude/commands/add-category.md`** (house format per
`add-skill.md`; write it essentially as-is — tighten wording, don't drop steps):

```markdown
---
description: Use when the task is to add a new slot-registry CATEGORY to data/slots.json — optionally a full balancing domain — and update every place that hardcodes the domain/category list.
argument-hint: <category key + display name, e.g. "projectiles (Projectiles), asset-only, 64x64">
allowed-tools: Read, Edit, Write, Grep, Glob, Bash(py tools/smoke.py*), Bash(py -m unittest*), Bash(py -c *)
---

Add a new registry category: **$ARGUMENTS**. A *category* is a top-level node of
`data/slots.json` (the editor tree's top level). It is a **balancing domain** when it
also has `data/balancing/<key>.json` + `data/schemas/<key>.schema.json` — the editor
derives that set, so no editor edit is ever needed here. Adding a GROUP/variant inside
an existing category is NOT this skill: use the editor's `+ Variant` / `+ Type` buttons
or `/add-asset-importer`. Wiring the import path for the new category's art is
`/add-asset-importer`'s job — this skill stops at data + the checklist and hands off.

The branch+lock protocol is SUSPENDED (root `CLAUDE.md`): never write a `_lock` value
other than the initial `"UNLOCKED"`, never write `.claude/active_domain`.

## Read first (token-light)
1. `data/CLAUDE.md` — slots.json shape (`categories[]`, `key/display_name/frame_w/
   frame_h/animations/groups`, `animations[0] == "idle"`), balancing-file + `_lock`
   shape (D-10/11), schema house style (D-3/D-12: every property `description`d, every
   numeric bounded, `additionalProperties: false`, all keys `required`).
2. `editor/panels/CLAUDE.md` — how the selector builds top-level nodes from the
   registry and how `editor/locks.py::domains()` derives the balancing domains.

## Steps
1. **slots.json** — append the category to `data/slots.json`'s `categories[]` (order
   IS the editor tree order; balancing domains conventionally come before the
   asset-only ones). Give it at least one leaf group with one slot key
   (`^[a-z][a-z0-9_]*$`), the frame size, and the `animations` vocabulary starting with
   `idle`. Write it via `engine.data_io.write_validated` against
   `data/schemas/slots.schema.json` — never hand-format. A slot key may NOT repeat
   across categories (the loader raises).
   `data/schemas/slots.schema.json` needs a change ONLY if you introduce a new
   category-level *field* — a plain new category needs none.
2. **Balancing domain (only when the payload's `is_balancing_domain` is true)** —
   create BOTH:
   - `data/balancing/<key>.json` starting as `{"_lock": "UNLOCKED", ...}` plus at least
     one real tunable (an empty domain renders an empty form).
   - `data/schemas/<key>.schema.json` — house style: `$id`, draft 2020-12,
     `additionalProperties: false`, every key `required`, a `description` on every
     property, `minimum`/`maximum` on every numeric (ED-30), and the D-11 `_lock`
     subschema **inlined** (copy it verbatim from `data/schemas/ui.schema.json` — no
     cross-file `$ref`; `engine.data_io` uses a plain `jsonschema.validate`).
   `tools/smoke.py` stem-pairs `data/balancing/<key>.json` ↔
   `data/schemas/<key>.schema.json` automatically — no smoke change.
3. **Walk the hardcoding checklist — every site, explicitly.** Grep first:
   `grep -rn "buildings.*enemies.*map.*ui.*core" --exclude-dir=.git --exclude-dir=.claude/worktrees .`
   | # | Site | Action |
   |---|------|--------|
   | 1 | `tools/tests/test_assets_registry.py::TestRealRegistry.test_category_order_is_domain_order_plus_asset_only` | **ALWAYS.** It asserts the literal category tuple; add your key in slots.json order or the suite goes red. |
   | 2 | `game/core/balance.py::DOMAINS` (re-exported by `game/core/__init__.py`) | **Balancing domains only.** `load_all()` iterates it — without this the game never loads your domain. |
   | 3 | `tools/tests/test_balancing_data.py::DOMAINS` (~L22) | **Balancing domains only.** Adds the D-3/D-11/D-12 acceptance walk to your new domain. |
   | 4 | `tools/tests/test_balancing_parity.py::DOMAINS` (~L23) | **Inspect; usually NO change.** It is a frozen prototype↔repo migration gate; a brand-new domain has no prototype counterpart. Touch it only if a `balancing_parity_map.json` entry resolves into your domain. |
   | 5 | `.claude/hooks/scope_guard.py::DOMAIN_SCOPE` | **Balancing domains only.** Add `"<key>": ["game/<key>/**", "data/balancing/<key>.json", "data/schemas/<key>.schema.json"]`. The lock protocol is SUSPENDED and the guard fail-opens without `.claude/active_domain`, so this is inert today — add it anyway so the table is correct the day the protocol returns. |
   | 6 | `.claude/commands/smalltweak.md` (~L14) | **Balancing domains only.** The feature-branch list (`featureBuildings`, …) gains `feature<Key>`. |
   | 7 | `.claude/commands/add-balancing-value.md` (frontmatter `description` + body ~L9), `.claude/commands/processtodo.md` (~L20), and the SUSPENDED `.claude/commands/{start,resume,merge}-domain.md` (`argument-hint` + tables) | **Balancing domains only.** Domain enumerations in prose — extend them. |
   | 8 | Docs: root `CLAUDE.md` (~L89), `data/CLAUDE.md` (~L34), `SPEC.md` (~L52 glossary), `data/schemas/slots.schema.json`'s `key` description | **Balancing domains only.** Prose that says "the five domains" — keep it true. |
   | — | `editor/locks.py` | **NOTHING TO DO.** `domains(data_dir)` derives the list from slots.json ∩ `data/balancing/*.json` (AD-6). The selector + balancing panel pick your domain up with zero editor edits. |
4. **Art** — every new slot renders as a grey X until a sheet is imported (E-37).
   Point the user at `/add-asset-importer` (import path) or `/replace-visual`.

## Avoid
- Hand-formatting any `data/` JSON (D-3 — use `write_validated` / `dumps_deterministic`).
- Reusing a slot key from another category (the registry loader raises).
- Cross-file `$ref` in the new schema, or `allOf` composition (it breaks
  `additionalProperties: false`).
- Writing any `_lock` value other than the initial `"UNLOCKED"`; writing
  `.claude/active_domain`.
- Editing `editor/locks.py` to "register" the domain — it is derived.

## Verify
- `py tools/smoke.py` — slots.json + the new balancing file validate.
- `py -m unittest discover -s tools/tests -t .` — zero new failures (item 1 of the
  checklist is the one that bites).
- Live: `py editor/main.py` → the new category is a top-level tree node; a balancing
  domain also shows its form. State exactly what you ran.

## Final report
Changed files; the new category key + whether it is a balancing domain; which
checklist items applied; verification performed; whether `data/CLAUDE.md` needed a
durable update.
```

### (b) `editor/locks.py::DOMAINS` becomes DERIVED

Today: `DOMAINS = ("buildings", "enemies", "map", "ui", "core")` (locks.py L17).
Target: **`data/slots.json` category order ∩ categories with an existing
`data/balancing/<key>.json`**, preserving D-10 order. A new balancing domain then
appears in the selector + balancing panel with **zero editor edits**.

**Verified against the real `data/` on this branch** (I ran it):

```
derived = tuple(c.key for c in load_registry(Path("data")).categories()
                if (Path("data")/"balancing"/f"{c.key}.json").exists())
# -> ('buildings', 'enemies', 'map', 'ui', 'core')   == the canonical tuple ✅
```

`data/slots.json` categories are `buildings, enemies, map, ui, core, vfx, deco,
backgrounds`; `data/balancing/` holds exactly `buildings, core, enemies, map, ui`.
The derivation is exact today.

**Function, not a module-level tuple — and this is a real deviation from the naive
reading of the plan, so here is the justification.** A derived module constant would
have to run file I/O at import against `REPO/data`, which is **data_dir-blind**: every
editor module takes `data_dir=None` and the whole editor test-suite runs against a
tempfile copy of `data/` (`test_editor_panels.TempDataCase`). A global computed from
the repo's real `data/` would report `map` as a domain in a temp tree where
`balancing/map.json` was deleted — i.e. it would reintroduce, as a *silent* bug, the
exact staleness AD-6 is removing. So:

```python
def domains(data_dir=None):
    """Balancing domains, derived: slots.json category order ∩ categories with a
    data/balancing/<key>.json (D-10 order). No hardcoded list — a new domain
    appears the moment its balancing file exists."""
```

`DOMAINS` is **deleted**, not aliased — a stale alias would be a trap for new code.

**Every call site of `locks.DOMAINS` (grepped repo-wide), and its adaptation:**

| Site | Today | After |
|------|-------|-------|
| `editor/panels/selector.py` L68 (skip guard), L125 (`domains()`), L254 (`_emit_selection`) | `locks.DOMAINS` | `self._domains` — cached (see §2) |
| `editor/spawnclaude.py` L45 (`domain_choices`) | `locks.DOMAINS` | **already gone**: AD-2 deletes `domain_choices` + the `locks` import. If AD-2 landed as specified there is nothing here; **if you find a surviving `locks` import in spawnclaude.py, STOP and report** — do not "fix" spawnclaude (§3 hard boundary). |
| `tools/tests/test_spawnclaude.py` L73 | `locks.DOMAINS` | **already gone** (AD-2 rewrites that test). |
| `tools/tests/test_editor_panels.py` L82 (`TempDataCase.setUp`), L113, L118, L531 | `locks.DOMAINS` | `locks.domains(self.data_dir)` — yours to fix (§3). |

Non-consumers, do **not** touch: `game/core/balance.py::DOMAINS` and the DOMAINS
literals in `tools/tests/test_balancing_data.py` / `test_balancing_parity.py` are
independent hardcodings (game and editor never import each other). They stay hardcoded
in AD-6 — the add-category checklist is what keeps them honest. (Flagged: the plan's
checklist did not name `game/core/balance.py`; it is in the draft above. See §4.)

**One behavior nuance you MUST preserve.** Selector L68-70 today omits a *domain*
category whose balancing file is missing ("no balancing file, no domain node" —
`editor/panels/CLAUDE.md`, and `test_domain_without_file_is_omitted` asserts it). With
derived domains, "a domain with no balancing file" is definitionally not a domain, so a
naive rewrite makes that guard dead code and the `map` node would be **shown** as an
asset-only category — and `_emit_selection` L249 emits `domain_selected("map")`
unconditionally for Maps-branch leaves, which would then drive `BalancingPanel.set_domain("map")`
into a `FileNotFoundError`. **Keep the omission**, expressed without a hardcoded list:

> a category is *intended* as a domain iff `data/schemas/<key>.schema.json` exists;
> omit it from the tree iff it is intended but has no `data/balancing/<key>.json`.

Verified safe: among the eight category keys, only the five domains have a
`data/schemas/<key>.schema.json` (`vfx`/`deco`/`backgrounds` have none), so this
reproduces today's tree exactly and needs no new list. `locks.schema_path()` already
exists for it.

### (c) Selector context menu

Right-click a **category node** (a top-level node — payload `path == ()`; `deco` counts,
it is a category node nested under `map`) → a `QMenu` with one **"Add New X…"** entry per
form spec whose `selector_context` equals that category key (AD-4 gives `add-enemy` →
`enemies`, `add-building` → `buildings`, etc.). Triggering an entry emits
`add_requested(form_id)`; `editor/main.py` opens the `AgentFormDialog` for that spec.

Right-click **empty tree space** → a single **"Add New Category…"** entry
(`form_id = "add-category"`, a module constant), so strand (a)'s form is reachable from
the tree, not only the launcher. If that spec is absent, show no menu (silent).

Specs are loaded **fresh on every menu open** (`agent_forms.load_form_specs(data_dir)`)
— same fresh-load semantics as the AD-3 launcher, so a spec added by `/add-form-spec`
needs no editor restart. Right-click on a group node, a Maps leaf, or (a category with
no matching spec) → **no menu** (don't show an empty popup).

### Explicit deferral (plan §6, AD-6)

`.claude/hooks/scope_guard.py::DOMAIN_SCOPE` **stays hardcoded and AD-6 does not edit
it**: it belongs to the SUSPENDED branch+lock protocol, fail-opens when
`.claude/active_domain` is absent, and `/dispatch` never writes that file. The
add-category checklist merely *names* it for the day the protocol returns. Do not
derive it, do not import it, do not touch the file.

---

## 2. Architecture plan

**`editor/locks.py`** — pure, no Qt, no pygame, reads only through `engine`:

```python
from engine.assets import load_registry   # PURE half of engine.assets (verified: importing it does NOT import pygame)

def category_keys(data_dir=None):        # optional helper, if you want it
    """slots.json category keys in file order."""

def domains(data_dir=None):
    """Balancing domains: slots.json category order ∩ existing data/balancing/<key>.json."""
    base = Path(data_dir) if data_dir is not None else REPO / "data"
    return tuple(c.key for c in load_registry(base).categories()
                 if balancing_path(c.key, base).exists())
```

- Use `engine.assets.load_registry` (it already does `load_validated(slots.json,
  slots.schema.json)` and preserves order) rather than re-parsing — one parse path,
  fail-loud on a bad registry, and it keeps `locks.py` free of its own JSON handling.
  `load_registry` takes a `Path` (`data_dir / "slots.json"`), so pass a `Path`.
- Keep `REPO`, `balancing_path`, `schema_path`, `lock_info`, `is_locked`, `owner`,
  `since` exactly as they are. Delete `DOMAINS`. Update the module docstring.
- `test_editor_panels.TestLocks.test_no_force_unlock_api` walks `dir(locks)` asserting
  no name contains "unlock"/"release" — `domains` is fine.

**`editor/panels/selector.py`**:
- `__init__`: `self._domains = locks.domains(self._data_dir)` **once**, before the
  category loop, and re-derive it in `reload_registry()` (a registry reload can add a
  category). Cache it — `_emit_selection` runs on every click and `domains()` costs a
  jsonschema validation of slots.json. (Optional: give `locks.domains` a
  `registry=None` kwarg and pass `self.registry` — allowed, not required.)
- L68-70 guard → the schema-exists-but-file-missing rule from §1(b):
  ```python
  if locks.schema_path(category.key, self._data_dir).exists() \
          and not locks.balancing_path(category.key, self._data_dir).exists():
      continue   # intended domain, no balancing file → no node (Phase 4 behavior)
  ```
- L125 / L254: `locks.DOMAINS` → `self._domains`.
- New signal: `add_requested = Signal(str)` (the form id).
- **Context menu** — use the DEFAULT context-menu policy (a `QWidget`'s default is
  `Qt.ContextMenuPolicy.DefaultContextMenu`, which routes right-clicks to
  `contextMenuEvent`) and override `contextMenuEvent`. Do **not** switch to
  `CustomContextMenu` + `customContextMenuRequested` — it buys nothing here and adds a
  connection to test. Split construction from display so tests never `exec()` a modal
  popup:
  ```python
  _ADD_CATEGORY_FORM_ID = "add-category"     # module constant

  def _add_entries(self, category_key):
      """[(label, form_id)] offered for this node. category_key=None → the
      empty-space menu. Fresh spec load, loud errors swallowed (a broken spec
      must not kill a right-click; the launcher dialog is where it surfaces)."""

  def _context_menu(self, item):             # -> QMenu | None, never exec()s
      ...

  def contextMenuEvent(self, event):
      menu = self._context_menu(self.itemAt(event.pos()))
      if menu is not None:
          menu.exec(event.globalPos())
  ```
  Each `QAction` connects to `lambda checked=False, fid=form_id: self.add_requested.emit(fid)`
  — bind `fid` as a default arg (late-binding closure bug) and absorb `triggered`'s
  `checked` bool. `QAction.trigger()` fires the signal without showing the menu → the
  test path. Parent the `QMenu` to `self` so it is destroyed with the panel.
- Node classification for the menu: `item is None` → empty-space menu; else
  `category_key, path = item.data(0, _PAYLOAD_ROLE)`; offer entries **only when
  `path == ()`** (a category root — this excludes group nodes, the "Maps" branch
  (`path == ("Maps",)`) and map leaves).
- `_add_entries` wraps `agent_forms.load_form_specs` in
  `try/except (OSError, ValueError, Exception-from-jsonschema)` → return `[]` on
  failure and write one line to `sys.stderr`. Rationale: an unhandled exception raised
  inside a Qt event handler can abort the process under PySide6; a right-click must
  never be able to kill the editor.
- Imports stay editor+engine only (`from editor import agent_forms, locks`) — no
  `game/` import, ever (TestPurity).
- Docstring: add a short paragraph describing the context menu (the module docstring is
  this file's architecture note).

**`editor/main.py`** (AD-6 owns main.py's real edits; AD-3 only touched a comment):
- imports: `from editor import agent_forms, registry_ops, selection, theme` and
  `from editor.agent_form_dialog import AgentFormDialog` (both editor modules — the
  `editor/` ↔ `game/` layering rule is untouched).
- wiring, next to the existing selector connects (~L99-101):
  `self.selector.add_requested.connect(self._on_add_requested)`
- handler, next to `_on_spawnclaude`:
  ```python
  def _on_add_requested(self, form_id):
      """Selector right-click → the AgentFormDialog for that form spec. Specs are
      re-read per open, so a newly added spec needs no editor restart."""
      spec = next((s for s in agent_forms.load_form_specs(self._data_dir)
                   if s["id"] == form_id), None)
      if spec is None:
          self.statusBar().showMessage(f"No form spec {form_id!r}", 5000)
          return
      AgentFormDialog(spec, data_dir=self._data_dir, repo=REPO, parent=self).exec()
  ```
  Signature per AD-3: `AgentFormDialog(spec, data_dir=None, repo=None, parent=None,
  detach=None)`. `REPO` already exists in `main.py`. Do not add a `detach` seam to
  `MainWindow` — AD-3's dialog tests already cover dispatch; AD-6's tests stop at the
  signal (see §3).

---

## 3. File scope + shared-file contract

**New**
- `.claude/commands/add-category.md` — §1(a) draft.
- `data/agent_forms/add-category.json` — §1(a) spec, written via `write_validated`.

**Modified**
- `editor/locks.py` — `DOMAINS` → `domains(data_dir=None)`; docstring.
- `editor/panels/selector.py` — cached derived domains, the reworked omission guard,
  `add_requested` signal, `_add_entries` / `_context_menu` / `contextMenuEvent`.
- `editor/main.py` — **AD-6 owns the real edits here**: import, one connect, one
  handler. Nothing else.
- `editor/panels/CLAUDE.md` — the selector architecture note. Update **two** places:
  the Phase-5 "Merged tree" bullet (context menu → `add_requested(form_id)` from the
  specs' `selector_context`; empty-space → Add New Category) and the "`locks.py` is
  read-only" bullet (`DOMAINS` (D-10 order) → `domains(data_dir)`, derived from
  slots.json ∩ `data/balancing/*.json`; a domain category whose *schema* exists but
  whose balancing file does not is still omitted whole).
- `tools/tests/test_editor_panels.py` — **required**, `locks.DOMAINS` no longer exists:
  `TempDataCase.setUp` L82, `TestSelector` L113/L118, `TestMainWindowWiring` L531 →
  `locks.domains(self.data_dir)`. While you are in L113, assert against the **literal**
  `("buildings","enemies","map","ui","core")` — comparing `panel.domains()` to
  `locks.domains(...)` would be a tautology now that both derive.

**Tests — put them in `tools/tests/test_editor_panels.py`** (a new
`tools/tests/test_locks_domains.py` is the plan's alternative; I chose the existing
module and here is why: it already carries the offscreen preamble
(`QT_QPA_PLATFORM=offscreen` + `SDL_VIDEODRIVER/SDL_AUDIODRIVER=dummy` set **before**
any Qt/pygame import, one `QApplication` per process), the `TempDataCase` temp-copy
harness, and `TestLocks`/`TestSelector` classes that are literally about these two
symbols. A new module would clone ~40 lines of harness to hold ~40 lines of test —
reuse wins, and the AD-6 tests are not a separable concern). Add:

1. `TestLocks` (or a new `TestDomainsDerivation(TempDataCase)`):
   - `locks.domains(self.data_dir) == ("buildings","enemies","map","ui","core")` — the
     derivation reproduces the canonical D-10 order.
   - **remove**: `unlink data/balancing/map.json` → `("buildings","enemies","ui","core")`.
   - **add**: write `data/balancing/vfx.json` (`{"_lock": "UNLOCKED"}`, plus a minimal
     `data/schemas/vfx.schema.json` so anything downstream that validates still can)
     into the temp copy → `("buildings","enemies","map","ui","core","vfx")` — **order
     follows slots.json**, where `vfx` sits after `core`. This is the test that proves
     "a new domain appears with zero editor edits".
   - `locks.domains()` with no arg (real `data/`) still returns the canonical tuple.
2. `TestSelector`: with the temp `vfx` balancing file, `SelectorPanel(data_dir=…).domains()`
   includes `vfx`; without it, it does not (the existing
   `test_domain_without_file_is_omitted` still passes unchanged in meaning — the `map`
   node is still omitted **whole**; assert `panel._find_item("map", ())` raises `KeyError`
   to pin that).
3. Context menu (offscreen, no `exec()`):
   - `panel._add_entries("enemies")` contains `("Add New Enemy…", "add-enemy")` (label
     text comes from the spec's `title`; assert on the **form id**, not the label, so a
     wording change doesn't break the test).
   - build `menu = panel._context_menu(panel._find_item("enemies", ()))`, connect
     `add_requested` to a list, `menu.actions()[0].trigger()` → the list is
     `["add-enemy"]`. **Mapped form id, per the plan's stated test.**
   - `panel._context_menu(<a group node>)` is `None`; `panel._context_menu(None)`
     (empty space) yields exactly the `add-category` entry.

Optional (nice, not required): a `TestMainWindowWiring` test that monkeypatches
`editor.main.AgentFormDialog` with a stub capturing `(spec, data_dir, repo)`, emits
`window.selector.add_requested`, and asserts the stub saw the right spec — **never
call the real dialog's `exec()` in a test** (it blocks).

**HARD BOUNDARY — do not open, do not edit:** `editor/spawnclaude.py`,
`editor/agent_form_dialog.py`, `editor/agent_forms.py`, `tools/smoke.py`,
`data/schemas/agent_form.schema.json`, `.claude/hooks/scope_guard.py`,
`editor/CLAUDE.md` (AD-3 owns it), `tools/tests/test_agent_forms.py` (AD-4/AD-5 own it
— your new spec is covered by their all-specs sweep automatically),
`game/**`, `tools/tests/test_balancing_data.py`, `tools/tests/test_balancing_parity.py`,
`tools/tests/test_assets_registry.py` (AD-6 adds no category — those files are only
*named* by the skill's checklist, for future add-category runs).

---

## 4. Exit gate + Quick Test

**Exit gate (you run these):**
1. `py tools/smoke.py` — must print the file count and pass; it now also validates
   `data/agent_forms/add-category.json` against `agent_form.schema.json` (AD-1's
   directory exception).
2. `py -m unittest discover -s tools/tests -t .` — **zero NEW failures** vs. the
   Development baseline (there is a known pre-existing baseline of failures on
   `Development`; diff against it, don't chase it). Report the exact before/after
   counts.
3. Qt tests are headless via the mechanism already used by
   `tools/tests/test_editor_panels.py` / `test_editor_viewport.py`: at the TOP of the
   module, **before any Qt/pygame import**,
   `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` +
   `os.environ.setdefault("SDL_VIDEODRIVER", "dummy")` +
   `os.environ.setdefault("SDL_AUDIODRIVER", "dummy")`, then a single
   `_APP = QApplication.instance() or QApplication(sys.argv)` per process. You are
   adding to an existing module, so this is already in place — just never `exec()` a
   menu or a dialog.
4. Sanity one-liner worth pasting into the PR:
   `py -c "import sys; sys.path.insert(0,'.'); from editor import locks; print(locks.domains())"`
   → `('buildings', 'enemies', 'map', 'ui', 'core')`.

**NOT doable headlessly — write these into the PR body as Quick Tests for the user:**
- **QT-1 (context menu):** `py editor/main.py` → right-click the **Enemies** node in
  the tree → **"Add New Enemy…"** appears → click it → the AD-3 agent form opens with
  the enemy fields. Right-click **Buildings** → "Add New Building…". Right-click a
  *group* node (e.g. Enemies → Walker) or a map under **Maps** → **no menu**.
  Right-click **empty space** below the tree → **"Add New Category…"** → the
  add-category form opens.
- **QT-2 (add-category end-to-end):** from that form, dispatch a toy category
  (`key: "projectiles"`, display "Projectiles", *not* a balancing domain, 64×64,
  animations `idle, fly`) in **branch** mode. The agent should land a PR adding it to
  `data/slots.json` **and** updating `tools/tests/test_assets_registry.py`'s category
  tuple. Check out that branch → the editor shows a **Projectiles** top-level node
  (grey-X slot).
- **QT-3 (derived DOMAINS — the payoff):** repeat QT-2 with
  `is_balancing_domain: true`. On that branch the editor must show the new category
  **with a balancing form** — with **zero edits to `editor/`**. That is the whole point
  of strand (b).

---

## Notes for the reviewer / anything that contradicts the plan

1. **The plan's hardcoding checklist is incomplete.** It names `scope_guard.py`, "test
   DOMAINS lists (e.g. `test_balancing_data.py`)" and `smalltweak.md`. Grepping turns up
   two more load-bearing sites: **`tools/tests/test_assets_registry.py`** asserts the
   literal 8-category tuple, so *any* new category (even asset-only) reddens the suite;
   and **`game/core/balance.py::DOMAINS`** drives `load_all()`, so a new balancing domain
   is invisible to the *game* without it. Both are in the skill's checklist above. Plus
   prose sites: `add-balancing-value.md`, `processtodo.md`, the suspended
   `{start,resume,merge}-domain.md`, root `CLAUDE.md`, `data/CLAUDE.md`, `SPEC.md`, and
   `slots.schema.json`'s `key` description.
2. **"`DOMAINS` becomes derived" cannot stay a module-level tuple.** Every editor module
   is `data_dir`-injectable and the editor tests run on a temp copy of `data/`; a global
   derived at import from `REPO/data` would be silently wrong for any other tree. It
   becomes `domains(data_dir=None)` and `DOMAINS` is deleted — 4 source call sites + 4
   test lines (all listed in §1(b)); `spawnclaude`'s two are already gone via AD-2.
3. **The derivation alone would break the tree, not just the list.** "Domain with no
   balancing file" stops being expressible, so the selector's "no balancing file, no
   domain node" omission (and its test) would silently die — and a Maps leaf would then
   emit `domain_selected("map")` into a missing file (`FileNotFoundError` in
   `BalancingPanel.set_domain`). §1(b) keeps the omission via *schema exists but
   balancing file does not*, which reproduces today's tree exactly (verified: only the
   five domains have a `data/schemas/<key>.schema.json`). Derivation itself is otherwise
   safe — I ran it against the real `data/` and it returns exactly
   `("buildings","enemies","map","ui","core")`.
4. **`/add-category` overlaps `/add-asset-importer`** (whose step 1 already says "add the
   category to `data/slots.json` … if it should also be a balancing domain it needs a
   `data/balancing/<domain>.json`"). Resolved by scope, not by deleting either: add-category
   owns the **data + hardcoding-checklist** half and hands the **import-path wiring** off
   to `/add-asset-importer` (stated in both the skill's opening paragraph and its step 4).
5. **"category/subcategory"**: the form/skill covers the **category** case only.
   Subcategories (groups/variants inside a category) are already served by the editor's
   `+ Variant` / `+ Type` buttons and `editor/registry_ops.py`; the skill says so rather
   than growing a second path.
</content>
</invoke>
