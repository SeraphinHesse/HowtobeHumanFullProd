# UiResolutionPLAN.md — one UI coordinate space at 640×360

## 1. Context

The game's logical surface is **1280×720** (`data/display.json` →
`game/main.py:219` → every screen constructor). But the UI inside it is
authored in **two different scales at once**:

| Thing | Committed value | Scale it implies |
|---|---|---|
| `main_menu` buttons | `[480, 300, 320, 52]` | 1280×720 |
| `pause` buttons | `[520, 284, 240, 46]` | 1280×720 |
| `hud` icons | `icon_love [18, 20, 18, 18]` | 640×360 |
| `data/ui/fonts.json` | `sm 9` … `xxl 26` | 640×360 |

The migration doubled *positions* and left *element sizes and font presets* at
the prototype's 640×360 scale. That is why the UI reads as tiny: 13px bold text
on a 52px-tall button, 18px icons on a 720px-tall screen.

The fix is to stop straddling and commit to **640×360 as the one logical
surface**, which is the prototype's internal resolution
(`planning/planning resources/MIGRATION_AGENT_READ_FIRST.md:141`). `pygame.SCALED`
(already on, `game/main.py:133`) upscales it to the monitor and remaps mouse
coords back down, so hit-testing, `handle_click(mx, my)` and every widget rect
keep working untouched. Full-screen art then lands at an exact integer 2× on a
1280×720 monitor instead of today's 2.667× stretch from 480×270.

**Scope decision (user, at plan time): UI only. The world zoom retune is
deferred.** See §3 — this is the one place the plan knowingly ships a visible
change it does not resolve.

## 2. Architecture

Nothing new is built. The resolution is already data-driven in the game; the
work is (a) removing the places that hardcode 1280×720 anyway, (b) flipping
`data/display.json`, (c) converting the 1280-scale constants down.

- **The surface** — `data/display.json`'s `window_w`/`window_h`. `game/main.py`
  reads it into `view_w, view_h` and passes it to every screen. Never
  hardcoded there. → `game/CLAUDE.md` (host conventions).
- **Screen layout** — each `game/ui/*.py` screen lays itself out from
  `view_w`/`view_h` (12–16 references per file) plus absolute pixel constants.
  The relative half adapts for free; the absolute half is the work.
  → `game/ui/CLAUDE.md`.
- **Committed layout data** — only **12 hardcoded rects exist**, in
  `hud.json` (4), `settings.json` (5), `main_menu.json` (3). Every other screen
  JSON has zero. `data/ui/screen_defaults.json` is **generated** by
  `tools/export_ui_layouts.py`, which already reads `display.json` and never
  hardcodes (its own §1 note) — it regenerates for free.
  → `data/CLAUDE.md` (UI screen data).
- **The editor preview** — `editor/panels/viewport.py:97`,
  `SCREEN_W, SCREEN_H = 1280, 720`, commented "data/display.json's canonical
  resolution" while not reading it. One constant, four prose references
  (lines 11, 25, 414, 515) and `NUDGE_STEP` (line 102, logical px).
  → `editor/panels/CLAUDE.md`.

### The conversion rule (the subtle part — do not blind-`sed` this)

A blind ÷2 is **wrong**, because the tree is mixed-scale. Per constant:

- **Halve it** if it is 1280-scale: anything positioned against, derived from,
  or compared to `view_w`/`view_h`; button/panel widths and heights; the 12
  JSON rects; `backdrop [0,0,1280,720]` entries.
- **Leave it** if it is already 640-scale: `data/ui/fonts.json`'s 7 presets,
  the 18×18 HUD icons, and any other element size that already looks
  prototype-sized. These become *correct* the moment the surface halves —
  halving them again is the bug this plan exists to remove.

Deciding which bucket a constant is in is the actual work of UR-2, and is why
UR-5 (eyeball pass) is a real phase and not a formality.

## 3. Deferred: the world comes along with the surface

The world renders into the **same** surface. Flipping to 640×360 means that at
`geometry.json`'s current `zoom_levels [1.0, 2.0, 4.0]` with 64×32 iso tiles,
the player sees roughly **a quarter of the board** at a given zoom level.

The user chose to defer the zoom retune, so this plan **accepts the framing
change and does not fix it**. Consequences, stated plainly:

