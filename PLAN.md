<!-- active-plan: UiEditorHonestyPLAN.md | set: 2026-07-20 -->
> **Active plan:** UiEditorHonestyPLAN.md (mirror). Source of truth:
> `planning/UiEditorHonestyPLAN.md`. Do **not** edit this file directly — edit the
> source in `planning/` and re-run `/setcurrentplan`, or pick a different
> plan (`/setcurrentplan <name>`, or the editor's Summon a Drunken Robot
> screen).

# UiEditorHonestyPLAN.md — Make the UI editor honest

Phased, agent-executable plan (same family as `AgentDispatchPLAN.md` /
`MIGRATION_PLAN.md`). Base branch: `Development`. Runnable via
`/execute-plan-phases planning/UiEditorHonestyPLAN.md UH-1-UH-6` or
phase-by-phase.

## 1. Context

Source of record: the 2026-07-20 investigation **"Why the UI Editor Lies"**
(artifact `8bdd2bb8`, findings from `editor/`, `game/ui/`, `data/ui/`,
`UI_EDITOR_PLAN.md`). Root cause, one sentence: **the editor never runs the
game** — it edits override "stickers" on top of a frozen snapshot
(`data/ui/screen_defaults.json`, exported by `tools/export_ui_layouts.py`),
while the game applies the same overrides on top of live per-frame layout code.
Every user-visible symptom traces to that gap or to controls that silently
no-op against it:

1. Fonts / button colors / text "can't be changed" — fonts are 7 hardcoded
   presets in `engine/render/fonts.py`; skinned buttons ignore the `color`
   field (colors live in the baked PNG sheets); most text is live game state.
2. `building_panel` looks broken in the editor — the exporter flattens all
   four panel modes (unlock / construct / upgrade / base-info) plus the
   preview window into ONE superimposed snapshot the game never shows.
3. No way to add a new button **type** (slot-registry family) — only
   "+ Variant" exists; the data model already supports families.
4. Widget ids (`action_btn`, …) are programmer names and can't be renamed —
   they are the game↔exporter↔override contract; the editor lacks a
   display-name layer.
5. + 6. User wants preview / unlock / construct / upgrade separated — the
   editor-side split falls out of per-mode snapshots (2).

This plan implements **every fix the artifact suggests** in its waves 1–2.
Its wave-3 "decide separately" items (in-game screen split; true-WYSIWYG
subprocess preview) are deliberately **out of scope** — see Risks.

## 2. Decisions (binding for all phases)

- **D1 — Layering holds.** Editor still never imports `game/**`; all game
  knowledge reaches the editor through the exporter → `screen_defaults.json`
  path. Per-mode views are more/better snapshots, not a live feed.
- **D2 — Per-mode snapshots are views of ONE screen, not new screens.**
  `building_panel` keeps a single override JSON; the exporter emits named
  views (`unlock`, `construct`, `upgrade`, `base_info`, `preview`) and the
  editor renders one view at a time. Override ids stay global to the screen.
- **D3 — Honest controls beat hidden no-ops.** Any editor control that cannot
  take effect (Color on a skinned button, label on code-owned text) is
  disabled with an explanatory tooltip — never silently accepted.
- **D4 — Display names are cosmetic.** A human label per widget id, shown in
  the editor UI only; the code id remains the contract everywhere on disk.
  Real renames stay dispatched agent tasks, not editor buttons.
- **D5 — Theme values move to `data/`** (`data/ui/fonts.json`,
  `data/ui/palette.json`, schema-validated) per the "data is the only value
  store" pillar. Engine reads them at boot with the current hardcoded values
  as schema-checked committed content — byte-identical rendering when the
  files match today's constants (parity-pinned).
- **D6 — Tint is additive.** Optional per-widget `tint` for skinned buttons
  multiplies the sheet at draw time; omitted = today's rendering, pinned.

## 3. Build order

