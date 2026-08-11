# Phase UR-2 — Flip the surface to 640×360 + convert UI layout constants

Source plan: `planning/UiResolutionPLAN.md` §2 (the conversion rule), §3
(deferred world zoom), "Phase UR-2". Package: `game/ui` (`game/ui/CLAUDE.md`)
plus three `data/ui/screens/*.json` files (`data/CLAUDE.md`).

**Read this first — the one thing that will look wrong and must NOT be
"fixed" here.** After this phase the WORLD renders too close: the surface
halves but `data/geometry.json`'s `zoom_levels [1.0, 2.0, 4.0]` and the 64×32
iso tile pitch do not, so roughly a quarter of the board is visible at a given
zoom step. That is `planning/UiResolutionPLAN.md:72-86` (§3), **deferred and
deliberate by the user's own scope decision**, and it belongs to a separate
future plan covering `zoom_levels`, the camera clamp and
`visible_tile_window` culling. **Do not touch `data/geometry.json`, do not
touch `game/map/`, do not "compensate" by scaling anything in the world
render path.** If a reviewer or playtester reports it, the answer is §3.

Bare-minimum new tests only. Existing pins get re-pinned, never deleted or
relaxed.

---

## 1. Behavioral spec — the constant inventory

### 1.0 The rule, stated executably

Per `planning/UiResolutionPLAN.md:57-70`:

- **HALVE** — the constant is 1280-scale: it is a POSITION, is derived from
  or compared to `view_w`/`view_h`, or is a CONTAINER dimension (panel/button/
  popup/modal width or height, and the padding/gap/offset internal to a
  container that itself halves), or is a `[0, 0, 1280, 720]` backdrop rect.
- **LEAVE** — the constant is already 640-scale or is scale-free: font
  presets (`data/ui/fonts.json`), RGB/RGBA colour components, alpha values,
  `border_radius`, line `width=`, text-truncation `max_lines`, timings, and
  element sizes that were authored at prototype scale.

**Arithmetic**: halve with Python integer floor division (`// 2`). Odd values
are listed explicitly below with their floored target so nobody has to guess.
Odd-pixel rounding drift is an expected UR-5 item
(`planning/UiResolutionPLAN.md:214-217`).

**Do not blind-`sed`.** Every number below is bucketed individually.

### 1.1 DECISION NEEDED — D1: the 18×18 HUD icons

`planning/UiResolutionPLAN.md:64-67` names "the 18×18 HUD icons" as the
canonical **LEAVE** example. Measured against the code, that classification
looks wrong and cannot be implemented without visible clipping:

- `game/ui/hud.py:80` — `_ICON_SIZE = 18`, commented "fits the ~16-20px HUD
  rows without crowding the text".
- `game/ui/hud.py:176` — `self._love_panel = SimpleNamespace(rect=(12, 12, 190, 34), ...)`.
  The love pill is **34 px tall today**; the icon was sized to sit inside it
  (`game/ui/hud.py:276-277`, `icon_love_y = pill[1] + (pill[3] - _ICON_SIZE) // 2`).
- Halving the pill (34 → 17; the committed `hud.json` override 39 → 19) while
  leaving the icon at 18 puts an 18 px icon inside a 17 px pill — it
  overflows, and `_ICON_GAP` (4) pushes the love text off the pill's right
  edge.

**Recommendation (implement this unless the orchestrator rules otherwise):
HALVE `_ICON_SIZE` 18 → 9 and `_ICON_GAP` 4 → 2.** This is the one place the
brief knowingly diverges from §2's worked example; it is flagged, not
silently decided. **Mark it "UR-5 review" in the phase report either way** —
9 px icons over a baked 64×64 sheet may read poorly and is exactly what UR-5
exists to judge.

### 1.2 GAP IN THE PHASE'S FILE LIST — six more `game/ui` screens

`planning/UiResolutionPLAN.md:136-140` enumerates `building_ui.py`,
`levelup.py`, `main_menu.py`, `boss_cutscene.py`, `hud.py`, `pause.py`,
`highscores.py`, `game_over.py`, `cheat_menu.py`, `credits.py`, `shell.py`,
`tutorial_message.py`, `widgets.py`. The goal line above it says
`game/ui/*.py`. **Six live screens carrying 1280-scale constants are missing
from the enumeration and MUST be converted** — leaving them out ships
screens that draw off the bottom of the frame:

- `game/ui/settings.py` — `self._top = view_h // 2 - 180` (line 97). At
  `view_h=360` that is `0`, and the stack below it runs past 360. It is also
  one of the three screens whose committed JSON rects are being halved (§1.13),
  so its code defaults and its overrides would disagree.
- `game/ui/player_intro.py:47` — `_PW, _PH = 520, 476`. **476 > 360**: the
  panel is taller than the entire new surface.
- `game/ui/debug_settings.py:105` — `self._top = view_h // 2 - 200` → `-20`
  at 360, i.e. off the top of the screen.
- `game/ui/add_name.py:28` — `_PW, _PH = 460, 260`.
- `game/ui/game_log.py:29-31` — `_LINE_STEP`/`_X`/`_LIFT`.
- `game/ui/overlays.py:86-87` — the two toggle pills.

`game/ui/effects.py` is **out of scope**: its remaining pixel constants are
world-space HP/charge bars sized off enemy class attrs and `data/balancing/
vfx.json`, not screen layout. Do not touch it.

`game/ui/shell.py` is in the enumeration but is a **no-op**: it contains no
pixel constants — it only forwards `view_w`/`view_h` into the screens it owns
(`game/ui/shell.py:46,60-84,333-336`). Verify and report; change nothing.

`game/ui/skinning.py`, `game/ui/strings.py`, `game/ui/cutscene_player.py` are
untouched.

### 1.3 `game/ui/widgets.py` (shared chrome)

