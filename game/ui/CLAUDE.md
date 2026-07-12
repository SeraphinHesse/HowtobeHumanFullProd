# CLAUDE.md — game/ui (Phases 9G + 9H + 10A UI)

HUD, building panel, floaters, game over, and the top-level shell/menus. You
reached here from `game/CLAUDE.md`. When you change UI conventions, update THIS
doc.

**Layering rule: `game.ui → game.core` is ONE-WAY** (`hud.py` imports
`game.core.phases`). `game/ui` is **pygame-free** like all UI logic (a source-scan
`TestPurity` guards it — it may import `engine.render.fonts`, a sanctioned pygame
module, so it imports pygame only *transitively*); visuals go out as the engine
HUD layer (G-6). The shell therefore lives in **`game/ui/shell.py`**, NOT
`game/core` (that would be circular).

## In-round UI (9G)
`game/ui/{widgets,hud,building_ui,effects,game_over}.py`: HUD (love panel, round,
base HP, End Turn, phase banner), unlock/construct/upgrade/base-info panel modes,
ConstructPreview (name entry, confirm/cancel per `ui.Timing`), income/upkeep
floaters, not-enough-love flash, building HP bars; input routing + click-consume
priority in `game/main.py`. Every menu screen mirrors the `game_over.py`
construct→layout→update→hit→submit template + `widgets.Button`.

## Level-up UI (10A)
`game/ui/levelup.py` (`LevelupWindow`, the `game_over.py` template; it lays out on
`open` because hover/hit run before the first `submit`), an XP bar + `LVL N` in
`hud.py` (gold + pulsing when pending), purple XP floaters via
`FloaterManager.spawn_xp_events` (drained every frame, not at a phase edge), and
the gated construct list + five-mode upgrade button in `building_ui.py`. The modal
sits at the TOP of `main.py`'s click ladder and swallows keys. (The pure roll/gate
logic is `game/core` — see that doc.)

## Shell + menus (9H)
`game/ui/shell.py` wraps a run — ports the prototype's `GameState` shell
(`src/core/game.py` dispatch):
- **`Shell` is pure** (pygame-free; a source-scan purity test in `test_shell.py`
  guards it). It owns `state` (`GameState`), the five menu screens
  (`main_menu`/`settings`/`credits`/`add_name`/`pause`, each the `game_over.py`
  template), the session-only `SessionSettings`, and `settings_caller` (SETTINGS is
  reused for both entry points — NO `SETTINGS_PAUSED` state). It applies pure
  transitions itself and returns an **intent string** only for host-side
  (pygame/disk) actions: `new_game` / `quit_to_menu` / `quit_app` /
  `set_display_mode` / `add_name_commit`.
- **The host (`main.py`) executes intents + owns the pygame-only concerns** the
  pure shell can't: window (re)creation (`_apply_display_mode` — SCALED keeps the
  logical surface `view_w×view_h` in all three modes so coords/renderer/hit-rects
  never change, E-5), the cutscene raw-surface blit, `engine.audio.play_music` (one
  looping track; windowed runs only), and the `_World` lifecycle
  (`build_gameplay`/`teardown_gameplay` — a fresh `_World` = a fresh run; menus
  hold NO world). The frame loop is three per-`shell.state` switches
  (input / update / render); the 9G in-round click ladder runs only in GAMEPLAY.
  Esc opens PAUSE in gameplay / backs out of menus (was: quit).
- **Cutscene = FULL video** via the 9B `engine.video.VideoSource`
  (`data/video/cutscene.mp4`, length from `ui.json Menu.cutscene_length`);
  graceful-skips to MAIN_MENU when cv2/file absent (headless).
- **ADD_NAME persists** via `game/core/names.py append_random_name` (see
  `game/core/CLAUDE.md`); the host also appends to the in-memory `buildings_balance`
  so it goes live.
- **Headless seam**: `main(autostart=True)` skips the shell straight into GAMEPLAY
  so `tools/smoke.py` + the boot tests still exercise the full `_World`/`Session`
  construction + sim the menu would otherwise defer.
- **Deferred**: main-menu background art + the pause dim overlay (the HUD pass has
  no per-pixel alpha) are host raw-surface concerns, not yet wired; the settings
  audio slider is inert (no audio system beyond music).

## Defence FX (10B)
`effects.py` `FloaterManager` grew `submit_beams` + `submit_craters`, drawn from
live scene state (like `submit_hp_bars`): a per-tier colored `HudLines` from each
firing Sun Scorcher to the enemy its `BeamAttacker._target` names, and a fading
world-space diamond for each `"crater"` GameObject a mortar shell left (the
`Crater` objects age + self-despawn in the scene; the FX just draws them). This is
the sanctioned `game/ui → game/buildings.components` read (building_ui already
imports it). Alpha-true glow/ellipse is deferred to 10J (the HUD/overlay pass has
no per-pixel alpha — same limit as the opaque level-up backdrop).

## Map overlays + terrain badges (10I)
`game/ui/overlays.py` (`MapOverlays`, pure — covered by the purity scan) owns
ALL of 10I's UI so `hud.py` (10G boss bar + 10H lightning both edit it) carries
no 10I diff: two persistent bottom-left toggle pills (`RANGE`/`HEATMAP`, gold
rim + gold label when active; clicks consumed in `main.py`'s ladder between the
End-Turn branch and the panel, `over()` feeds the pan-arming `over_ui` check),
the world condition tint (windowed — never a full-grid scan), the RANGE overlay
(union Chebyshev squares from RAW `range_tiles()`, mortar INCLUDED — its
exclusion is pathfinding-only — plus a cardinal plus-shape per `"boost"`
occupant), and the HEATMAP overlay (previous round's distinct-enemy traffic:
`track()` accumulates `id(e)` per tile during ENEMY and snapshots counts on the
phase edge; blue→yellow→red ramp in `heat_color`). `widgets.COND_LABELS`
(condition label + colour, keyed by `TileCondition.name`) is shared with
`building_ui`'s new terrain badges: a `Terrain: <Label>` pill in the upgrade
panel (below Level, reads the building's `_tile_condition` snapshot) and at the
unlock/construct panel foot (reads the tile), each with a hover tooltip whose
effect lines read LIVE from `TileConditions.modifiers` (enemy effects
deliberately unlisted, prototype-exact); the tooltip draws last/on top.
`base_info` shows NO badge. The panel Range row + selection range highlight use
`effective_range_tiles()` when present (mountain +1); the RANGE overlay stays
raw.

## Known divergences (deliberate)
The level-up window backdrop is OPAQUE — the HUD pass has no per-pixel alpha, the
same limit that deferred 9H's pause dim (10J). The XP bar/floaters drop the
prototype's mascot face + `xp_icon`, which has no slot in `data/slots.json` (10J).
The 10I condition tint + RANGE/HEATMAP overlays render as diamond OUTLINES
(prototype colours verbatim, alpha dropped) — the engine overlay pass draws
outline polylines only; alpha-filled parity lands with the 10J FX sweep.

## Verify
Live mouse-only loop — unlock, build both types, upgrade to tier 2, lose → game
over screen; cold `py game/main.py`: cutscene → menu → rounds → pause/settings →
add name → credits. Purity test in the suite:
`py -m unittest discover -s tools/tests -t .`.