- UR-2's playtest will show a correct-looking UI over a too-close world.
- Halving `zoom_levels` to `[0.5, 1.0, 2.0]` restores today's framing at the
  cost of downscaled world art; keeping them is prototype-faithful (that build
  ran a 320×180 gameplay surface at 2×). Neither is chosen here.
- This is a `game/map` + `data/geometry.json` concern and belongs in its own
  plan. Tracked in §5.

## 4. Build order

| Phase | Scope | Status |
|-------|-------|--------|
| UR-1  | De-hardcode the resolution (game + editor + tools) | not started |
| UR-2  | Flip the surface to 640×360 + convert UI layout constants | not started |
| UR-3  | Editor screen-preview parity at 640×360 | not started |
| UR-4  | Full-screen art recut 480×270 → 640×360 and wire it in | not started |
| UR-5  | Eyeball / playtest polish pass | not started |

UR-1 is pure prep and lands green with **zero visual change** — it is what makes
UR-2 a one-file flip instead of a hunt. UR-3 and UR-4 are independent of each
other and both depend on UR-2. UR-5 is last by definition.

---

### Phase UR-1 — De-hardcode the resolution

**Goal.** After this phase, exactly one place in the repo states the logical
resolution: `data/display.json`. Nothing else contains a literal 1280 or 720
that means "the screen". No visual change — the value is still 1280×720.

**Files.**
- Modified: `editor/panels/viewport.py` — `SCREEN_W`/`SCREEN_H` read
  `data/display.json` (the editor already loads `data/`; use the existing
  loader, do not add a second read path). Update the four prose references and
  `NUDGE_STEP`'s comment to stop naming a literal size.
- Modified: `editor/panels/CLAUDE.md` — screen-mode section says "the canvas is
  `display.json`'s resolution", not "1280×720".
- Audit only (fix if found): `game/**`, `tools/**` for any other literal screen
  size. `tools/export_ui_layouts.py` is already clean — confirm, don't change.

**Tests.** `tools/tests/test_editor_viewport.py` (7 references to the literals)
switches to asserting against the loaded value rather than the constant.

**Exit gate.** `py tools/smoke.py` · `py tools/testgate.py check` → GATE PASS.
Game and editor render pixel-identically to before (nothing moved).

---

### Phase UR-2 — Flip the surface + convert UI layout constants

**Goal.** `data/display.json` is 640×360 and every screen lays out correctly in
it. This is the big phase; it is coupled by nature — the surface and the
constants cannot flip separately without shipping a broken tree in between.

**Files.**
- Modified: `data/display.json` — `window_w: 640`, `window_h: 360`.
- Modified: `game/ui/*.py` — the absolute pixel constants in each screen's
  layout, per the §2 conversion rule. `building_ui.py`, `levelup.py`,
  `main_menu.py`, `boss_cutscene.py`, `hud.py`, `pause.py`, `highscores.py`,
  `game_over.py`, `cheat_menu.py`, `credits.py`, `shell.py`,
  `tutorial_message.py`, plus shared chrome in `widgets.py`.
- Modified: `data/ui/screens/hud.json`, `settings.json`, `main_menu.json` — the
  12 rect overrides, halved.
- Regenerated: `data/ui/screen_defaults.json` via `py tools/export_ui_layouts.py`.
  **Never hand-edit** — it is generated-but-committed and a test re-runs the
  exporter.
- **Unchanged, deliberately:** `data/ui/fonts.json`, `data/geometry.json`.

**Tests.** ~14 test files reference the literals; the load-bearing ones are
`test_ui_skinning.py` (11 refs, incl. the golden baseline) and `test_hud_panel.py`,
`test_shell.py`, `test_screen_honest_controls.py`, `test_levelup.py`,
`test_button_skin.py`, `test_10j_qol.py`, `test_right_click_dismiss.py`,
`test_player_identity.py`. Re-pin the golden baseline to the new geometry —
**re-pin, do not delete**: it is the only thing that catches an accidental
re-scale later. Bare-minimum new tests only.

**Exit gate.** `py tools/smoke.py` · `py tools/testgate.py check` → GATE PASS.
Then `py game/main.py`: main menu, pause, HUD, building panel and level-up all
render inside the frame with no clipping or overlap. Expect the world to look
too close — that is §3, not a bug in this phase.

---

### Phase UR-3 — Editor screen-preview parity

