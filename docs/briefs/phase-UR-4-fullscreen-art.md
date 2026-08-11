# Phase UR-4 — Full-screen art at 640×360

Source plan: `planning/UiResolutionPLAN.md` §"Phase UR-4" (lines 184–206).
Assumes **UR-1 and UR-2 have landed**: `data/display.json` is `640×360` and the
UI constants have been converted.

---

## 1. Behavioral spec (with citations)

### 1.1 The plan's three claims, checked

**Claim A — "no screen JSON currently sets a `background` key". CONFIRMED
(measured).** `rg "background" data/ui/screens/` returns **zero** matches across
all 14 files:

| file | contents today |
|---|---|
| `add_name.json` | `widgets` only (2 button skins) |
| `boss_cutscene.json` | `widgets` only (`box_a`/`box_b` skins) |
| `building_panel.json` | `defaults` + `widgets` |
| `cheat_menu.json` | `widgets` only |
| `credits.json` | `widgets` only |
| `game_log.json` | `{}` |
| `game_over.json` | `widgets` only |
| `hud.json` | `widgets` (incl. UR-2's rect overrides) |
| `levelup.json` | `defaults.panel_skin` only |
| `main_menu.json` | `widgets` (incl. `backdrop` rect `[0,0,1280,720]`) |
| `overlays.json` | `widgets` only |
| `pause.json` | `widgets` only |
| `settings.json` | `widgets` (incl. rect overrides) |
| `tutorial_message.json` | `{}` |

The schema already permits the key: `data/schemas/ui_screen.schema.json` →
`properties.background` is a `oneOf` of `{slot: string}` / `{color: [3..4 ints]}`
(verified by loading the schema). Documented at `data/CLAUDE.md:477`.

**Claim B — "`submit_background` is therefore a no-op on every screen".
CONFIRMED (verified).** `ScreenSkinning.screen_background`
(`game/ui/skinning.py:157-167`) returns `None` when the loaded override has no
`background` key; `submit_background` (`game/ui/skinning.py:169-179`) returns
immediately on `None`. Its own docstring says so
(`game/ui/skinning.py:171-172`: *"A no-op with no `background` key (every
shipped screen JSON today)"*), and it is pinned by
`tools/tests/test_ui_skinning.py:653-660`
(`test_submit_background_draws_nothing_with_no_override`). There are **16 live
call sites**, one per screen `submit()`: `game/ui/add_name.py:130`,
`boss_cutscene.py:149`, `building_ui.py:1269`, `cheat_menu.py:225`,
`credits.py:85`, `debug_settings.py:170`, `game_over.py:66`,
`highscores.py:191`, `hud.py:393`, `levelup.py:111`, `main_menu.py:208`,
`pause.py:91`, `player_intro.py:175`, `settings.py:166`,
`tutorial_message.py:85`.

**Claim C — "`main_menu_bg` is unreferenced". REFUTED (verified).**
`main_menu_bg` is drawn every frame, by hardcoded slot key, not via the
skinning mechanism:
- `game/ui/main_menu.py:45` — `_BG_SLOT = "main_menu_bg"`
- `game/ui/main_menu.py:210` —
  `renderer.submit_hud(HudSprite(_BG_SLOT, (0, 0), (view_w, view_h)))`,
  submitted immediately *after* the no-op `submit_background` call on line 208
  and after the solid `HudRect` fallback on line 209.
- Documented at `game/ui/CLAUDE.md` ("Main-menu background (10K)") and
  `game/ui/main_menu.py:11-14`.

The slot that **is** unreferenced at runtime is the *other* one:
**`ui_bg_main_menu`**. No file under `game/` reads it. Its only producers/
consumers are `tools/bake_ui_sheets.py:281-284` (writes its manifest entry,
pointing at the shared `imported/main_menu_bg.png`, no byte copy) and
`editor/panels/screen_details.py:293-304` — the designer's **Background** combo
box, which populates from `registry.group_slots("ui", ("Backgrounds",))` and
writes `session.doc["background"] = {"slot": <key>}` (pinned by
`tools/tests/test_editor_viewport.py:1075-1079`).

**This is load-bearing for the phase:** the editor's background picker offers
**only the `ui` category's `Backgrounds` group** — i.e. exactly
`ui_bg_main_menu`. It does **not** offer the `backgrounds` category's
`main_menu_bg`. So the designer-facing `background` key can only ever name
`ui_bg_main_menu` today.

### 1.2 Every background slot and its current frame size (verified)

| slot | where declared | `frame_w` | `frame_h` | reachable from |
|---|---|---|---|---|
| `main_menu_bg` | `data/slots.json:1144`, inheriting the `backgrounds` category's `frame_w` (`:1139`) / `frame_h` (`:1138`); category block `:1133-1149` | **480** | **270** | code only — `game/ui/main_menu.py:45,210` |
| `ui_bg_main_menu` | `data/slots.json:806-810` — per-slot override object (`frame_h` `:807`, `frame_w` `:808`, `key` `:809`) inside the `ui` category's `Backgrounds` group (`:813`) | **480** | **270** | editor Background combo → screen JSON `background.slot` |

Manifest entries (both point at the **same** sheet):
- `main_menu_bg` — `data/sprites/asset_manifest.json:4411-4428`,
  `frame_h: 270`, `frame_w: 480`, `sheet: "imported/main_menu_bg.png"`.
- `ui_bg_main_menu` — `data/sprites/asset_manifest.json:7830-7849`, same sizes,
  same `sheet: "imported/main_menu_bg.png"`.

**The sheet itself is 480×270 (measured** — `PIL.Image.open(
"data/sprites/imported/main_menu_bg.png").size == (480, 270)`**).**

**No 640×360 image exists anywhere in the repo (measured** — a PIL walk over
every `.png`/`.jpg` outside `.git`/`graphify-out` found zero files at
`(640, 360)`; the only large art is enemy/building sheets at 512×384 …
1088×864, plus `editor/assets/thats_my_producer.png` at 775×570**).**

### 1.3 What the slot frame size actually controls (verified — read this before editing)

`AssetStore.frame_size` (`engine/assets/store.py:52-62`) resolves
**manifest entry > registry (slots.json) > override map > default**. The
manifest wins. Therefore:

> **Editing `data/slots.json`'s background frame sizes changes ZERO drawn
> pixels.** It changes how the importer *slices a newly imported sheet*
> (`data/CLAUDE.md:315-322` — the override exists so a 480×270 whole-sheet
> background is not grid-sliced into a 7×4 grid inside the 64×64 `ui`
> category). The on-screen size is the render fit; `main_menu.py:210` already
> stretches the frame to `(view_w, view_h)` whatever it is.

This is why the wiring half of this phase is safe and invisible, and why the
crispness win in the exit gate depends entirely on new art.

### 1.4 Which screens *should* carry a `background` key

Honest answer for **this** phase: **none of them can gain one that produces a
correct picture today**, because the only art in the repo is the main-menu
painting and the one screen that wants it already draws it in code.

- `main_menu` — the only screen with art. Adding
  `"background": {"slot": "ui_bg_main_menu"}` to `data/ui/screens/main_menu.json`
  **without** removing `game/ui/main_menu.py:210` **double-draws the same PNG**
  (`submit_background` at line 208 draws `HudSprite(slot, (0,0), (view_w,
  view_h))`, then line 210 draws the identical sprite). That is a visible
  no-change but a real defect — two draw calls per frame for one image, and a
  golden-parity stream change. See §2 for the two options.
- `pause`, `settings`, `credits`, `game_over`, `highscores`, `add_name`,
  `boss_cutscene`, `player_intro` — the plausible future consumers of a
  full-screen background. **All of them lack art.** Wiring a `background` key on
  any of them today would point at `ui_bg_main_menu` (the menu painting) behind
  an unrelated screen. Do not.
- `hud`, `building_panel`, `game_log`, `overlays`, `tutorial_message`,
  `levelup`, `cheat_menu` — in-world / overlay surfaces. A full-view opaque
  background would occlude the game. **Never** give these a `background` slot.

---

## 2. Architecture plan

Two separable pieces. **(a) is fully doable in code; (b) is not.**

### (a) Data / wiring — do this

1. **Slot frame sizes 480×270 → 640×360**, through the validating writer
   (`engine.data_io.write_validated`; `data/CLAUDE.md` — agents may write
   schema-valid JSON, humans never hand-edit):
   - `data/slots.json:1138-1139` — the `backgrounds` category's `frame_h`/
     `frame_w`.
   - `data/slots.json:807-808` — `ui_bg_main_menu`'s per-slot override.
   Both must move **together**; they describe the same painting cut two ways.
2. **`tools/bake_ui_sheets.py:281-283`** hardcodes `480, 270` when it writes the
   `ui_bg_main_menu` manifest entry. If the slot registry says 640×360 and the
   baker says 480×270, the next `py tools/bake_ui_sheets.py` silently
   re-installs the old size. Update the literal in the same commit (and the
   module docstring at `tools/bake_ui_sheets.py:7`'s sibling note in
   `tools/tests/test_bake_ui_sheets.py:7`). **Flagged as a scope extension
   beyond the plan's file list — it is one literal, and leaving it is a landmine.**
3. **Screen JSONs — the `background` key.** Per §1.4 there is exactly one
   defensible edit, and it is a *decision*, not a mechanical change:
   - **Option A (default — recommended): change nothing under
     `data/ui/screens/`.** `submit_background` stays a no-op, `main_menu.py:210`
     keeps drawing the art, and the phase ships pure frame-size wiring. Zero
     risk, zero double-draw, and the `background` mechanism stays available the
     day art exists. The plan's "wire them in" goal is then only *partly* met —
     say so in the handback.
   - **Option B (only on explicit orchestrator/user go-ahead): migrate
     `main_menu` off the hardcode.** Add
     `"background": {"slot": "ui_bg_main_menu"}` to
     `data/ui/screens/main_menu.json` **and** delete `game/ui/main_menu.py:210`
     (plus `_BG_SLOT` at `:45` and the `HudSprite` import if it becomes unused,
     and the docstring paragraph at `:11-14`). This makes the designer's editor
     combo the real control surface and removes a code-owned art reference.
     **Costs**: it touches `game/ui/`, which is outside the plan's stated UR-4
     file scope; it changes the `main_menu` entry of the golden parity stream
     (`tools/tests/test_ui_skinning.py:211` `_BASELINE`, asserted at `:464-471`)
     — a baseline UR-2 has *already* re-pinned, so this is a second re-pin on
     the same artifact; and it requires updating `game/ui/CLAUDE.md`'s
     "Main-menu background (10K)" paragraph. **Do not do this silently.**
4. **`data/CLAUDE.md`** — the plan says "two places". There are **three**
   (verified): `:319` (`ui_bg_main_menu` (480×270, a whole-sheet background …)),
   `:326` (`ui_bg_main_menu_v2` inherits the … 480×270 override), `:387`
   (frame-sizes list: *ui / vfx 64×64 (except `ui_bg_main_menu`, 480×270 …);
   backgrounds 480×270*). Update all three.

### (b) The art recut — the coder CANNOT do this

**There is no 640×360 source art in this repo (measured, §1.2).** The only
background painting is `data/sprites/imported/main_menu_bg.png` at 480×270.

- **Upscaling 480×270 → 640×360 is a 1.333× non-integer resample.** It would
  destroy the pixel grid — the exact artefact class the exit gate ("crisp at 2×,
  no resampling artefacts") is written to catch. It is *worse* than today, where
  the stretch at least happens once, in SDL, at draw time.
- **Generating new art is out of scope for an implementation agent.** Do not
  produce, synthesise, upscale, or "temporarily" substitute a background image.
  Do not commit any new PNG.

**What the coder does instead:**
1. Do all of (a). Leave `data/sprites/asset_manifest.json` and
   `data/sprites/imported/*.png` **untouched** — the entries stay at 480×270 and
   keep rendering exactly as they do today (manifest wins, §1.3).
2. Report the missing asset explicitly in the handback: *"UR-4's art half is
   blocked: `data/sprites/imported/main_menu_bg.png` is 480×270 and no 640×360
   source exists. Slot registry now expects 640×360 for the `backgrounds`
   category and `ui_bg_main_menu`; the manifest entries are deliberately stale
   until a human supplies a 640×360 painting."*
3. Record the canonical swap path so the human can finish it in one command —
   `.claude/commands/replace-visual.md` (the `/replace-visual` skill), whose
   idle-only branch is:
   ```
   py -c "from editor import asset_import; from engine.assets.registry import load_registry; reg=load_registry('data'); asset_import.import_idle_sheet('data', reg, 'main_menu_bg', r'<path-to-640x360.png>'); print('imported')"
   ```
   `import_idle_sheet` copies the sheet to `data/sprites/imported/main_menu_bg.png`
   and writes the one `idle` row through `write_validated` — **the sole writer**;
   the manifest is never hand-formatted. `ui_bg_main_menu` then picks the new
   size up by re-running `py tools/bake_ui_sheets.py` (it shares the sheet,
   `tools/bake_ui_sheets.py:278-284`).

**Order matters:** doing (a) first is what makes the future import slice
correctly. A 640×360 sheet imported against a 480×270 slot would be sliced
wrong.

---

## 3. File scope + shared-file contract

**May edit:**

| file | change |
|---|---|
| `data/slots.json` | `:1138`/`:1139` and `:807`/`:808` → `360`/`640`. Through the validating writer. Nothing else in the file. |
| `data/CLAUDE.md` | three 480×270 mentions (`:319`, `:326`, `:387`) → 640×360. |
| `tools/bake_ui_sheets.py` | `:282` literal `480, 270` → `640, 360` (+ the docstring note at `:7`). |
| `tools/tests/test_bake_ui_sheets.py` | docstring at `:7` names the 480×270 exception. |
| `tools/tests/fixtures/data/slots.json` | the mirrored frame sizes — see the fixture contract below. |
| `tools/tests/test_assets_registry.py` | `:38`, `:56` assert `(480, 270)`. |
| `tools/tests/test_registry_ops.py` | `:142-151`, `:177-205` assert/comment `480x270`. |
| `data/ui/screens/main_menu.json` | **only under Option B** (§2.3), and only with explicit sign-off. |
| `game/ui/main_menu.py`, `game/ui/CLAUDE.md`, `tools/tests/test_ui_skinning.py` | **only under Option B.** |

**Must NOT edit:** `data/sprites/asset_manifest.json`,
`data/sprites/imported/*` (art half is blocked — §2b);
`data/ui/screen_defaults.json` (generated; UR-2 owns its regeneration);
`data/display.json` (UR-2); any `game/ui/*.py` under Option A.

### Shared-file contract with UR-2 (state this precisely; it is the merge)

`data/ui/screens/hud.json`, `settings.json` and `main_menu.json` are touched by
both phases, at **disjoint JSON paths**:

- **UR-2 owns `widgets.*.rect`** — the 12 hardcoded rect overrides
  (`hud.json` 4, `settings.json` 5, `main_menu.json` 3, incl. the
  `backdrop` `[0,0,1280,720]` entries), halved to 640-scale.
  `planning/UiResolutionPLAN.md:141-142`. **UR-4 must not touch any `rect`,
  any `skin`, or any other key under `widgets`.**
- **UR-4 owns only a NEW top-level `background` key** — a sibling of `widgets`
  and `defaults`, never nested inside them
  (`data/schemas/ui_screen.schema.json` → root `properties.background`), and
  only in the Option-B case. **UR-4 must not add, remove or reorder any
  `widgets` entry.**

Because both phases write through the validating writer (sorted keys, 2-space
indent), a conflict on these files is textual only: keep UR-2's `widgets` block
verbatim and re-add UR-4's `background` key at the root. If UR-4 runs as
Option A (recommended), **there is no overlap at all** — UR-4 touches no file
under `data/ui/screens/`.

### Fixture contract (this is where the change is actually observable)

Every value-asserting test reads the pinned snapshot
`tools/tests/fixtures/data/` (`tools/tests/fixture_data.py:1-22`), enforced by
`tools/tests/test_fixture_guard.py`. `tools/tests/test_assets_registry.py:13,27`
loads `FIXTURE_DATA`, and `ScreenSkinningCase`
(`tools/tests/test_ui_skinning.py:475-483`) copies the fixture — **which ships
no `data/ui/screens/` at all**. Consequence (verified): editing live
`data/slots.json` or a live screen JSON is **invisible to the whole suite**
except for `py tools/smoke.py`'s schema validation.

So the *only* way this phase gets a real gate is to move the fixture too.
**Do the surgical edit, not the refresh:** hand-edit the two frame-size pairs
in `tools/tests/fixtures/data/slots.json` (the `backgrounds` category and the
`ui_bg_main_menu` override) to 640×360, then update the four assertion sites
listed in the table above. **Do NOT run
`py tools/tests/fixture_data.py --refresh`** — it re-mirrors *all* live JSON and
would drag UR-2's `display.json` flip and rect halvings into the pin in the same
commit, with an unbounded blast radius across pinned tests. (If the orchestrator
wants a full refresh, it belongs in its own step after UR-5, not here.)

---

## 4. Exit gate + Quick Test

### Commands (run exactly these — **not** the full suite, **not** `--affected`)

```
py tools/smoke.py
py -m pytest tools/tests/test_assets_registry.py tools/tests/test_registry_ops.py tools/tests/test_bake_ui_sheets.py tools/tests/test_assets_manifest.py tools/tests/test_fixture_guard.py -q
```

Add `tools/tests/test_ui_skinning.py` to that pytest list **only if Option B was
taken** (it owns the `main_menu` golden baseline and the `background`
mechanism's own tests).

**Bare-minimum new coverage — one test, no more.** In
`tools/tests/test_assets_registry.py`, beside `test_main_menu_background_slot`
(`:37-40`), assert against the fixture registry that the two background slots
agree on the new size:

```python
def test_background_slots_are_full_surface_640x360(self):
    self.assertEqual(self.reg.frame_size("main_menu_bg"), (640, 360))
    self.assertEqual(self.reg.frame_size("ui_bg_main_menu"), (640, 360))
```

(The existing `:38` and `:56` assertions are the same claim at the old value —
update them rather than duplicating.) Do **not** add a live-data consistency
test comparing the manifest's frame size against the registry's: they are
*deliberately* divergent until the art lands (§2b), and such a test would
encode the blocked state as a failure.

### Definition of done for this phase

- `GATE PASS` on the two commands above; `py tools/testgate.py check` run once
  at handback (orchestrator's call — do not run it mid-task).
- `data/slots.json`, `data/CLAUDE.md`, `tools/bake_ui_sheets.py` and the fixture
  all say 640×360; no PNG and no manifest entry changed.
- The handback names the blocked asset explicitly (§2b step 2).

### Quick Test (in-game)

1. `py game/main.py` on a 1280×720 window (SCALED gives an exact integer 2× of
   the 640×360 logical surface after UR-2).
2. Main menu appears; the painting fills the frame with no letterboxing of the
   art itself and no clipping of the title/button stack.
3. **Expected result today: the background looks exactly as it did before this
   phase** — still the 480×270 sheet stretched to the full view. That is the
   correct outcome of the wiring-only change and is *not* a bug. The plan's exit
   criterion ("crisp at 2×, no resampling artefacts") **cannot be met until a
   640×360 painting is imported** and is therefore *not* satisfied by this
   phase.
4. Regression check: click through MAIN MENU → SETTINGS → BACK → CREDITS →
   BACK → START NEW GAME. No screen may show a stray full-screen image (proves
   no `background` key leaked onto the wrong screen), and the main menu must not
   dim or double-darken (proves no double-draw under Option B).
5. Post-art re-test (for whoever supplies the painting): after
   `/replace-visual main_menu_bg <640x360.png>` + `py tools/bake_ui_sheets.py`,
   repeat step 2 and confirm hard pixel edges at 2× with no interpolation
   fringing.

---

## Open questions for the orchestrator / user

1. **Option A or Option B (§2.3)?** A is safe and leaves `submit_background`
   a no-op on every screen — i.e. the plan's "wire them in" goal only half-met.
   B genuinely wires it but reaches into `game/ui/main_menu.py` and re-pins the
   `main_menu` golden baseline a second time after UR-2. **Recommendation: A**,
   with B split out as its own small follow-up once art exists.
2. **Who supplies the 640×360 painting?** Until someone does, UR-4's exit gate
   as written in the plan is unreachable. Consider re-labelling the phase
   "UR-4 — background wiring at 640×360" and moving the crispness criterion to a
   follow-up art task.
3. **`tools/bake_ui_sheets.py:282`** is outside the plan's file list but holds
   the same magic number. Confirm it is in scope (recommendation: yes).
4. **Fixture policy** — surgical edit (recommended) vs. deferred full
   `--refresh` after UR-5.