| `file:line` | constant | now | bucket | target |
|---|---|---|---|---|
| `widgets.py:243` | `submit_tutorial_banner(..., pad=24)` | 24 | HALVE (container padding around a full-screen banner) | 12 |
| `widgets.py:254-255` | banner `HudRect` fills / `width=3` border | 3 | LEAVE (line width) | 3 |
| `widgets.py:232` | `submit_ui_box_highlight(..., width=3)` | 3 | LEAVE (line width) | 3 |
| `widgets.py:373-375` | `Button.submit` `border_radius=3`, `width=1` | 3 / 1 | LEAVE | unchanged |
| `widgets.py:47-71` | the `C_*` palette | — | LEAVE (colours) | unchanged |
| `widgets.py:378` | `ty = y + (h - layout_h(...)) // 2` | — | derived, no constant | unchanged |

`widgets.py:265` (`submit_bar` fill math) and `widgets.py:216,225` (tile
diamonds, world-space tile coords) carry no screen-pixel constants.

### 1.4 `game/ui/hud.py`

| `file:line` | constant | now | bucket | target |
|---|---|---|---|---|
| `hud.py:80` | `_ICON_SIZE` | 18 | **D1 — see §1.1**; recommended HALVE | 9 |
| `hud.py:81` | `_ICON_GAP` | 4 | **D1**; recommended HALVE | 2 |
| `hud.py:151` | `end_turn` Button `(0,0,160,60)` | 160×60 | HALVE | 80×30 |
| `hud.py:152` | `pause` Button `(0,0,90,30)` | 90×30 | HALVE | 45×15 |
| `hud.py:155-157` | three speed Buttons `(0,0,56,28)` | 56×28 | HALVE | 28×14 |
| `hud.py:165` | `drag_select_btn` `(0,0,90,28)` | 90×28 | HALVE | 45×14 |
| `hud.py:176` | `_love_panel.rect = (12,12,190,34)` | — | HALVE | `(6,6,95,17)` |
| `hud.py:181` | `_readout_panel.rect = (12,44,190,60)` | — | HALVE | `(6,22,95,30)` |
| `hud.py:197` | `_xp_bar.rect = (0,0,110,9)` | 110×9 | HALVE (odd h) | 55×4 — **UR-5 review**: a 4 px bar is at the legibility floor |
| `hud.py:229` | `end_turn` inset `16` (×2) | 16 | HALVE | 8 |
| `hud.py:231` | `pause` inset `16`, `12` | — | HALVE | 8, 6 |
| `hud.py:237` | `_phase_label.rect = (12, view_h - 26, 0, 0)` | 12, 26 | HALVE | 6, 13 |
| `hud.py:239` | `sy = 110` (speed row top) | 110 | HALVE | 55 |
| `hud.py:240` | `sw, sh, gap = 56, 28, 6` | — | HALVE | 28, 14, 3 |
| `hud.py:241-243,248` | `12` left margin, `12 + sw + gap`, `12 + 2*(sw+gap)` | 12 | HALVE | 6 |
| `hud.py:268` | `lvl_x = pill[0] + pill[2] + 12` | 12 | HALVE | 6 |
| `hud.py:270` | `bar_y = lvl_y + layout_h("hud_lvl") + 3` | 3 | LEAVE (sub-4 nudge; **UR-5 review**) | 3 |
| `hud.py:277` | `pill[0] + 6` | 6 | HALVE | 3 |
| `hud.py:279` | `pill[1] + 7` | 7 | HALVE (odd) | 3 |
| `hud.py:281` | `(_ICON_SIZE - 9) // 2` — the literal `9` mirrors the xp bar height | 9 | follow the xp-bar row above | 4 |
| `hud.py:284-285` | `xp_bar` `(bar_x, bar_y, 110, 9)`, `bar_y + 9 + 2` | — | HALVE, keep consistent with `hud.py:197` | `55, 4`, `+4+1` |
| `hud.py:286` | `_income_text.rect = (pill[0]+4, 50, ...)` | 4, 50 | HALVE | 2, 25 |
| `hud.py:287,289` | `pill[0]+4`, `66` | 4, 66 | HALVE | 2, 33 |
| `hud.py:290` | `_tiles_text.rect = (pill[0]+4, 84, ...)` | 4, 84 | HALVE | 2, 42 |
| `hud.py:296` | `pad = 4` (readout panel) | 4 | HALVE | 2 |
| `hud.py:302` | `round_label` `by - layout_h("md") - 4` | 4 | HALVE | 2 |
| `hud.py:442` | `income_pill = (pill[0]-10, 48, 118, 18)` (hover zone) | — | HALVE | `(pill[0]-5, 24, 59, 9)` |
| `hud.py:497` | separator `(bx, by-2, bw, 1)` | 2, 1 | LEAVE (1 px hairline; the `-2` is its offset — **UR-5 review**) | unchanged |
| `hud.py:513-514,527-529` | active-rim `width=2, border_radius=3` | — | LEAVE | unchanged |
| `hud.py:564-573` | tooltip `lh = text_h("sm")+3`, `+8`, `+8`, `x=max(2,…)`, `y+2`, `x+4`, `ty=y+4` | — | HALVE the ≥4 paddings (`8`→`4`, `4`→`2`), LEAVE the `+3`/`+2` sub-4 nudges | see left; **UR-5 review** |
| `hud.py:650` | `x, y = 12, view_h - 26 - h - 12` | 12, 26, 12 | HALVE | 6, 13, 6 |
| `hud.py:651` | lightning backing `(x-4, y-3, w+8, h+6)` | — | HALVE | `(x-2, y-2, w+4, h+3)` |
| `hud.py:655` | cursor bar `self._mx - 11, self._my + 16, 22, 3` | — | HALVE (keep `3` — 1 px is invisible) | `-5, +8, 11, 2` — **UR-5 review** |
| `hud.py:34-35,76-86` | `_LIGHTNING_*`, `_INCOME_PINK`, `_XP_*`, `_TOOLTIP_*` | — | LEAVE (colours) | unchanged |

### 1.5 `game/ui/building_ui.py`

The panel is a full-height right sidebar; its width and every inset derived
from it are 1280-scale.