**Goal.** A designer laying out a screen in the editor sees what the game
draws. Depends on UR-1 (the constant already reads `display.json`) and UR-2
(the value is now 640×360), so this phase is about the preview *behaving* well
on a canvas a quarter the area — scale-to-fit, grid, and a 1px nudge that is now
twice as coarse relative to the screen.

**Files.**
- Modified: `editor/panels/viewport.py` — scale-to-fit and letterbox math at the
  new canvas (lines ~414, ~515); revisit `NUDGE_STEP` (1 logical px is now a
  bigger visual step — keep it at 1 unless the playtest says otherwise).
- Modified: `editor/panels/CLAUDE.md` if the preview's behaviour changes.

**Tests.** `tools/tests/test_editor_viewport.py` — the `-m editor` (Qt) tier.

**Exit gate.** GATE PASS. Open the editor, select a UI-screen leaf, confirm the
preview matches a screenshot of the same screen in-game.

---

### Phase UR-4 — Full-screen art at 640×360

**Goal.** Whole-screen backgrounds are cut at 640×360 and blit 1:1 into the
surface, replacing today's 480×270 → 2.667× stretch. Also *wire them in*: no
screen JSON currently sets a `background` key at all, so
`ScreenSkinning.submit_background` (`game/ui/skinning.py:169`) is a no-op on
every screen today and `main_menu_bg` is unreferenced.

**Files.**
- Modified: `data/slots.json` — `backgrounds` category `frame_w`/`frame_h`
  480×270 → 640×360; `ui_bg_main_menu`'s per-slot override likewise. Use
  `/replace-visual` for the art swap rather than hand-editing the manifest.
- Modified: `data/sprites/asset_manifest.json` + `data/sprites/imported/*.png`
  — via the editor's import path only (it is the sole writer).
- Modified: the screen JSONs that should carry a background key.
- Modified: `data/CLAUDE.md` — the frame-sizes list names 480×270 in two places.

**Tests.** Bare minimum — a slot/manifest validation test. The art itself is
verified by eye.

**Exit gate.** GATE PASS. Main menu background is crisp at 2× on a 1280×720
window, with no resampling artefacts.

---

### Phase UR-5 — Eyeball / playtest polish

**Goal.** Fix what the conversion rule got wrong. This phase exists because §2
says the tree is mixed-scale and some constants' bucket is a judgement call.

**Files.** Whatever the playtest surfaces — expected: odd-pixel rounding from
halving an odd number, text now overflowing a halved container, click targets
too small at 640×360 (a 46px button became 23px), spacing that read fine at
2× and is cramped at 1×.

**Tests.** Update pins for anything that moves. No new coverage expected.

**Exit gate.** GATE PASS **plus explicit user sign-off from a live playtest** —
this is the one phase whose exit criterion is a human eye, not a command.

---

## 5. Risks / open items

- **The world framing is knowingly wrong from UR-2 until a follow-up plan.**
  §3. The single biggest thing a reviewer or playtester will notice, and it is
  deliberate. Needs its own plan covering `data/geometry.json`'s `zoom_levels`,
  camera clamp, and `visible_tile_window` culling margins.
- **Click targets shrink.** Every button halves in logical pixels. `SCALED`
  means they occupy the same *physical* screen area, so this should be neutral
  — but sub-pixel rounding in the mouse remap at non-integer monitor scales
  could make edges of small controls unreliable. Worth a deliberate check in
  UR-5.
- **`SCALED` is only an integer multiple on standard 16:9 sizes** — exactly 2×
  at 1280×720, 3× at 1920×1080, 4× at 2560×1440, but not on 1366×768. Pixel art
  will resample unevenly there. Not solved by this plan; note it if it bites.
- **The golden baseline in `test_ui_skinning.py` must be re-pinned, not
  deleted.** It is the regression net for exactly this class of change, and
  `data/CLAUDE.md`'s standing warning about tests asserting against live data
  applies — pin the fixture.
- **Fonts may need re-tuning after all.** The plan asserts the 7 presets are
  already 640-scale and should be left alone. If UR-5 shows they were tuned for
  the *stretched* look rather than the prototype's, the fix is a `fonts.json`
  edit through the editor's Theme panel — data, not code.
- **`data/ui/screen_defaults.json` merge conflicts** resolve by re-running the
  exporter (deterministic), never by hand.
