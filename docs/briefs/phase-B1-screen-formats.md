# Phase B1 — data: screen override format (slice 10L-B)

Branch: `phase-10L-finish-umbrella`. Plan: `planning/UI_EDITOR_PLAN.md` §B1
(lines 278–293), "New requirements" R3 (lines 84–100), and architecture decision
"Smoke pairing" (lines 165–170). This file is the contract — implement exactly
this.

---

## 1. Behavioral spec

### 1.1 What exists today

No UI screen JSON files exist. `game/ui/` owns 12 screen implementations
(main_menu.py, pause.py, hud.py, etc.) each with a hardcoded `layout()` method
that positions widgets absolutely. Plan §B1 decision 1 (line 104) pins the
design: screens keep computing their prototype-exact default layout in
`game/ui` code; a per-screen JSON can override any *named* widget's rect / skin /
font / colors / label, plus a screen background.

### 1.2 Target scope: 12 screen IDs (R3, verified against game/ui/)

All live screens that shall be editable in B1+B4. Verified by grep in
`game/ui/__init__.py` / individual screen imports in `game/main.py` (Phase 9H,
10A, 10G, 10H, 10I, 10J):

- **`main_menu`** — `game/ui/main_menu.py:32-67` (`MainMenu` class; five buttons
  + title + background art)
- **`pause`** — `game/ui/pause.py` (shell pause modal; verified exists)
- **`settings`** — `game/ui/settings.py` (shell settings modal; verified exists)
- **`credits`** — `game/ui/credits.py` (shell credits modal; verified exists)
- **`add_name`** — `game/ui/add_name.py` (shell name-entry modal; verified exists)
- **`game_over`** — `game/ui/game_over.py` (end-of-run screen; verified exists)
- **`levelup`** — `game/ui/levelup.py` (10A level-up modal; verified exists)
- **`hud`** — `game/ui/hud.py:1-154` (in-round HUD; love panel, XP bar, phase
  banner, End Turn button)
- **`building_panel`** — `game/ui/building_ui.py` (in-round tile panel; unlock /
  construct / upgrade / info modes; verified exists)
- **`cheat_menu`** — `game/ui/cheat_menu.py` (10H Ctrl+L cheat modal; verified
  exists; plan §B1 specifies full template at lines 85–89)
- **`game_log`** — `game/ui/game_log.py` (10J game log display; plan §B1
  specifies at lines 90–93: container-only with ONE widget `log`)
- **`boss_cutscene`** — `game/ui/boss_cutscene.py` (10G boss win/loss modal; plan
  §B1 specifies at lines 94–100)

Every `game/ui/<screen_id>.py` file defines a class (or classes) that name their
fixed widgets via an `ids` dict (exact pattern established by existing screens).
Nothing consumes ui screen JSON files yet (B2 wires them into game code).

### 1.3 Widget-kind vocabulary (the schema enum)

Enumerated by inspecting `game/ui/` widget construction (game/ui/widgets.py
lines 1–150, hud.py, main_menu.py, building_ui.py, cheat_menu.py, game_log.py):

- **`button`** — `widgets.Button` class (main_menu.py:34–35, cheat_menu.py,
  pause.py, etc.; a rectangular click target + label)
- **`panel`** — `widgets.submit_panel()` and HudRect-based containers
  (building_ui.py, levelup.py; graphical container with border)
- **`label`** — `widgets.submit_text()` / `submit_centered()` and HudText
  (main_menu.py:61–64, hud.py; text-only, static)
- **`backdrop`** — `HudRect(..., color)` solid backgrounds (main_menu.py:59,
  hud.py; a colored rectangle, no border)
- **`bar`** — `widgets.submit_bar()` (hud.py income/XP bar, building HP bars;
  progress/stat bar)
- **`field`** — text input element (add_name.py, cheat_menu.py round_goto field;
  an editable text field)

Pin this enum (six kinds) by validating it against the four representative
screens in plan §B1 lines 85–100 (cheat_menu full, game_log partial, boss_cutscene
A/B). All six kinds are represented across the 12 screens.

### 1.4 Schema: `data/schemas/ui_screen.schema.json` (NEW)