| `file:line` | constant | now | bucket | target |
|---|---|---|---|---|
| `building_ui.py:164` | `ConstructPreview` `pw, ph = 340, 300` | — | HALVE | 170, 150 |
| `building_ui.py:169` | `name_rect = (x+16, y+96, pw-32-36, 30)` | — | HALVE | `(x+8, y+48, pw-16-18, 15)` |
| `building_ui.py:170-171` | `dice_btn (x+pw-16-30, y+96, 30, 30)` | — | HALVE | `(x+pw-8-15, y+48, 15, 15)` |
| `building_ui.py:172` | `close_btn (x+pw-26, y+6, 20, 18)` | — | HALVE | `(x+pw-13, y+3, 10, 9)` |
| `building_ui.py:173-175,184` | `btn_y = y+ph-48`, `bw, bh = 140, 34`, insets `16`, full-width `pw-32` | — | HALVE | `ph-24`, `70, 17`, `8`, `pw-16` |
| `building_ui.py:347` | `MovePreview` `pw, ph = 340, 190` | — | HALVE | 170, 95 |
| `building_ui.py:350-353,364` | `MovePreview` close/confirm/cancel geometry — **the exact mirror of lines 172-175/184** | — | HALVE identically | as above |
| `building_ui.py:462` | `(cx, y + 120)` info line | 120 | HALVE | 60 |
| `building_ui.py:473` | `self.panel_w = 260` | 260 | HALVE | 130 |
| `building_ui.py:476` | `_right = panel_x + panel_w - 14` | 14 | HALVE (odd) | 7 |
| `building_ui.py:499` | `_name_box_rect = (panel_x+14, 40, panel_w-64, 22)` | — | HALVE | `(+7, 20, -32, 11)` |
| `building_ui.py:501` | `_dice_up (panel_x+14+panel_w-64+6, 40, 24, 22)` | — | HALVE | `(+7+…-32+3, 20, 12, 11)` |
| `building_ui.py:507` | `close_btn (panel_x+panel_w-28, 8, 20, 18)` | — | HALVE | `(-14, 4, 10, 9)` |
| `building_ui.py:509` | `action_btn (panel_x+12, 0, panel_w-24, 36)` | — | HALVE | `(+6, 0, -12, 18)` |
| `building_ui.py:515` | `move_btn (panel_x+12, 0, panel_w-24, 30)` | — | HALVE | `(+6, 0, -12, 15)` |
| `building_ui.py:521` | `boss_btn (panel_x+12, 420, panel_w-24, 32)` | 420 | HALVE | `(+6, 210, -12, 16)` |
| `building_ui.py:523-525` | boss popup `pw, ph = 340, 260` centred on view | — | HALVE | 170, 130 |
| `building_ui.py:528` | `_boss_close_btn (px+pw//2-60, py+ph-44, 120, 32)` | — | HALVE | `(-30, ph-22, 60, 16)` |
| `building_ui.py:706` | `action_btn.rect = (panel_x+12, 150, panel_w-24, 36)` | 150 | HALVE | 75 |
| `building_ui.py:747` | card `Button((panel_x+12, y, panel_w-24, 42))` | 42 | HALVE | 21 |
| `building_ui.py:775` | `(panel_x+12, view_h-120, panel_w-24, 36)` | 120, 36 | HALVE | 60, 18 |
| `building_ui.py:1295,1311,1362,1463,1549` | body cursor `x = panel_x + 14` | 14 | HALVE | 7 |
| `building_ui.py:1307,1316` | tooltip anchor `view_h - 40` | 40 | HALVE | 20 |
| `building_ui.py:1422` | `panel_x + panel_w // 2` | — | derived, no change | — |
| `building_ui.py:1433` | divider `(x, y, panel_w-28, 1)` | 28 / 1 | HALVE the 28, LEAVE the 1 | 14 / 1 |
| `building_ui.py:1518,1537` | `panel_x + (panel_w - w) // 2` | — | derived, no change | — |
| `building_ui.py:61` | `_COND_TOOLTIP_BG` | — | LEAVE (colour) | unchanged |

**Body-layout numbers not individually tabled above.** `building_ui.py` is
1610 lines and its `_build_*`/`_submit_*` bodies advance a `cursor`/`y` with
inline row pitches, badge sizes and text pads. Apply the §1.0 rule uniformly
to them: **every vertical cursor advance, row height, badge/box dimension and
padding ≥ 4 px HALVES; every `width=`/`border_radius`/colour/alpha and every
sub-4 nudge LEAVES.** Report the count you converted. Any row that ends up
under ~8 px tall after halving is a **UR-5 review** item — list them, do not
hand-tune them here.

### 1.6 `game/ui/main_menu.py`

| `file:line` | constant | now | bucket | target |
|---|---|---|---|---|
| `main_menu.py:76` | `_BTN_W, _BTN_H, _GAP = 320, 52, 8` | — | HALVE | 160, 26, 4 |
| `main_menu.py:82` | `_GEAR_W, _GEAR_GAP = 52, 10` | — | HALVE | 26, 5 |
| `main_menu.py:153` | `y = view_h // 2 - 60` | 60 | HALVE | 30 |
| `main_menu.py:168` | `title` `view_h // 2 - 150` | 150 | HALVE | 75 |
| `main_menu.py:169` | `subtitle` `view_h // 2 - 110` | 110 | HALVE | 55 |
| `main_menu.py:44` | `_BG` | — | LEAVE (colour) | unchanged |
| `main_menu.py:210` | `HudSprite(_BG_SLOT, (0,0), (view_w, view_h))` | — | derived; UR-4 recuts the art | unchanged |

`main_menu.py:70-75` carries a comment justifying `_GAP = 8` in terms of the
"shipped 1280x720 logical surface". **Update that comment** — it will be a lie
the moment this phase lands.

### 1.7 `game/ui/pause.py`

| `file:line` | constant | now | bucket | target |
|---|---|---|---|---|
| `pause.py:32` | `_PW, _PH = 300, 320` | — | HALVE | 150, 160 |
| `pause.py:33` | `_BTN_W, _BTN_H, _GAP = 240, 46, 12` | — | HALVE (odd 46) | 120, 23, 6 |
| `pause.py:59` | `y = py + 84` | 84 | HALVE | 42 |
| `pause.py:64` | `title` `py + 32` | 32 | HALVE | 16 |
| `pause.py:46` | backdrop colour `(0,0,0,150)` | — | LEAVE (alpha) | unchanged |
| `pause.py:94-96` | `border_radius=6`, `width=2` | — | LEAVE | unchanged |

### 1.8 `game/ui/levelup.py`

