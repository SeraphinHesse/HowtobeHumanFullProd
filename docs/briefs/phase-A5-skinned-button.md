# Phase A5 — Game: skinned `widgets.Button` / `submit_panel` (hook only)

Slice 10L-A (`planning/UI_EDITOR_PLAN.md` lines 134-140, binding decisions at
55-64). Branch: `phase-A5-skinned-button`, cut off the umbrella **after A1+A2
and A3 land**. Package: **game only** (`game/ui` + a minimal `game/main.py`
thread). Docs: `CLAUDE.md` → `game/CLAUDE.md` → `game/ui/CLAUDE.md`.

**Dependency check before you write a line of code.** A1 added
`animation: str = "idle"` and `anim_time_ms: int = 0` to `HudSprite`,
**after `flip`** (`docs/briefs/phase-A1-hud-anim.md` §2, "Field-order decision
(binding)"), so the final signature is

```python
HudSprite(slot_key, dest, size, tint=None, flip=False,
          animation="idle", anim_time_ms=0)
```

and the renderer resolves it via `assets.frame(slot_key, animation,
anim_time_ms)`. Open `engine/render/hud.py` and confirm those two fields exist
before starting; **always pass them by keyword**. If they are not there, A1 has
not landed on your base — stop and say so, do not add them yourself
(`engine/**` is out of scope, §3).

---

## 1. Behavioral spec

### 1.1 What A5 delivers

A `widgets.Button` and a `widgets.submit_panel` can OPTIONALLY be given a
`skin` (a slot key). With a skin they draw as an animated, nine-sliced
`HudSprite` instead of flat rects. **Nothing assigns a skin yet** — plan line
138: *"Nothing assigns skins yet — 10L-B's screen JSON does."* A5 is the hook
plus the two pieces of state a skin needs (a pressed flag and an animation
clock). No screen JSON, no `data/**`, no defaults file.

### 1.2 The byte-identical guarantee (the crux of this phase)

Plan lines 44-49: *"**Unskinned = today's flat-rect rendering, byte-identical.**
… a screen with no JSON (or an empty one) must produce the exact HUD-primitive
stream it produces today — pinned by a parity test."*

With `skin=None` (the default, i.e. every button in the game after A5),
`Button.submit` and `submit_panel` must emit **exactly** the primitives they
emit today, in the same order, with the same field values:

- `Button.submit` (`game/ui/widgets.py:166-181`) →
  `HudRect(rect, fill, border_radius=3)`, then
  `HudRect(rect, C_UI_BORDER, border_radius=3, width=1)`, then the centred
  `HudText` at `y + (h - text_h(font_key)) // 2`.
- `submit_panel` (`widgets.py:87-90`) → `HudRect(rect, fill)`, then
  `HudRect(rect, border, width=1)`.

The `(fill, tcol, label)` selection at `widgets.py:167-175` — priority
**flash → disabled → normal(hover vs base)**, with `color=` / `text_color=`
overrides applying only in the normal branch — is **unchanged**. The
`color=`/`text_color=` kwargs are load-bearing: `game/ui/overlays.py:185` calls
`btn.submit(renderer, color=C_UI_BTN, text_color=C_GOLD)` for an active toggle
pill. They must keep working identically.

Pinned by the mandatory parity test in §4.

### 1.3 Pressed state (plan lines 55-61)

> *"`widgets.Button` today tracks hover + flash only. The host already owns
> mouse-down; `Button.hover(mx, my)` grows an optional `mouse_down` arg →
> `pressed` property."*

- `Button.hover(mx, my, mouse_down=False)`; `pressed` is `hovered and
  mouse_down` (so a disabled button is never pressed — `hovered` is already
  gated on `self.enabled`, `widgets.py:151`).
- **Accepted v1 simplification:** we do not track *where the press began*. A
  left button held down while the cursor drags onto a widget reads as pressed.
  The prototype's flat buttons had no pressed art at all, so there is no
  behavior to diverge from; state it in the doc.
- `mouse_down` defaults to `False`, so every existing `hover(mx, my)` call
  keeps compiling and every unfed button behaves exactly as today.

### 1.4 State → animation mapping (plan lines 58-61)

> *"`disabled` → disabled row, flash → pressed row (the not-enough-love red
> flash becomes the pressed art when skinned; label overlay unchanged), else
> pressed/hover/idle rows. Missing rows fall back to idle (existing manifest
> semantics — partial sheets are fine)."*