| Phase | What | Status |
|-------|------|--------|
| UH-1 | Tools + data — per-mode snapshot exporter (`building_panel` views) | done — reviewed clean |
| UH-2 | Editor — per-mode screen views + auto Refresh Layouts on entry | done — reviewed; view tests pinned to a fixture |
| UH-3 | Editor — honest controls (grey-out no-op Color/label; tooltips) + pink-test verdict | done — 3 review rounds (panel/field/label fills); reconciled with UH-6 tint |
| UH-4 | Tools + editor — widget display-name layer | done — reviewed clean |
| UH-5 | Editor — "+ Button Type" (new ui slot-registry family) | done — reviewed clean |
| UH-6 | Engine + data + editor + game — theme data (fonts/palette) + Theme panel + optional skin tint | done — Tint editor-authorable for buttons + panels (UH-6 review) |

**Landed** on branch `phase-UH-1-UH-6-umbrella` (off `Development`) as one PR.
Full gate green (`1465 ran | 0 failures` at the button-only checkpoint;
re-certified after the buttons+panels tint reconciliation). **Naming
correction:** the phase text below writes `editor/main_window.py`; the real
file is `editor/main.py` (no `main_window.py` exists) — the phases edited
`editor/main.py`.

UH-1 → UH-2 is the only hard dependency chain. UH-3/UH-4/UH-5 are independent
of each other and of UH-1/2 (UH-4 touches the exporter — coordinate the
`screen_defaults.json` shape with UH-1 in the briefs). UH-6 is independent but
largest; last so the honest-editor wave lands even if UH-6 slips.

## 4. Phases

### UH-1 — Tools + data: per-mode snapshot exporter
- **Goal**: `screen_defaults.json` carries one clean snapshot per
  `building_panel` mode (`unlock`, `construct`, `upgrade`, `base_info`,
  `preview`) instead of one superimposed pile; other screens get a single
  implicit default view (no format churn for them).
- **Files**: mod `tools/export_ui_layouts.py` (per-mode mock states),
  `data/schemas/screen_defaults.schema.json` (optional `views` level),
  regenerate `data/ui/screen_defaults.json`; game side read of defaults is
  untouched (game never reads views).
- **Tests**: exporter staleness-diff test updated; per-view determinism
  (byte-idempotent, sha-measured like B3); schema validation via smoke.
- **Exit gate**: `py tools/smoke.py` + targeted gate green; committed defaults
  regenerated in the same commit as the exporter change.

### UH-2 — Editor: per-mode views + auto-refresh
- **Goal**: selecting Screens → Building Panel offers its five views, each an
  editable, uncluttered canvas (this IS the editor-side split of issues 5+6);
  entering screen mode auto-runs Refresh Layouts so snapshots can't be stale.
- **Files**: mod `editor/main.py` (selector sub-leaves / view picker),
  viewport screen mode + `editor/ui_screen_session.py` (current view state —
  overrides still write to the one screen JSON), `editor/panels/
  screen_details.py` (widget list filtered to the active view); auto-invoke
  the existing Refresh Layouts subprocess on screen-mode entry (reuse W3-6's
  `reload_assets()` entry hook).
- **Tests**: view switching shows/hides the right widget sets; overrides
  round-trip regardless of active view; auto-refresh fires once per entry
  (subprocess mocked); regression: non-building screens unchanged.
- **Exit gate**: targeted gate green. **Quick Test**: editor → Building Panel
  → `construct` view shows only construct widgets; drag one, Save, Play — the
  game's construct mode reflects it.

### UH-3 — Editor: honest controls + pink-test verdict
- **Goal**: no control silently no-ops (D3). Color picker disabled with
  tooltip "colors come from the sprite sheet" when the widget resolves to a
  skin; label edit disabled on code-owned (dynamic) text, enabled on static
  titles; disabled state recomputes when a skin is assigned/cleared.
- **Files**: mod `editor/panels/screen_details.py` (+ whatever small helper
  identifies code-owned labels from `screen_defaults` kinds — planner to pin).
- **Tests**: enabled/disabled matrix per widget kind × skinned/unskinned;
  tooltip text present; clearing a skin re-enables Color.