| `file:line` | constant | now | bucket | target |
|---|---|---|---|---|
| `levelup.py:35` | `_BOX_W, _BOX_H, _GAP = 200, 220, 8` | — | HALVE | 100, 110, 4 |
| `levelup.py:43` | `_SPRITE_PX = 72` | 72 | HALVE | 36 |
| `levelup.py:116` | heading `top - layout_h("xxl") - 16` | 16 | HALVE | 8 |
| `levelup.py:138` | `cursor = y + 10` | 10 | HALVE | 5 |
| `levelup.py:145,147` | `+ layout_h("sm") + 2`, `cursor += 10` | 2 / 10 | LEAVE / HALVE | 2 / 5 |
| `levelup.py:149` | `+ layout_h("md") + 6` | 6 | HALVE | 3 |
| `levelup.py:155` | `cursor += _SPRITE_PX + 4` | 4 | HALVE | 2 |
| `levelup.py:163` | `+ layout_h("sm") + 4` | 4 | HALVE | 2 |
| `levelup.py:165` | `wrap_text(..., w - 16, max_lines=4)` | 16 / 4 | HALVE the 16; **LEAVE `max_lines=4`** (a count, not pixels) | 8 / 4 |
| `levelup.py:167` | `+ layout_h("sm") + 1` | 1 | LEAVE | 1 |
| `levelup.py:173` | `y + h - layout_h("sm") - 6` | 6 | HALVE | 3 |
| `levelup.py:179` | chevron `(cx-5, y+6), (cx,y), (cx+5, y+6)`, `width=2` | — | HALVE the 5/6; LEAVE `width=2` | `-2/+3`, `+2/+3` |
| `levelup.py:34` | `_BG = (0,0,0,185)` | — | LEAVE (alpha) | unchanged |

### 1.9 `game/ui/boss_cutscene.py`

| `file:line` | constant | now | bucket | target |
|---|---|---|---|---|
| `boss_cutscene.py:44` | `_BOX_W, _BOX_H, _GAP = 180, 130, 20` | — | HALVE | 90, 65, 10 |
| `boss_cutscene.py:45` | `_DOWN_SHIFT = 20` | 20 | HALVE | 10 |
| `boss_cutscene.py:116` | headline `- 28` | 28 | HALVE | 14 |
| `boss_cutscene.py:117` | subtitle `- 12` | 12 | HALVE | 6 |
| `boss_cutscene.py:191` | `cursor = y + 12` | 12 | HALVE | 6 |
| `boss_cutscene.py:197` | `+ layout_h(...) + 10` | 10 | HALVE | 5 |
| `boss_cutscene.py:200` | `+ layout_h("sm") + 2` | 2 | LEAVE | 2 |
| `boss_cutscene.py:41-43` | `_BG`, `_WIN_GREEN`, `_LOSS_RED` | — | LEAVE (colours) | unchanged |

### 1.10 `game/ui/game_over.py`, `credits.py`, `tutorial_message.py`, `highscores.py`, `cheat_menu.py`

| `file:line` | constant | now | bucket | target |
|---|---|---|---|---|
| `game_over.py:31` | `Button((0,0,240,46))` | 240×46 | HALVE (odd) | 120×23 |
| `game_over.py:42` | `view_h // 2 + 110` | 110 | HALVE | 55 |
| `game_over.py:44` | `view_h // 2 - 120` | 120 | HALVE | 60 |
| `game_over.py:78` | `y = view_h // 2 - 30` | 30 | HALVE | 15 |
| `game_over.py:81` | `y += 28` (line pitch) | 28 | HALVE | 14 |
| `credits.py:41-42` | `_LINE_H, _SPACER_H = 30, 14` | — | HALVE (odd 7) | 15, 7 |
| `credits.py:51,61` | BACK `200×46`, `view_w//2 - 100`, `view_h - 90` | — | HALVE (odd 23) | `100×23`, `-50`, `-45` |
| `credits.py:63` | `title` `y = 70` | 70 | HALVE | 35 |
| `credits.py:92` | `y = 150` (body top) | 150 | HALVE | 75 |
| `credits.py:97,99` | `cx - 40` / `cx + 40` columns | 40 | HALVE | 20 |
| `tutorial_message.py:19` | `_PANEL_W, _PANEL_H = 520, 260` | — | HALVE | 260, 130 |
| `tutorial_message.py:27` | `continue_btn (0,0,200,46)` | — | HALVE (odd) | 100, 23 |
| `tutorial_message.py:28` | `skip_btn (0,0,180,40)` | — | HALVE | 90, 20 |
| `tutorial_message.py:49` | `(x+20, y+24)` | — | HALVE | `(x+10, y+12)` |
| `tutorial_message.py:52,54` | inset `16` (×3) | 16 | HALVE | 8 |
| `tutorial_message.py:94` | `wrap_text(..., _PANEL_W - 40, max_lines=6)` | 40 / 6 | HALVE the 40; LEAVE `max_lines` | 20 / 6 |
| `tutorial_message.py:97` | `ty += 22` line pitch | 22 | HALVE | 11 |
| `tutorial_message.py:18` | `_BG = (10,5,20,200)` | — | LEAVE | unchanged |
| `highscores.py:62-71` | `_TABLE_W 760`, `_COL_SKILL 300`, `_COL_ROUND_R 520`, `_COL_BUILT_R 640`, `_COL_KILLS_R 760`, `_ROW_H 28`, `_HEADER_GAP 30`, `_TABLE_TOP 140`, `_BOTTOM_PAD 24` | — | HALVE all (`_COL_NAME = 0` unchanged) | 380, 150, 260, 320, 380, 14, 15, 70, 12 |
| `highscores.py:91,131` | BACK `200×46`, `view_w//2-100`, `view_h-90` | — | HALVE | `100×23`, `-50`, `-45` |
| `highscores.py:133` | `title` `y = 70` | 70 | HALVE | 35 |
| `highscores.py:210` | `_viewport_top + 20` | 20 | HALVE | 10 |
| `highscores.py:229` | `back_btn.rect[1] - 22` | 22 | HALVE | 11 |
| `cheat_menu.py:48` | `_PANEL_W, _PANEL_H = 220, 288` | — | HALVE | 110, 144 |
| `cheat_menu.py:83` | `close_btn (0,0,20,18)` | — | HALVE | 10, 9 |
| `cheat_menu.py:137` | `(px+_PANEL_W-26, py+6, 20, 18)` | — | HALVE | `-13, +3, 10, 9` |
| `cheat_menu.py:138` | `y = py + 32` | 32 | HALVE | 16 |
| `cheat_menu.py:140-141` | row `(px+10, y, _PANEL_W-20, 26)`, `y += 30` | — | HALVE | `+5, -10, 13`, `+15` |
| `cheat_menu.py:142` | `_divider_y = y + 2` | 2 | LEAVE | 2 |
| `cheat_menu.py:143-144` | `field_rect (px+10, y+26, 96, 22)`, `go_btn (px+112, y+26, _PANEL_W-122, 22)` | — | HALVE (odd 61) | `(+5, +13, 48, 11)`, `(+56, +13, -61, 11)` |
| `cheat_menu.py:148-149` | `title (px+_PANEL_W//2, py+8)`, `jump (px+10, y+8)` | 8, 10 | HALVE | 4, 5 |
| `cheat_menu.py:240` | divider `(px+10, …, pw-20, 1)` | — | HALVE the 10/20, LEAVE the 1 | 5 / 10 / 1 |
| `cheat_menu.py:254` | `(fx+6, fy+4)` | — | HALVE | `(+3, +2)` |
| `cheat_menu.py:47` | `_BG = (0,0,0,150)` | — | LEAVE | unchanged |
| `cheat_menu.py:50` | `_MAX_DIGITS = 4` | — | LEAVE (a count) | 4 |