Resolve in **the same priority order the flat path already uses**
(`widgets.py:167-175`) so a skinned and an unskinned button never disagree
about which state they are in:

| # | Condition | Flat fill (unchanged) | Skinned `animation` |
|---|---|---|---|
| 1 | `self.flash > 0` | `C_RED` + `flash_label` | `"pressed"` |
| 2 | `not self.enabled` | `C_UI_BTN_DISABLED` / `C_UI_TEXT_DIM` | `"disabled"` |
| 3 | `self.pressed` | `C_UI_BTN_HOVER` (hover fill — flat path has no pressed fill) | `"pressed"` |
| 4 | `self.hovered` | `C_UI_BTN_HOVER` | `"hover"` |
| 5 | else | `C_UI_BTN` (or `color=`) | `"idle"` |

Rows 3 and 4 collapse to the same flat fill — that is why the flat output is
unchanged by adding pressed tracking, and it is exactly what the parity test
pins.

**Label overlay unchanged**: the skinned button still draws the *same* centred
`HudText` (same string incl. `flash_label`, same font, same `tcol` incl. a
`text_color=` override, same y). Only the two `HudRect`s are replaced by one
`HudSprite`. `color=` (a fill override) is ignored when skinned — there is no
rect to fill; say so in the docstring.

**Missing rows need no code.** `Manifest.current_frame` already falls back to
the idle row for an unknown animation and to the grey-X placeholder for a slot
with no art (`docs/briefs/phase-A1-hud-anim.md` §1.4; `engine/assets/CLAUDE.md`
E-36/E-37). A 1-row (idle-only) sheet skinned onto a button just draws idle in
all four states. Do not add fallback logic.

### 1.5 UI animation clock (plan lines 62-64)

> *"screens accumulate one `anim_ms` in their `update(dt)` and pass it to
> skinned submits (no per-widget phase in v1 …)."*

- **One clock per screen**, not per widget. Mirrors the established
  `game/ui/hud.py:132` `self._clock = 0.0` / `:151` `self._clock += dt`
  pattern. All widgets on a screen animate in phase.
- `dt` is **seconds** (`game/main.py:448`: `clock.tick(fps) / 1000.0`);
  `HudSprite.anim_time_ms` is **integer ms**. The conversion is explicit and
  lives in ONE place — a new `widgets.anim_ms(clock_s)` helper (§2.1). Never
  accumulate `int(dt * 1000)` per frame (truncation drifts ~4% slow at 60 fps).
- The clock reaches the widget as an explicit **`anim_ms=` keyword on
  `submit()`** (and on `submit_panel`). No hidden state on the widget, no
  module-level global, no per-widget phase offset.
- A screen that never passes `anim_ms` renders a skinned widget frozen at frame
  0. Harmless in A5 (nothing has a skin) but a trap for 10L-B, so A5 threads
  the clock through **every** `game/ui` screen that owns buttons or panels.

### 1.6 Purity

`game/ui` must never import pygame — enforced by the directory-wide source scan
in `tools/tests/test_shell.py:259-274`. `widgets.py` grows one import
(`HudSprite` from `engine.render`, alongside `HudRect`/`HudText` at
`widgets.py:10`); pygame stays in `game/main.py` (the host), which is where the
held-mouse-button read belongs.

---

## 2. Architecture plan

Edit in this order. Every new argument is defaulted, so **no existing call site
breaks** — that is the invariant that makes this diff safe.

### 2.1 `game/ui/widgets.py` — the core

**(a) import (line 10)**

```python
from engine.render import HudRect, HudText            # current
from engine.render import HudRect, HudSprite, HudText # target
```

**(b) the seconds→ms helper** (new, next to `text_size`/`text_h`)

```python
def anim_ms(clock_s):
    """A screen's float seconds accumulator -> the integer ms a skinned
    HudSprite wants (10L-A). ONE conversion, so no screen re-derives it."""
    return int(clock_s * 1000)
```

**(c) `submit_panel` (currently lines 87-90)**

Current:

```python
def submit_panel(renderer, rect, *, fill=C_UI_PANEL, border=C_UI_BORDER):
    """A filled, bordered panel body."""
    renderer.submit_hud(HudRect(rect, fill))
    renderer.submit_hud(HudRect(rect, border, width=1))
```