Everything optional — the schema allows a minimal `{}` at load time and layering
defaults + overrides at game startup:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/schemas/ui_screen.schema.json",
  "type": "object",
  "properties": {
    "background": {
      "type": "object",
      "oneOf": [
        { "required": ["slot"], "properties": { "slot": { "type": "string" } }, "additionalProperties": false },
        { "required": ["color"], "properties": { "color": { "type": "array", "minItems": 3, "maxItems": 4, "items": { "type": "integer", "minimum": 0, "maximum": 255 } } }, "additionalProperties": false }
      ]
    },
    "defaults": {
      "type": "object",
      "properties": {
        "button_skin": { "type": "string" },
        "panel_skin": { "type": "string" },
        "font": { "type": "string" },
        "text_color": { "type": "array", "minItems": 3, "maxItems": 4, "items": { "type": "integer", "minimum": 0, "maximum": 255 } }
      },
      "additionalProperties": false
    },
    "widgets": {
      "type": "object",
      "patternProperties": {
        "^[a-z][a-z0-9_]*$": {
          "type": "object",
          "properties": {
            "rect": { "type": "array", "minItems": 4, "maxItems": 4, "items": { "type": "integer" } },
            "skin": { "type": "string" },
            "font": { "type": "string" },
            "color": { "type": "array", "minItems": 3, "maxItems": 4, "items": { "type": "integer", "minimum": 0, "maximum": 255 } },
            "text_color": { "type": "array", "minItems": 3, "maxItems": 4, "items": { "type": "integer", "minimum": 0, "maximum": 255 } },
            "label": { "type": "string" },
            "visible": { "type": "boolean" }
          },
          "additionalProperties": false
        }
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false
}
```

Widget IDs validated against `screen_defaults.json` at LOAD time in game code
(B2), not in the schema — a load-time fail-loud check catches renames. Schema
allows any snake_case widget id; the runtime contract is enforced in B2.

### 1.5 Schema: `data/schemas/ui_screen_defaults.schema.json` (NEW)

The generated defaults file, written by `tools/export_ui_layouts.py` (B3):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/schemas/ui_screen_defaults.schema.json",
  "type": "object",
  "properties": {
    "screens": {
      "type": "object",
      "patternProperties": {
        "^[a-z_]+$": {
          "type": "object",
          "required": ["widgets"],
          "properties": {
            "widgets": {
              "type": "object",
              "patternProperties": {
                "^[a-z][a-z0-9_]*$": {
                  "type": "object",
                  "required": ["rect", "kind", "label"],
                  "properties": {
                    "rect": { "type": "array", "minItems": 4, "maxItems": 4, "items": { "type": "integer" } },
                    "kind": { "type": "string", "enum": ["button", "panel", "label", "backdrop", "bar", "field"] },
                    "label": { "type": "string" }
                  },
                  "additionalProperties": false
                }
              },
              "additionalProperties": false
            },
            "mock_note": { "type": "string" }
          },
          "additionalProperties": false
        }
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false,
  "required": ["screens"]
}
```

The `kind` enum is pinned to the six widget kinds (§1.3). The `mock_note` field
documents the mock state used when the exporter ran (e.g., "love=123, round=7").

### 1.6 Seeded screen files: 12 × `data/ui/screens/<id>.json`

Each screen starts as an EMPTY `{}` JSON object. The schema makes every top-level
key optional, so `{}` validates perfectly. The editor lists all 12; overrides
accrete later (B4).

Files to create (stems MUST match the screen IDs exactly):
- `data/ui/screens/main_menu.json`
- `data/ui/screens/pause.json`
- `data/ui/screens/settings.json`
- `data/ui/screens/credits.json`
- `data/ui/screens/add_name.json`
- `data/ui/screens/game_over.json`
- `data/ui/screens/levelup.json`
- `data/ui/screens/hud.json`
- `data/ui/screens/building_panel.json`
- `data/ui/screens/cheat_menu.json`
- `data/ui/screens/game_log.json`
- `data/ui/screens/boss_cutscene.json`

---

## 2. Architecture plan (edits, in order)

1. **Create directory** `data/ui/screens/` (does not exist yet).

2. **Create two NEW schemas:**
   - `data/schemas/ui_screen.schema.json` — per-screen override format (§1.4).
     Schema: everything optional (background + defaults + widgets), widget
     object keys are snake_case identifiers, individual widget properties
     (rect, skin, font, color, text_color, label, visible) are all optional.
   - `data/schemas/ui_screen_defaults.schema.json` — the generated defaults file
     (§1.5). Schema: flat `{"screens": {<screen_id>: {widgets: {...},
     mock_note}}}`, per-widget entries REQUIRED (rect, kind, label), kind enum
     is the fixed six. Write both using `engine.data_io.dumps_deterministic`
     (sorted keys, 2-space indent, validates at write time).

3. **Create 12 screen JSON files**, all EMPTY `{}`:
   `data/ui/screens/{main_menu,pause,settings,credits,add_name,game_over,levelup,hud,building_panel,cheat_menu,game_log,boss_cutscene}.json`
   via `engine.data_io.write_validated(..., ui_screen.schema.json)`.

4. **`tools/smoke.py` — wire the directory rule:**
   Add a fourth exception to `validate_data` (lines 25–61), immediately after
   the `agent_forms_dir` block (line 51):
   ```python
   screens_dir = data_root / "ui" / "screens"
   ```
   Then in the chain at line 44, between line 52 and the final `else` (line 53),
   add:
   ```python
   elif screens_dir in path.parents:
       schema = schema_dir / "ui_screen.schema.json"
   ```
   **Rationale**: `data/ui/screens/*.json` are named arbitrarily (the screen id,
   not a schema stem) and validate against `ui_screen.schema.json` — the exact
   parallel to `data/maps/*.json`. The stem 'screen' is unavailable (singular
   data files use their own id as stem, e.g., `ui_screen_defaults.json`), so
   the directory exception is the only way to express this rule.

5. **`tools/tests/test_smoke_pairing.py` — add test cases for the directory rule:**
   In the `TestPairingRule` class, after `test_mispaired_file_outside_maps_still_fails_loud`
   (line 61–65), add TWO new test methods:

   ```python
   def test_ui_screen_file_with_arbitrary_stem_pairs_to_ui_screen_schema(self):
       self.write("ui/screens/main_menu.json", {})
       self.write("ui/screens/pause.json", {"widgets": {}})
       self.assertEqual(smoke.validate_data(self.data_root), 2)

   def test_invalid_ui_screen_file_fails(self):
       self.write("ui/screens/bad.json", {"widgets": {"w": "not-an-object"}})
       with self.assertRaises(jsonschema.ValidationError):
           smoke.validate_data(self.data_root)
   ```

   (The pattern mirrors the map-file tests: one passing, one catching a schema
   violation in the widget object.)

6. **`data/CLAUDE.md` — document both formats + correct stale A7 bullet:**
   Add a new subsection after the "Asset data" section (before "Map data"),
   named **"UI screen data"**:

   ```
   ## UI screen data (Phase 10L-B, R3)
   - **`data/ui/screens/<screen_id>.json`**: per-screen override format. One file
     per screen (12 total: main_menu, pause, settings, credits, add_name,
     game_over, levelup, hud, building_panel, cheat_menu, game_log,
     boss_cutscene); each is EMPTY `{}` until edited in the editor.
     `background: {slot} | {color}` sets the background (slot key OR RGB[A]);
     `defaults: {button_skin?, panel_skin?, font?, text_color?}` applies per-kind
     styling to dynamic widgets; `widgets: {<id>: {rect?, skin?, font?, color?,
     text_color?, label?, visible?}}` overrides any named widget's properties.
     Nothing consumes these files until B2.
   - **`data/ui/screen_defaults.json`**: generated-but-committed file, written by
     `tools/export_ui_layouts.py` (B3) and validated by a test that re-runs the
     exporter (B3). Per-screen snapshot: `{widgets: {<id>: {rect, kind, label}},
     mock_note}`, where `kind` is one of `button | panel | label | backdrop |
     bar | field`. Editor previews render from defaults + overrides only. Merge
     conflicts on two branches resolve by re-running the exporter (deterministic
     output).
   - **SCHEMA-PAIRING EXCEPTION (the directory rule — now THREE + ONE)**:
     `data/ui/screens/*.json` (any stem) → `ui_screen.schema.json` (exact
     parallel to `data/maps/*.json` → `map_file.schema.json`); stem `ui_screen`
     is unavailable because `ui_screen_defaults.json` uses it (a singular data
     file paired with its own stem). `tools/smoke.py::validate_data` special-cases
     the directory exactly like maps. `data/ui/screen_defaults.json` pairs
     normally via stem.
   - **`ui` animation vocabulary** (`slots.json` A3): `["idle", "hover",
     "pressed", "disabled"]` — button states become manifest rows (plan decision
     2, landed A3). Widget skins source the `ui` slots; per-slot animation
     vocabulary + partial-sheet fallback apply uniformly.
   ```

   Then, in the existing "Asset data" subsection (line 158), replace the stale
   bullet starting "The override does NOT propagate to "+ Variant"" (lines 134–137):

   **OLD** (stale A7 note):
   ```
   - **The override does NOT propagate to "+ Variant"**: `registry_ops.add_variant`
     appends a bare key, so `ui_bg_main_menu_v2` inherits the category's 64×64.
     Harmless today (nothing consumes the slot); fix before a background picker
     ships (10L-B).
   ```

   **NEW** (A7 landed in this umbrella):
   ```
   - **The override DOES propagate to "+ Variant"** (A7): `registry_ops.add_variant`
     now inherits the family stem's frame-size override on creation, so
     `ui_bg_main_menu_v2` inherits the `ui_bg_main_menu` 480×270 override.
     Bare stems stay bare (regression pin for enemies/deco); independently
     resizable afterwards via the Frame W/H spinboxes.
   ```

---

## 3. File scope + shared-file contract (binding)

B1's coder works alone on branch `phase-10L-finish-umbrella`, in parallel with
A4/A5′/A6/A7/A8 (which do NOT touch `data/ui/**` or the new smoke rule). B1's
file scope:

- `data/schemas/ui_screen.schema.json` (**NEW**)
- `data/schemas/ui_screen_defaults.schema.json` (**NEW**)
- `data/ui/screens/` directory (**NEW**, create it)
- `data/ui/screens/*.json` (**NEW**, 12 files, all `{}`)
- `tools/smoke.py` (add the fourth directory exception)
- `tools/tests/test_smoke_pairing.py` (extend with two new test methods)
- `data/CLAUDE.md` (add UI screen data subsection + correct A7 bullet)

**B1 must NOT touch** `game/ui/**` (B2 owns the wiring), `editor/**` (B4 owns
the screen mode), or any `engine/` file. Schema-writing uses the standard
pattern: `dumps_deterministic` for formatting, `write_validated` for
round-trip validation.

**Shared-file contract with A3+A5′:** A3 lands `ui` category with four groups
(Buttons, Panels, Icons, Backgrounds) holding eight slots (ui_button,
ui_panel, ui_panel_stone, ui_icon_love, ui_icon_xp, ui_icon_lives,
ui_bg_main_menu, and one background variant test). A5′ lands `widgets.Button`
and `submit_panel` with optional `skin` parameter (none assigned yet). B1 creates
the empty screen JSON files and pins the schema formats; B2 reads them in game
code and assigns skins. **No code changes in B1** — data and schema only.

---

## 4. Exit gate + Quick Test

### Commands

```bash
py tools/smoke.py                      # all 12 screens must validate
py tools/testgate.py check --affected  # targeted tests
```

**Gate = ZERO failures** (`GATE PASS`). No baseline, no tolerated failures.

### New tests (name them exactly)

Two methods in `tools/tests/test_smoke_pairing.py` in `TestPairingRule` (copy
the existing map-directory pattern):

- **`test_ui_screen_file_with_arbitrary_stem_pairs_to_ui_screen_schema`** —
  create `ui/screens/main_menu.json` (empty), `ui/screens/pause.json` (with
  `{"widgets": {}}`), call `smoke.validate_data(self.data_root)`, assert count
  = 2. Proves both files validate against `ui_screen.schema.json`.
- **`test_invalid_ui_screen_file_fails`** — create `ui/screens/bad.json` with
  an invalid widget entry, call `smoke.validate_data`, expect
  `jsonschema.ValidationError`. Proves the schema rejects malformed data.

### Human Quick Test (live)

1. `py tools/smoke.py` before and after B1.
2. Inspect one created screen file: `cat data/ui/screens/main_menu.json` → prints
   `{}`.
3. Inspect the two NEW schemas: `cat data/schemas/ui_screen.schema.json` →
   contains `"properties": {"background", "defaults", "widgets"}` with all
   optional; `cat data/schemas/ui_screen_defaults.schema.json` → contains
   `"kind": {"enum": ["button", "panel", "label", "backdrop", "bar", "field"]}`.
4. `grep -c '"ui_screen.schema.json"' tools/smoke.py` → prints `1` (the new
   elif block is the only reference).
5. Run smoke again: `py tools/smoke.py` → validates all 12 empty screens +
   prints "OK". Corrupt `data/ui/screens/main_menu.json` to
   `{"widgets": "not-an-object"}`, run smoke → fails loud with a schema error.
   Revert.

---

## Risks / open items

- **Directory-rule count in smoke.py** — the rule now has FOUR exceptions
  (maps, balancing_history, agent_forms, ui/screens). Smoke test checks
  schema count; if the count diverges from reality, the test reveals it. No
  issue on its own (the test passes).
- **`screen_defaults.json` merge friction** — this file is generated and
  committed. Two concurrent branches that both run B3's exporter will conflict
  when merged. Resolution: merge locally by re-running the exporter (it is
  deterministic), never by hand-merging the JSON. A test ensures staleness is
  caught (B3).