### 1.11 The six screens from §1.2 (not in the plan's enumeration — convert them)

| `file:line` | constant | now | bucket | target |
|---|---|---|---|---|
| `settings.py:78-79` | `dm_left`/`dm_right` `(0,0,40,40)` | — | HALVE | 20×20 |
| `settings.py:80` | `default_btn (0,0,170,40)` | — | HALVE | 85×20 |
| `settings.py:83` | toggle `(0,0,90,40)` | — | HALVE | 45×20 |
| `settings.py:85` | `back_btn (0,0,200,46)` | — | HALVE (odd) | 100×23 |
| `settings.py:97` | `_top = view_h//2 - 180` | 180 | HALVE | 90 |
| `settings.py:98` | `_dm_y = _top + 70` | 70 | HALVE | 35 |
| `settings.py:99-102` | `cx-150`, `cx+110`, `cx+170`, `-6` | — | HALVE | `-75`, `+55`, `+85`, `-3` |
| `settings.py:103,108` | `y = _dm_y + 70`, `y += 56` | — | HALVE | 35, 28 |
| `settings.py:107` | toggle `(cx+60, y-8, 90, 40)` | — | HALVE | `(+30, -4, 45, 20)` |
| `settings.py:109-111` | `_slider_y = y+10`, `(cx-90, …, 180, 12)`, `back (cx-100, y+70, …)` | — | HALVE | `+5`, `(-45, …, 90, 6)`, `(-50, y+35)` |
| `settings.py:174,185,191,195` | `_dm_y-34`, `cx-150`, `sy-24`, `sy+20` | — | HALVE | `-17`, `-75`, `-12`, `+10` |
| `add_name.py:28` | `_PW, _PH = 460, 260` | — | HALVE | 230, 130 |
| `add_name.py:42-43` | `add_btn 160×40`, `back_btn 130×40` | — | HALVE | 80×20, 65×20 |
| `add_name.py:57-59,62` | `(x+24, y+108, _PW-48, 36)`, `y+_PH-56`, `x+_PW-24-130`, `y+20` | — | HALVE | `(+12, +54, -24, 18)`, `-28`, `-12-65`, `+10` |
| `add_name.py:143,155,158,160` | `y+62`, `(nx+8, ny+9)`, `y+156`, `y+_PH-78` | — | HALVE | `+31`, `(+4, +4)`, `+78`, `-39` |
| `player_intro.py:47` | `_PW, _PH = 520, 476` | — | HALVE | 260, 238 |
| `player_intro.py:52` | `_OPT_W, _OPT_H, _OPT_GAP = 280, 40, 10` | — | HALVE | 140, 20, 5 |
| `player_intro.py:69-70` | `start_btn 160×40`, `back_btn 130×40` | — | HALVE | 80×20, 65×20 |
| `player_intro.py:85-95` | `(x+24, y+96, _PW-48, 36)`, `_prompt_y y+150`, `oy y+180`, `y+_PH-56`, `x+_PW-24-130`, `y+20` | — | HALVE | `(+12, +48, -24, 18)`, `+75`, `+90`, `-28`, `-12-65`, `+10` |
| `debug_settings.py:105-116` | `_top view_h//2-200`, `_level_y +70`, `cx-210`, `cx+170`, `-6`, `y = _level_y+70`, `(cx+100, y-8, 90, 40)`, `y += 56`, `back (cx-100, y+30, 200, 46)` | — | HALVE | `-100`, `+35`, `-105`, `+85`, `-3`, `+35`, `(+50, -4, 45, 20)`, `+28`, `(-50, +15, 100, 23)` |
| `game_log.py:29-31` | `_LINE_STEP 12`, `_X 8`, `_LIFT 32` | — | HALVE | 6, 4, 16 |
| `game_log.py:25-28` | `LIFETIME`, `FADE_START`, `MAX_MESSAGES`, `_COLOR` | — | LEAVE (timings/count/colour) | unchanged |
| `overlays.py:86` | `range_btn (12, view_h-72, 74, 26)` | — | HALVE | `(6, -36, 37, 13)` |
| `overlays.py:87` | `heatmap_btn (90, view_h-72, 74, 26)` | — | HALVE | `(45, -36, 37, 13)` |
| `overlays.py:50-68,202,208` | tints, `heat_color` alphas, `border_width=2/1` | — | LEAVE | unchanged |

`overlays.py:84-85` carries a comment citing "the banner sits at view_h-26" —
update it to match the halved `hud.py:237` anchor.

### 1.12 `data/ui/fonts.json` — LEAVE, all seven