Target:

```python
def submit_panel(renderer, rect, *, fill=C_UI_PANEL, border=C_UI_BORDER,
                 skin=None, anim_ms=0):
    """A filled, bordered panel body. With ``skin`` (a slot key, 10L-A) the
    two flat rects are replaced by one nine-sliced HudSprite covering the same
    rect; ``fill``/``border`` are then ignored. Panels carry no interaction
    state, so they always animate the ``idle`` row."""
    if skin:
        x, y, w, h = rect
        renderer.submit_hud(HudSprite(skin, (x, y), (w, h),
                                      animation="idle", anim_time_ms=anim_ms))
        return
    renderer.submit_hud(HudRect(rect, fill))
    renderer.submit_hud(HudRect(rect, border, width=1))
```

(The local name `anim_ms` shadows the module helper inside this function — fine,
the helper is only called by screens. If that bothers you, import-free rename
the helper to `to_anim_ms`; keep ONE name and use it everywhere.)

**(d) `Button` (currently lines 132-181)**

```python
class Button:
    """... (keep the existing docstring, add:)

    10L-A: an optional ``skin`` (a slot key) swaps the two flat rects for one
    animated, nine-sliced ``HudSprite`` — the centred label is drawn exactly
    the same either way. With no skin the emitted primitives are byte-identical
    to pre-10L (pinned by tools/tests/test_button_skin.py). ``hover`` takes the
    host's held-left-button flag so the widget can report ``pressed``.
    """

    def __init__(self, rect, label, font_key="lg", enabled=True, skin=None):
        self.rect = rect
        self.label = label
        self.font_key = font_key
        self.enabled = enabled
        self.skin = skin          # 10L-A: slot key, or None = flat rects
        self.hovered = False
        self.mouse_down = False   # 10L-A: host's held-left-button flag
        self.flash = 0.0
        self.flash_label = None

    def hover(self, mx, my, mouse_down=False):
        self.hovered = self.enabled and contains(self.rect, mx, my)
        self.mouse_down = bool(mouse_down)

    @property
    def pressed(self):
        """Held down over this button (10L-A). Never true when disabled —
        ``hovered`` is already gated on ``enabled``."""
        return self.hovered and self.mouse_down

    # hit / start_flash / update(dt) UNCHANGED (lines 153-164)

    def _state(self):
        """Skin animation row. Same priority as the flat fill selection below,
        so skinned and unskinned never disagree about the button's state
        (plan lines 58-61: flash -> pressed art, disabled -> disabled row)."""
        if self.flash > 0:
            return "pressed"
        if not self.enabled:
            return "disabled"
        if self.pressed:
            return "pressed"
        return "hover" if self.hovered else "idle"

    def submit(self, renderer, *, color=None, text_color=None, anim_ms=0):
        x, y, w, h = self.rect
        if self.flash > 0:
            fill, tcol = C_RED, C_UI_TEXT
            label = self.flash_label or self.label
        elif not self.enabled:
            fill, tcol, label = C_UI_BTN_DISABLED, C_UI_TEXT_DIM, self.label
        else:
            fill = color or (C_UI_BTN_HOVER if self.hovered else C_UI_BTN)
            tcol = text_color or C_UI_TEXT
            label = self.label
        if self.skin:
            # 10L-A: the sprite replaces both rects; ``color`` (a fill
            # override) has nothing to fill and is ignored. Label unchanged.
            renderer.submit_hud(HudSprite(self.skin, (x, y), (w, h),
                                          animation=self._state(),
                                          anim_time_ms=anim_ms))
        else:
            renderer.submit_hud(HudRect((x, y, w, h), fill, border_radius=3))
            renderer.submit_hud(HudRect((x, y, w, h), C_UI_BORDER,
                                        border_radius=3, width=1))
        ty = y + (h - text_h(self.font_key)) // 2
        submit_centered(renderer, label, x + w // 2, ty, self.font_key, tcol)
```

The `(fill, tcol, label)` block is copied verbatim from today — do not
restructure it. The `else:` branch is today's two `submit_hud` lines verbatim.
That is what makes the parity test pass by construction.

### 2.2 `game/main.py` — thread the held-left-button flag (MINIMAL diff)