- **Exit gate**: targeted gate green. **Quick Test** (doubles as the
  artifact's "pink test"): set `text_color` pink on `boss_btn`, run the game —
  pink label appears, or the live bug is filed with a repro in the report.

### UH-4 — Tools + editor: widget display names
- **Goal**: every widget shows a human name ("Unlock / Build / Upgrade
  button") throughout the editor; code ids remain the on-disk contract (D4).
- **Files**: mod `tools/export_ui_layouts.py` + `screen_defaults.schema.json`
  (optional `display_name` per widget, authored as a mapping in the exporter —
  ids without one fall back to the id); mod `editor/panels/screen_details.py`
  + viewport labels to prefer `display_name` (id shown secondarily, e.g.
  tooltip/subtitle).
- **Tests**: exporter emits names for the mapped ids; editor list renders
  display names; fallback path for unmapped ids; override JSONs still keyed
  by code id (round-trip pin).
- **Exit gate**: targeted gate green; regenerated defaults committed.

### UH-5 — Editor: "+ Button Type"
- **Goal**: create a new button **family** (slot-registry stem under
  ui → Buttons) from the editor, beside "+ Variant" — new type is immediately
  importable and appears in every skin dropdown.
- **Files**: mod `editor/registry_ops.py` (new-family op, validated write to
  `data/slots.json`), `editor/main.py` (affordance + naming dialog),
  skin combo already registry-driven (verify, no change expected).
- **Tests**: registry_ops unit tests (name collision, schema-valid result,
  frame-size default per D-rules); editor integration: new family appears in
  tree + skin dropdown without restart.
- **Exit gate**: targeted gate green + `py tools/smoke.py`. **Quick Test**:
  add type `ui_button_tab`, import a 4-row sheet onto it, assign it to a
  widget, see it render in-game. (New *behavior* widget classes stay
  out of scope — game-code tasks, per the artifact's caveat.)

### UH-6 — Engine + data + editor + game: theme data
- **Goal**: fonts and the UI color palette become data (D5); a Theme panel
  edits them; optional `tint` recolors skinned buttons per widget (D6).
- **Files**: NEW `data/ui/fonts.json`, `data/ui/palette.json` + two schemas;
  mod `engine/render/fonts.py` (load presets from data; `layout_h` pinned
  table stays authoritative — W3-4 invariant must hold), palette constants'
  consumers in `game/ui/widgets.py`/screens re-pointed at the loaded palette;
  editor: NEW Theme panel (`/add-editor-feature`), font combo sourced from
  data; tint: `ui_screen.schema.json` optional `tint`, engine draw path
  multiply, details-panel color control repurposed honestly on skinned
  buttons (ties back to UH-3's tooltip).
- **Tests**: parity pin — stock fonts/palette files reproduce today's
  HUD-primitive stream byte-identical; `layout_h` invariant still green;
  schema validation; tint applied/omitted rendering tests; Theme panel
  round-trip via `write_validated`.
- **Exit gate**: targeted gate green + smoke. **Quick Test**: change the gold
  accent in the Theme panel, see menus recolor in-game; tint one button blue.

## 5. Risks / open items

- **Deferred by design (artifact wave 3)**: in-game building-panel split
  (design decision first → own plan) and true-WYSIWYG game-subprocess preview
  (own plan). Neither blocks UH-1..6.
- **Real widget renames** stay per-rename dispatched agent tasks (D4).
- **A6/B5 live Quick Tests from `UI_EDITOR_PLAN.md` are still pending** — run
  them before/alongside UH-1; several artifact symptoms may partly predate the
  July-19 wave-3 fixes.
- **`screen_defaults.json` merge friction** (known from 10L): UH-1 and UH-4
  both regenerate it — briefs must sequence the regeneration; resolve
  conflicts by re-running the exporter, never by hand.
- **UH-6 parity risk**: moving palette constants is wide but mechanical; the
  B2 golden parity pin + W3-4 `layout_h` invariant are the safety net — if
  either goes red, the phase is wrong, not the pin.
- **testgate `--affected` vacuous-pass bug** (`tools/testgate.py:222-238`,
  known from 10L): editor-tier-only phases must run their test modules
  explicitly until fixed.