`data/ui/fonts.json:1-30` — `sm 9`, `md 11`, `lg 13`, `hud_lvl 12`,
`hud_phase 14`, `xl 18`, `xxl 26`. Per `planning/UiResolutionPLAN.md:64-67`
these are the prototype's 640-scale presets and **become correct the moment
the surface halves** — halving them again is precisely the bug this plan
exists to remove. Zero edits to this file, its schema, or
`engine/render/fonts.py`. (`planning/UiResolutionPLAN.md:244-247` parks
"fonts may need re-tuning after all" as a UR-5 question; it is not this
phase's call.)

### 1.13 The 12 committed JSON rects — current → target

All twelve are 1280-scale (`planning/UiResolutionPLAN.md:44-49`) and halve.

**`data/ui/screens/hud.json`** (4)

| widget | `file:line` | current | target |
|---|---|---|---|
| `btn_end_turn.rect` | `hud.json:4-9` | `[1104, 644, 160, 60]` | `[552, 322, 80, 30]` |
| `btn_pause.rect` | `hud.json:18-23` | `[1174, 12, 90, 30]` | `[587, 6, 45, 15]` |
| `love_panel.rect` | `hud.json:36-41` | `[12, 12, 107, 39]` | `[6, 6, 53, 19]` |
| `readout_panel.rect` | `hud.json:45-50` | `[12, 46, 107, 57]` | `[6, 23, 53, 28]` |

(`skin` / `text_color` keys are untouched.)

**`data/ui/screens/settings.json`** (5)

| widget | `file:line` | current | target |
|---|---|---|---|
| `backdrop.rect` | `settings.json:4-9` | `[0, 0, 1280, 720]` | `[0, 0, 640, 360]` |
| `btn_back.rect` | `settings.json:12-17` | `[540, 558, 200, 46]` | `[270, 279, 100, 23]` |
| `btn_toggle_bg_art.rect` | `settings.json:27-32` | `[700, 368, 90, 40]` | `[350, 184, 45, 20]` |
| `btn_toggle_gore.rect` | `settings.json:36-41` | `[700, 424, 90, 40]` | `[350, 212, 45, 20]` |
| `btn_toggle_income_floaters.rect` | `settings.json:45-50` | `[700, 312, 90, 40]` | `[350, 156, 45, 20]` |

**`data/ui/screens/main_menu.json`** (3)

| widget | `file:line` | current | target |
|---|---|---|---|
| `backdrop.rect` | `main_menu.json:4-9` | `[0, 0, 1280, 720]` | `[0, 0, 640, 360]` |
| `btn_new_game.rect` | `main_menu.json:21-26` | `[480, 300, 320, 52]` | `[240, 150, 160, 26]` |
| `subtitle.rect` | `main_menu.json:36-41` | `[640, 250, 0, 0]` | `[320, 125, 0, 0]` |

**Consistency check that must hold after conversion**: `btn_end_turn`'s
halved override `[552, 322, 80, 30]` must equal the halved code default
(`hud.py:151` 80×30 at `hud.py:229`'s `view_w - w - 8, view_h - h - 8` =
`552, 322`). Same for `btn_pause` (`587, 6`) and `love_panel` (`6, 6`). If
they disagree, the code conversion is wrong, not the JSON.

Every other `data/ui/screens/*.json` file carries **zero** rects
(`planning/UiResolutionPLAN.md:44-47`) — `credits.json`, `pause.json`,
`add_name.json`, `game_over.json`, `levelup.json`, `building_panel.json`,
`cheat_menu.json`, `game_log.json`, `boss_cutscene.json`, `overlays.json`
keep only `skin`/`defaults` content and are **not edited**.

---

## 2. Architecture plan — order of operations

Nothing new is built (`planning/UiResolutionPLAN.md:32-36`). The phase is
coupled by nature: the surface and the constants cannot flip separately
without an intermediate tree that is genuinely broken. Do all of steps 1-4 in
one working pass and one commit; the ordering below exists so that when a
test goes red you can say which step owns it.

**Step 0 — confirm UR-1 landed.** `editor/panels/viewport.py` must already
read `SCREEN_W`/`SCREEN_H` from `data/display.json` rather than the literals
(`planning/UiResolutionPLAN.md:110-114`). If it still hardcodes 1280/720,
**stop and report** — UR-2 on an un-de-hardcoded tree silently desyncs the
editor preview from the game and turns UR-3 into a bug hunt.

**Step 1 — flip the surface.** `data/display.json` → `"window_w": 640`,
`"window_h": 360`. Keep sorted keys / 2-space indent (D-3); the file is tiny,
but write it through the same canonical form it already has. `caption`,
`display_mode`, `fps` unchanged. Nothing else in `game/` or `tools/` states
the resolution — `game/main.py:219` reads it into `view_w, view_h` and passes
it to every screen constructor.

After this step alone the tree renders the OLD constants into the NEW
surface: everything clips. That is expected and is why step 2 is not a
separate commit.

**Step 2 — convert the code constants**, file by file, per §1.3-§1.11. Work
in the listed order (`widgets.py` first — the shared chrome — then `hud.py`,
then `building_ui.py`, then the screens) so the shared helper's padding is
settled before the callers are reviewed.

**Step 3 — halve the 12 JSON rects** (§1.13). Write through the validating
writer / keep D-3 canonical form. Do NOT hand-add rects to the ten screen
JSONs that have none.

**Step 4 — regenerate `data/ui/screen_defaults.json`:**

```
py tools/export_ui_layouts.py
```

**Never hand-edit that file.** It is generated-but-committed and a test
re-runs the exporter (`planning/UiResolutionPLAN.md:143-145`;
`tools/export_ui_layouts.py:1-27,200-206`). The exporter already reads
`display.json` for its `(view_w, view_h)` (`tools/export_ui_layouts.py:
200-206,547`) and hardcodes nothing, so it regenerates for free — **it needs
no edit in this phase**. Its one stale docstring is
`tools/export_ui_layouts.py:487` ("R3 contract: open(1, 'win') + layout(1280,
720)") — a comment, not code; update the number. Expect the regenerated file
to change in essentially every screen entry; that is the correct signal.

**Step 5 — re-pin the tests** (§4). Only after steps 1-4 are complete, so a
red test is attributable to a converted constant and not to a half-flipped
tree.

### Explicitly UNCHANGED, and why

- **`data/ui/fonts.json`** — §1.12 above. `planning/UiResolutionPLAN.md:64-67,146`:
  the 7 presets are already the prototype's 640-scale values; halving them is
  the double-scale bug the plan exists to delete. Do not touch the file, its
  schema, `engine/render/fonts.py`, or `engine.render.fonts.configure_fonts`.
- **`data/geometry.json`** — `planning/UiResolutionPLAN.md:72-86,146,228-231`
  (§3). The zoom retune is DEFERRED by the user's own scope decision. Halving
  `zoom_levels` to `[0.5, 1.0, 2.0]` would restore today's framing at the cost
  of downscaled world art; keeping them is prototype-faithful. **Neither is
  chosen here.** The world looking too close after this phase is the
  documented, accepted consequence — not a bug, not a regression, and not
  something to patch from `game/ui`.
- **`data/ui/palette.json`, `data/ui/strings.json`** — colours and copy, no
  pixel content.
- **`engine/**`** — the engine draws what it is handed; SDL `SCALED`
  (`game/main.py:133`) already upscales the logical surface to the monitor
  and remaps mouse coordinates back down, so hit-testing, `handle_click(mx,
  my)` and every widget rect keep working untouched
  (`planning/UiResolutionPLAN.md:20-26`). No engine change is in scope. If you
  believe one is needed, **stop and report** — that is a cross-package task.

---

## 3. File scope + shared-file contract

### May create/modify

**Data (4 files):**
- `data/display.json` — 2 values.
- `data/ui/screens/hud.json` — 4 rects.
- `data/ui/screens/settings.json` — 5 rects.
- `data/ui/screens/main_menu.json` — 3 rects.

**Generated (1 file, by tool only):**
- `data/ui/screen_defaults.json` — via `py tools/export_ui_layouts.py`. Never
  by hand, never by editor, never by a merge resolution
  (`planning/UiResolutionPLAN.md:248-249`: conflicts resolve by re-running the
  deterministic exporter).

**Code — `game/ui/` (19 files):**
`widgets.py`, `hud.py`, `building_ui.py`, `main_menu.py`, `pause.py`,
`levelup.py`, `boss_cutscene.py`, `game_over.py`, `credits.py`,
`tutorial_message.py`, `highscores.py`, `cheat_menu.py`, `settings.py`,
`add_name.py`, `player_intro.py`, `debug_settings.py`, `game_log.py`,
`overlays.py`, plus `shell.py` (**verify-no-op only**, §1.2).

**Comments/docstrings that name a literal size and must be corrected in the
same pass:** `main_menu.py:70-75`, `overlays.py:84-85`,
`tools/export_ui_layouts.py:487`.

**Tests (9 files):** §4.

**Docs:** `game/ui/CLAUDE.md` — add ONE short section recording that
`game/ui` now lays out in a 640×360 logical surface, that `fonts.json`'s
presets are the matching scale and were deliberately not touched, and that
the world framing is a known deferred item (§3). Per the root router: update
the PACKAGE doc, not the root router and not another package's doc.

### Explicitly OUT of scope for UR-2

- **`editor/panels/viewport.py` — NOT UR-2's.** UR-1 owns the de-hardcoding
  (`SCREEN_W`/`SCREEN_H` reading `display.json`, plus the four prose
  references at lines 11/25/414/515 and `NUDGE_STEP` at line 102) and **UR-3
  owns the preview behaviour at the new canvas** (scale-to-fit and letterbox
  math at ~414/~515, and revisiting `NUDGE_STEP`) —
  `planning/UiResolutionPLAN.md:110-118,171-175`. Do not edit it here even if
  the preview looks wrong after the flip; **that is UR-3's exit gate, and
  seeing it wrong is expected.** Likewise `editor/panels/CLAUDE.md` and
  `tools/tests/test_editor_viewport.py` belong to UR-1/UR-3, not here.
- **`data/slots.json` — NOT UR-2's.** UR-4 owns the `backgrounds` category
  `frame_w`/`frame_h` 480×270 → 640×360, the `ui_bg_main_menu` per-slot
  override, the manifest/PNG recut and `data/CLAUDE.md`'s two 480×270
  mentions (`planning/UiResolutionPLAN.md:184-199`). The main-menu background
  will look wrong (a 480×270 sheet stretched into 640×360) after this phase —
  **that is UR-4, do not pre-empt it.** `data/sprites/asset_manifest.json` and
  `data/sprites/imported/*.png` are untouched.
- `data/geometry.json`, `data/ui/fonts.json`, `game/map/**`, `engine/**`,
  `game/ui/effects.py`.

### Shared-file contract (where phases collide)

| File | UR-2 touches | Who else | Contract |
|---|---|---|---|
| `data/display.json` | `window_w`, `window_h` only | UR-1 reads it from the editor; UR-3 depends on the new value | UR-2 is the ONLY phase that writes it. `caption`/`fps`/`display_mode` untouched. |
| `data/ui/screen_defaults.json` | fully regenerated | UR-3's editor preview reads it | Regenerate via the exporter as the LAST data step; never hand-merge. |
| `data/ui/screens/*.json` | the 12 rects in 3 files | UR-4 may ADD a `background` key to some screen JSONs | UR-2 edits **only** existing `rect` values and adds no keys, so UR-4's later `background` additions are a clean, non-overlapping diff. |
| `tools/tests/test_ui_skinning.py` | `VIEW_W`/`VIEW_H` + `_BASELINE` | nobody else this phase | Re-pin, never delete (§4). |
| `game/ui/CLAUDE.md` | one new section | UR-5 may append findings | Append; do not restructure existing sections. |

---

## 4. Exit gate + Quick Test

### 4.1 Tests to re-pin (nine files, all in `tools/tests/`)

These construct screens at an **explicit** `VIEW_W`/`VIEW_H`, so they do not
read `display.json` and will not break from step 1 — they break from step 2
(the code constants). Move each to the shipped surface so the pins describe
what actually ships.

| File | `file:line` | What to do |
|---|---|---|
| `test_ui_skinning.py` | `:52` `VIEW_W, VIEW_H = 1280, 720`; `_BASELINE` at `:212+` with `1280, 720` backdrops at `:213,214,243,261,292,321,338,348,409,447` | Set `640, 360`, then **regenerate `_BASELINE`** (below). **RE-PIN, NEVER DELETE** — `planning/UiResolutionPLAN.md:152-154,240-243`: it is the only thing that catches an accidental re-scale later. Append a "Regenerated a SIXTH time (UR-2: the logical surface flipped 1280×720 → 640×360, so EVERY screen's default geometry moved on purpose)" note to the running `#:` changelog at `:180-211`, in the established voice. |
| `test_hud_panel.py` | `:38` | `VIEW_W, VIEW_H = 640, 360`; fix any assertion that hardcodes a derived HUD coordinate. |
| `test_shell.py` | `:19` `VW, VH = 1280, 720` | → `640, 360`. |
| `test_screen_honest_controls.py` | `:54` `"backdrop_a": {"rect": [0, 0, 1280, 720], ...}` | → `[0, 0, 640, 360]`. |
| `test_levelup.py` | `:800` `LevelupWindow(1280, 720)` | → `(640, 360)`; re-pin any rect assertion around it. |
| `test_button_skin.py` | `:202` `Shell(1280, 720, UI)` | → `(640, 360)`. This file's whole point is "unskinned output byte-identical" — keep that assertion, only the view size moves. |
| `test_10j_qol.py` | `:35` | → `640, 360`. |
| `test_right_click_dismiss.py` | `:35` | → `640, 360`. |
| `test_player_identity.py` | `:29` `VW, VH = 1280, 720` | → `640, 360`. |

**Two more the plan did not name; check and fix if red:**
`tools/tests/test_lightning.py:658,669,681,692,704` — five
`CheatMenu(1280, 720)` constructions, and the file reads `field_rect`/
`close_btn`/`go_btn` geometry directly. `tools/tests/test_vfx.py:169,172` is a
false positive (float VFX coordinates, not a resolution).

**Regenerating `_BASELINE`.** It is mechanical, not hand-tuned:
`tools/tests/test_ui_skinning.py:113-175` builds all 13 screens from the
module-level `VIEW_W`/`VIEW_H` and `_capture` (`:107`) records the primitive
stream. After the code conversion, dump `_screen_captures()` and paste the
repr into `_BASELINE`, preserving the existing one-primitive-per-line
formatting and the `#:` changelog comment block. Do it once, from the
converted tree — never guess an entry, never relax the equality.

**New tests: bare minimum.** One is enough and is the honest one: assert that
`data/display.json`'s `window_w`/`window_h` are `640`/`360` and that
`tools/export_ui_layouts.py`'s `_logical_resolution` returns the same pair —
i.e. that the exporter and the surface cannot drift. Read through the pinned
fixture, never live `data/`, per `data/CLAUDE.md`'s standing rule. Do not add
per-screen geometry coverage; that is what the golden pin already is.

### 4.2 Targeted test command

Per the router's test-suite policy, run an **explicit file list** while
iterating — NOT the full suite, NOT `--affected`:

```
py -m pytest tools/tests/test_ui_skinning.py tools/tests/test_hud_panel.py tools/tests/test_shell.py tools/tests/test_screen_honest_controls.py tools/tests/test_levelup.py tools/tests/test_button_skin.py tools/tests/test_10j_qol.py tools/tests/test_right_click_dismiss.py tools/tests/test_player_identity.py tools/tests/test_lightning.py -x -q
```

### 4.3 Exit gate

```
py tools/smoke.py
py tools/testgate.py check
```

**`GATE PASS` or you are not done.** The gate is ZERO
(`planning/UiResolutionPLAN.md:156`, root `CLAUDE.md` Step 2). Run the full
`check` exactly once, at the end, when handing work back — never as a
mid-task sanity run. Data changed, so confirm schema validation passes and
say so explicitly.

Additional non-negotiable checks:
- `data/ui/screen_defaults.json` is byte-identical to a fresh
  `py tools/export_ui_layouts.py` run (its own test enforces this; verify
  before committing so the diff is honest).
- `data/ui/fonts.json` and `data/geometry.json` show **zero** diff.
- The `data/` guard fixture is green — no test wrote into `data/`.

### 4.4 Quick Test (in-game, `py game/main.py`)

The phase's own gate (`planning/UiResolutionPLAN.md:156-159`). Walk these
five screens and confirm each renders **inside the frame with no clipping and
no overlap**:

1. **Main menu** — the seven-row button stack (START NEW GAME / PLAY DEBUG +
   its SET gear / ADD A NAME / HIGHSCORES / SETTINGS / CREDITS / QUIT) fits
   vertically with the title and subtitle above it; the QUIT button's lower
   edge is on screen and clickable. (The background art will be a stretched
   480×270 sheet — UR-4.)
2. **Pause** (Esc in gameplay) — the panel is centred, all four buttons
   inside it, the dim covers the full frame.
3. **HUD** — love pill, XP bar, income/lives/tiles readout pill, phase
   banner bottom-left, round label + END TURN bottom-right, PAUSE top-right,
   the speed row and the DRAG SEL row. **Specifically check the three icons
   against D1 (§1.1)**: love/xp/lives icons must sit inside their pill, not
   over its edge.
4. **Building panel** — click a tile: the right sidebar's width, the card
   list, the action button and the terrain badge all fit; then open the
   **construct preview** modal (name field + dice + CONFIRM/CANCEL) and
   confirm it is centred and fully on screen.
5. **Level-up** — trigger it (cheat menu, Ctrl+L → LEVEL UP): the 1-3 option
   boxes, the heading above them and each box's sprite/cost/explanation stay
   inside the frame.

**Expected and correct during all of the above: the world looks too close.**
That is `planning/UiResolutionPLAN.md` §3, deferred and deliberate. Report it
as observed-and-expected; do not fix it, and do not open `data/geometry.json`.

Log anything that reads cramped, any text overflowing a halved container, and
any control that now looks too small to click as **UR-5 review** items
(`planning/UiResolutionPLAN.md:209-222`) — surface them in the report, do not
hand-tune them in this phase.