`mouse_down` at `main.py:444` is a *local* `(x, y)` press position for the 4px
pan/drag threshold (set at 517, cleared at 535-536) — **do not touch it, do not
reuse it, do not rename it.** The pressed flag is a separate, simpler read.

At `main.py:548`, one new line beside the existing cursor read:

```python
        mx, my = pygame.mouse.get_pos()
        held = pygame.mouse.get_pressed()[0]   # 10L-A: skinned pressed state
```

(`pygame.mouse.get_pressed()` is safe headless — the SDL dummy driver reports
all-false; `tools/smoke.py` and the boot tests keep working.)

Then pass `held` at the seven existing per-frame call sites — all keyword, all
optional on the receiving side:

| main.py line | current | target |
|---|---|---|
| 618 | `gp["hud"].update(dt, mx, my, session, gp["panel"])` | `…, gp["panel"], mouse_down=held)` |
| 619 | `gp["panel"].hover(mx, my)` | `gp["panel"].hover(mx, my, held)` |
| 621 | `gp["overlays"].update(dt, mx, my)` | `gp["overlays"].update(dt, mx, my, held)` |
| 633 | `gp["cheat"].update(dt, mx, my)` | `gp["cheat"].update(dt, mx, my, held)` |
| 635 | `gp["levelup"].update(dt, mx, my)` | `gp["levelup"].update(dt, mx, my, held)` |
| 636 | `gp["boss_cutscene"].update(dt, mx, my)` | `gp["boss_cutscene"].update(dt, mx, my, held)` |
| 638 | `gp["game_over"].update(dt, mx, my)` | `gp["game_over"].update(dt, mx, my, held)` |
| 640 | `shell.update(dt, mx, my)` | `shell.update(dt, mx, my, held)` |

Nothing else in `main.py` changes. No new event handling, no MOUSEBUTTONDOWN /
MOUSEBUTTONUP edits, no change to `pan_from` / `over_ui` / the click ladder.

### 2.3 `game/ui/shell.py` — pass-through only

```python
    def update(self, dt, mx, my, mouse_down=False):
        screen = self._active_screen()
        if screen is not None:
            screen.update(dt, mx, my, mouse_down)
```

`submit` (line 180-183) is unchanged — each screen owns its own clock and
passes it to its own widgets.

### 2.4 The screens — `mouse_down` + one clock each (mechanical)

For **every** `game/ui` screen that owns `Button`s, three edits and nothing
else (no layout, no behavior, no new widgets):

1. `__init__`: `self._clock = 0.0  # 10L-A: one anim clock per screen`
   (`hud.py` already has `self._clock` at :132 — **reuse it**, add nothing).
2. `update(...)`: grow a trailing `mouse_down=False` param, add
   `self._clock += dt`, and forward the flag in the existing hover loop:
   `btn.hover(mx, my, mouse_down)`.
3. `submit(...)`: pass `anim_ms=anim_ms(self._clock)` at each `btn.submit(...)`
   and at each `submit_panel(...)` call. Compute it once at the top of
   `submit()` (`t = anim_ms(self._clock)`) and pass `anim_ms=t`.

Exact call sites (verified):

| File | `update` / `hover` (add `mouse_down`) | `submit` (add `anim_ms=`) |
|---|---|---|
| `main_menu.py` | 45-49 | 66 |
| `settings.py` | 83-89 | 119-135 |
| `credits.py` | 44-47 | 66 |
| `pause.py` | 40-44 | 62 |
| `add_name.py` | 65-69 | 121-122; `submit_panel` @ 98 |
| `cheat_menu.py` | 97-102 | 157-176; `submit_panel` @ 154 |
| `game_over.py` | 25-28 (`update(self, dt, mx, my, mouse_down=False)`) | 47 |
| `levelup.py` | 60-62 | 102-103 area (its buttons) |
| `boss_cutscene.py` | 59-61 | its buttons |
| `hud.py` | `update(self, dt, mx, my, session, panel, mouse_down=False)` @ 148; `hover` @ 159/163; `_clock` @ 132/151 already exists | 226/229 |
| `overlays.py` | `update(self, dt, mx, my, mouse_down=False)` @ 98-102 (needs a new `_clock`) | `submit_buttons` @ 185/189 — **keep `color=`/`text_color=`**, just add `anim_ms=` |
| `building_ui.py` | `BuildingUI.hover(self, mx, my, mouse_down=False)` @ 550 → forward to every `btn.hover(mx, my, mouse_down)` (556-591) and to `self.preview.hover(mx, my, mouse_down)` @ 560; `ConstructPreview.hover(self, mx, my, mouse_down=False)` @ 157-165; clock ticks in `BuildingUI.update(dt)` @ 785 and `ConstructPreview.update(dt)` @ 167 | every `btn.submit(renderer …)` inside `BuildingUI.submit` (from 800) and `ConstructPreview.submit` (from 206), plus `submit_panel` @ 210, 810, 1116 |

`building_ui.py` carries the bulk of the churn: it is pure mechanical
`anim_ms=t` / `mouse_down` threading — **no other change to that file**. If any
button there is drawn but not updated, do NOT restructure — just pass the same
`t`; the clock is the panel's, not the widget's.

### 2.5 `game/ui/CLAUDE.md`

Add a short section (under the 9G in-round UI section or a new "Skinnable
widgets (10L-A)" heading): `widgets.Button`/`submit_panel` take an optional
`skin` slot key → one animated nine-sliced `HudSprite` instead of flat rects,
label overlay unchanged, **unskinned output byte-identical** (pinned by
`tools/tests/test_button_skin.py`); `hover(mx, my, mouse_down)` → `pressed`
(the host reads `pygame.mouse.get_pressed()[0]`; press-origin is not tracked —
accepted v1 simplification); state→row map flash/pressed→`pressed`,
disabled→`disabled`, hover→`hover`, else `idle`, missing rows fall back to idle
via the manifest; **one anim clock per screen** (`self._clock` seconds →
`widgets.anim_ms()`), no per-widget phase; **nothing assigns skins yet** —
10L-B's screen JSON does.

---

## 3. File scope + shared-file contract (binding)

A5 runs **in parallel with A4** (editor slice-margins editor). A4 touches
`editor/**` + `tools/tests/test_details_panel.py` +
`tools/tests/test_editor_viewport.py` only. There is **no overlap**.

A5's file scope — exactly these:

- `game/ui/widgets.py` — Button + `submit_panel` (the core).
- `game/main.py` — thread the held-mouse-down bool into the per-frame
  hover/update calls. MINIMAL diff (§2.2).
- `game/ui/shell.py`, `game/ui/hud.py` (+ any other `game/ui/*.py` screen) —
  **only** to thread `mouse_down` / `anim_ms` through `update`/`hover`/`submit`.
  No behavior changes.
- `game/ui/CLAUDE.md` — doc update (skin hook + pressed state + anim clock).
- `tools/tests/` — a NEW file `tools/tests/test_button_skin.py` (the parity pin
  + skinned-state mapping tests). Do **NOT** edit `test_shell.py`,
  `test_hud_panel.py`, `test_10j_qol.py` unless a signature change forces it —
  and if it does, keep the diff minimal and say so in the PR.

**A5 must NOT touch**: `engine/**`, `editor/**`, `data/**`.

---

## 4. Exit gate + Quick Test

### Commands

```
py -m unittest discover -s tools/tests -t .     # 1086 tests
py tools/smoke.py
```

**Gate = no NEW failures.** Baseline on Development is **16 failures / 1
skipped**: `test_run_controls` ×1, `test_details_panel` ×1,
`test_editor_viewport` ×3, `test_editor_panels` ×2, `test_editor_map_mode` ×2,
`test_balancing_parity` ×6. Do not try to fix those. **None of them is a `game/`
test — so any new failure in a game test is A5's fault.** `test_shell.py`
(incl. `TestPurity`), `test_hud_panel.py`, `test_10j_qol.py` must stay green
untouched: that is your real regression signal for the threading.

### New tests — all in `tools/tests/test_button_skin.py`

Use a recording fake renderer (record every `submit_hud(item)` into a list) —
no pygame, no SDL. `game/ui` is pure, so the whole file is plain dataclass
equality. (`tools/tests/test_shell.py:21-39` has the established fake-assets /
recording-backend pattern if you prefer a real `Renderer`; a 5-line
`class _Rec: submit_hud = list.append`-style fake is enough and faster.)

1. **`test_unskinned_button_parity`** — **MANDATORY, the crux of the phase.**
   For each of the four states — normal, hovered, disabled, flashing (also:
   hovered **and** `mouse_down=True`, i.e. `pressed`, which must render the
   same as plain hovered) — submit an unskinned `Button((10, 20, 100, 30),
   "GO", font_key="md")` and assert the recorded list equals the **literal**
   expected stream, field for field:
   `[HudRect((10,20,100,30), fill, border_radius=3),
     HudRect((10,20,100,30), C_UI_BORDER, border_radius=3, width=1),
     HudText("GO", (60, ty), "md", tcol, align="center")]`
   with `fill`/`tcol` per the table in §1.4 and
   `ty = 20 + (30 - text_h("md")) // 2`. Also assert **no `HudSprite` is ever
   emitted** and that `color=`/`text_color=` overrides still take effect in the
   normal branch (the `overlays.py:185` call form).
2. **`test_unskinned_panel_parity`** — `submit_panel(r, (0, 0, 40, 50))` emits
   exactly `[HudRect((0,0,40,50), C_UI_PANEL), HudRect((0,0,40,50),
   C_UI_BORDER, width=1)]`; custom `fill=`/`border=` still honoured; no
   `HudSprite`.
3. **`test_skinned_button_emits_sprite_plus_label`** — `Button(rect, "GO",
   skin="ui_button")`: exactly two items — `HudSprite("ui_button", (x, y),
   (w, h), animation=…, anim_time_ms=…)` then the **same** `HudText` the
   unskinned button emits (assert equality against the unskinned run's text
   item). Zero `HudRect`s. `anim_ms=1234` → `anim_time_ms == 1234`.
4. **`test_skinned_state_rows`** — table-driven over §1.4: idle / hovered →
   `"hover"` / hovered+`mouse_down` → `"pressed"` / `enabled=False` →
   `"disabled"` / `start_flash(0.5)` → `"pressed"` (and the label is
   `flash_label` when given — label overlay unchanged). Flash beats disabled.
5. **`test_skinned_panel`** — `submit_panel(r, rect, skin="ui_panel",
   anim_ms=99)` emits exactly one `HudSprite(…, animation="idle",
   anim_time_ms=99)` and no `HudRect`.
6. **`test_pressed_property`** — `hover(mx, my)` (no arg) → `pressed is False`
   (the default keeps every unfed caller unpressed); inside + `mouse_down=True`
   → True; outside + `mouse_down=True` → False; `enabled=False` +
   `mouse_down=True` → False.
7. **`test_screen_threads_mouse_down_and_clock`** — end-to-end through the pure
   shell (no pygame): `Shell(1280, 720, ui_balance)`;
   `shell.update(0.1, *centre_of_first_main_menu_button, True)` → that
   `Button.pressed is True`; ten `update(0.1, …)` calls →
   `widgets.anim_ms(shell.main_menu._clock) == 1000` (the seconds→ms conversion
   is explicit and drift-free).

### Quick Test (human, in-game)

1. **Temporarily** hardcode a skin on one main-menu button — in
   `game/ui/main_menu.py:34`, `Button((0, 0, _BTN_W, _BTN_H), label,
   skin="ui_button")` — and make sure `main_menu.submit` passes
   `anim_ms=anim_ms(self._clock)` (it should, per §2.4).
2. `py game/main.py` → the main menu. The 320×52 buttons draw as the imported
   `ui_button` sheet, **nine-sliced** (corners crisp, edges stretched — A2's
   `slice` margins), animating: **idle** at rest, **hover** under the cursor,
   **pressed** while the left button is held on it, **disabled** row if you
   temporarily set `enabled=False`. The label sits on top, unchanged and
   centred. A slot with no imported art shows the grey X, never a crash.
3. Un-skinned buttons elsewhere (settings, pause, the HUD End Turn, the
   building panel) must look **exactly** as before.
4. **REVERT THE HARDCODED SKIN BEFORE COMMITTING.** Plan line 139-140: the skin
   assignment is 10L-B's screen JSON. A committed hardcoded `skin=` is a
   phase-scope violation — `git diff` your final tree and confirm no `skin="…"`
   literal survives outside tests and docstrings.
5. Also confirm a full round still plays (build → end turn → wave) — you
   touched `hud.update`, `panel.hover` and the `main.py` update block, so a
   TypeError there would surface immediately.
