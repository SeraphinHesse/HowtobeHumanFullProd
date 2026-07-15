# Phase A5′ — Game: skinned `widgets.Button` / `submit_panel` + R2 hit seam

Slice 10L-A (`planning/UI_EDITOR_PLAN.md` lines 225-239, R2 settled design at lines 68-80). Branch: `phase-10L-finish-umbrella`, one PR. Package: **game only** (`game/ui` + a minimal `game/main.py` seam). Docs: `CLAUDE.md` → `game/CLAUDE.md` → `game/ui/CLAUDE.md`.

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

### 1.1 What A5′ delivers

A `widgets.Button` and a `widgets.submit_panel` can OPTIONALLY be given a
`skin` (a slot key). With a skin they draw as an animated, nine-sliced
`HudSprite` instead of flat rects. **Nothing assigns a skin yet** — plan line 238: *"Nothing assigns skins yet — 10L-B's screen JSON does."* A5′ is the hook
plus the two pieces of state a skin needs (a pressed flag and an animation
clock). No screen JSON, no `data/**`, no defaults file.

### 1.2 The byte-identical guarantee (the crux of this phase)

Plan lines 44-49: *"**Unskinned = today's flat-rect rendering, byte-identical.**
… a screen with no JSON (or an empty one) must produce the exact HUD-primitive
stream it produces today — pinned by a parity test."*

With `skin=None` (the default, i.e. every button in the game after A5′),
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
  0. Harmless in A5′ (nothing has a skin) but a trap for 10L-B, so A5′ threads
  the clock through **every** `game/ui` screen that owns buttons or panels.

### 1.6 Purity

`game/ui` must never import pygame — enforced by the directory-wide source scan
in `tools/tests/test_shell.py:259-274`. `widgets.py` grows one import
(`HudSprite` from `engine.render`, alongside `HudRect`/`HudText` at
`widgets.py:10`); pygame stays in `game/main.py` (the host), which is where the
held-mouse-button read belongs.

### 1.7 R2 hit seam — pixel-perfect clickable surface (plan lines 68-80)

Skinned buttons hover AND click only over drawn pixels (alpha > 0). The R2
hit-seam design provides a host-injected per-pixel alpha test without coupling
`game/ui` to pygame or the asset system.

**Canonical-silhouette convention:** widgets always query `("idle", 0)` —
hit-testing the drawn state row oscillates at silhouette holes. Consequence:
cursor over a hole in the hover row → un-hovers → idle opaque → re-hovers,
flicker. This is accepted — the silhouette from the idle frame is the
ground-truth click target, stable across all row animations.

**The seam:**
- Module level: `_skin_hit_test = None` (mutable, for testing) + `def
  set_skin_hit_test(fn)` to set it at runtime.
- `Button._surface_hit(mx, my) -> bool`: rect `contains` first (fast path);
  if `self.skin is None` or seam is unset → return True (byte-identical to
  unskinned rects today). Else call `_skin_hit_test(self.skin, "idle", 0,
  (w, h), (mx - x, my - y))`.
- `Button.hover(mx, my, mouse_down=False)` and `Button.hit(mx, my)` **both**
  route through `_surface_hit` for the point test (hovered/hit → query the
  seam; no seam → plain rect). This unifies skinned and unskinned behavior.
- `submit_panel` gets **no hit test** — panels are not click targets. They are
  drawn via flat rects (or skins when 10L-B assigns them), but `submit()` never
  calls `hit()`. The seam is only wired on Button.
- **Host wiring** (game/main.py): ONE line right after the `AssetStore` is
  built: `widgets.set_skin_hit_test(assets.hit_opaque)`. At startup only —
  never reset it. The A8 phase (landing in the same umbrella wave, before this
  phase merges) provides `AssetStore.hit_opaque(slot_key, animation,
  anim_time_ms, dest_size, rel_xy) -> bool`; placeholder/missing art → True
  everywhere, so headless boots behave identically.
- **Tests** (§4): inject a fake refusing test, verify both `hover()` and
  `hit()` route through it, assert it receives exactly `("idle", 0)`, cleanup
  the seam. An unset seam or `skin=None` is rect-only (tested separately).

---

## 2. Architecture plan

Edit in this order. Every new argument is defaulted, so **no existing call site
breaks** — that is the invariant that makes this diff safe.

### 2.1 `game/ui/widgets.py` — the core + R2 hit seam

**(a) import (line 10)**

```python
from engine.render import HudRect, HudText            # current
from engine.render import HudRect, HudSprite, HudText # target
```

**(b) module level: the hit seam + the seconds→ms helper**

At the top of the module (after imports, before the first class):

```python
# R2 hit seam: host-injected per-pixel alpha test for skinned buttons
_skin_hit_test = None

def set_skin_hit_test(fn):
    """Inject a per-pixel alpha hit-test function (A8, host wiring).
    Signature: fn(slot_key, animation, anim_time_ms, dest_size, rel_xy) -> bool.
    None (the default) means unskinned rects only."""
    global _skin_hit_test
    _skin_hit_test = fn

def anim_ms(clock_s):
    """A screen's float seconds accumulator -> the integer ms a skinned
    HudSprite wants (10L-A). ONE conversion, so no screen re-derives it."""
    return int(clock_s * 1000)
```

**(c) `Button._surface_hit` (new method, right before `hover`)**

```python
def _surface_hit(self, mx, my):
    """Rect hit-test; if skin + seam exists, delegate to the injected
    alpha test. Canonical-silhouette query: ("idle", 0) only, so cursor
    oscillates over silhouette holes. R2."""
    x, y, w, h = self.rect
    if not contains(self.rect, mx, my):
        return False
    if self.skin is None or _skin_hit_test is None:
        return True
    return _skin_hit_test(self.skin, "idle", 0, (w, h), (mx - x, my - y))
```

**(d) `Button.hover` and `Button.hit` (use _surface_hit)**

Update `Button.hover`:

```python
def hover(self, mx, my, mouse_down=False):
    self.hovered = self.enabled and self._surface_hit(mx, my)
    self.mouse_down = bool(mouse_down)
```

Update `Button.hit` (find the existing one-liner and replace it):

```python
def hit(self, mx, my):
    return self.enabled and self._surface_hit(mx, my)
```

**(e) `submit_panel` (currently lines 87-90)**

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
    state, so they always animate the ``idle`` row. Panels are not click
    targets — no hit-test wiring."""
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

**(f) `Button` class (currently lines 132-181)**

```python
class Button:
    """... (keep the existing docstring, add:)

    10L-A: an optional ``skin`` (a slot key) swaps the two flat rects for one
    animated, nine-sliced ``HudSprite`` — the centred label is drawn exactly
    the same either way. With no skin the emitted primitives are byte-identical
    to pre-10L (pinned by tools/tests/test_button_skin.py). ``hover`` takes the
    host's held-left-button flag so the widget can report ``pressed``.

    R2 (10L-A): skinned ``hover`` and ``click`` only over drawn pixels (alpha >
    0), via a host-injected seam querying the idle row (`_surface_hit`). The
    seam is unset by default (pure game code); host wires it once at startup
    (`game/main.py`: `widgets.set_skin_hit_test(assets.hit_opaque)`). With no
    seam or no skin, behaves as today (rect test).
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

    def _surface_hit(self, mx, my):
        """Rect hit-test; if skin + seam exists, delegate to the injected
        alpha test. Canonical-silhouette query: ("idle", 0) only, so cursor
        oscillates over silhouette holes. R2."""
        x, y, w, h = self.rect
        if not contains(self.rect, mx, my):
            return False
        if self.skin is None or _skin_hit_test is None:
            return True
        return _skin_hit_test(self.skin, "idle", 0, (w, h), (mx - x, my - y))

    def hover(self, mx, my, mouse_down=False):
        self.hovered = self.enabled and self._surface_hit(mx, my)
        self.mouse_down = bool(mouse_down)

    @property
    def pressed(self):
        """Held down over this button (10L-A). Never true when disabled —
        ``hovered`` is already gated on ``enabled``."""
        return self.hovered and self.mouse_down

    def hit(self, mx, my):
        """Check if this point is a hit (10L-A: via _surface_hit for R2 seam)."""
        return self.enabled and self._surface_hit(mx, my)

    def start_flash(self, duration, label=None):
        """... (keep unchanged)"""
        # (existing implementation remains)

    def update(self, dt):
        """... (keep unchanged)"""
        # (existing implementation remains)

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

### 2.2 `game/main.py` — thread the held-left-button flag + R2 seam wiring

**Line-drift warning:** The brief's line-number table below has drifted — the
update block moved ~30 lines; ER-5 and fixture-pinning landed since. **RE-LOCATE
EVERY INSERTION POINT BY PATTERN, NEVER BY LINE NUMBER.** Patterns are stable.

**(a) R2 seam wiring (one line, right after AssetStore construction)**

Find the line that builds the `AssetStore` (pattern: `AssetStore(` or similar).
Immediately after that block closes (when the `assets` variable is assigned),
add:

```python
widgets.set_skin_hit_test(assets.hit_opaque)  # R2: pixel-perfect click targets
```

This runs exactly once at startup. If A8 has not landed yet (it provides
`hit_opaque`), this line will raise `AttributeError` — that is correct; do not
work around it (it means A8 has not merged yet).

**(b) Read the held-left-button flag (pattern: `pygame.mouse.get_pos()`)**

Find where the frame loop reads `mx, my = pygame.mouse.get_pos()`. On the next
line, add:

```python
held = pygame.mouse.get_pressed()[0]   # 10L-A: skinned pressed state
```

(`pygame.mouse.get_pressed()` is safe headless — the SDL dummy driver reports
all-false; `tools/smoke.py` and the boot tests keep working.)

**(c) Pass `held` at call sites (7 calls, all keyword, all optional on receiving side)**

Find these patterns and pass `mouse_down=held` at each:

| Pattern | Current | Add keyword arg |
|---|---|---|
| `gp["hud"].update(dt, mx, my, session, gp["panel"])` | threading | `mouse_down=held` |
| `gp["panel"].hover(mx, my)` | threading | `mouse_down=held` |
| `gp["overlays"].update(dt, mx, my)` | threading | `mouse_down=held` |
| `gp["cheat"].update(dt, mx, my)` | threading | `mouse_down=held` |
| `gp["levelup"].update(dt, mx, my)` | threading | `mouse_down=held` |
| `gp["boss_cutscene"].update(dt, mx, my)` | threading | `mouse_down=held` |
| `gp["game_over"].update(dt, mx, my)` | threading | `mouse_down=held` |
| `shell.update(dt, mx, my)` | threading | `mouse_down=held` |

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

**Exact call sites (verified, 12 live screens):**

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
| `game_log.py` | **No buttons.** Container-only (dynamic lists). No threading needed. |

`building_ui.py` carries the bulk of the churn: it is pure mechanical
`anim_ms=t` / `mouse_down` threading — **no other change to that file**. If any
button there is drawn but not updated, do NOT restructure — just pass the same
`t`; the clock is the panel's, not the widget's.

### 2.5 `game/ui/CLAUDE.md`

Add a new section (under "Skinnable widgets (10L-A)" or extending an existing
section): 

`widgets.Button`/`submit_panel` take an optional `skin` slot key → one animated
nine-sliced `HudSprite` instead of flat rects, label overlay unchanged, **unskinned
output byte-identical** (pinned by `tools/tests/test_button_skin.py`).

`hover(mx, my, mouse_down)` → `pressed` (the host reads `pygame.mouse.get_pressed()[0]`;
press-origin is not tracked — accepted v1 simplification); state→row map: flash/pressed→`"pressed"`,
disabled→`"disabled"`, hover→`"hover"`, else `"idle"`, missing rows fall back to idle
via the manifest.

**One anim clock per screen** (`self._clock` seconds → `widgets.anim_ms()`), no
per-widget phase; **nothing assigns skins yet** — 10L-B's screen JSON does.

**R2 pixel-perfect clickable surface:** skinned buttons hover AND click only over
drawn pixels (alpha > 0), via a host-injected seam (`widgets.set_skin_hit_test(fn)`).
The seam queries the `("idle", 0)` canonical silhouette — cursor over a hole in the
hover row oscillates. The seam is unset by default; host wires it once at startup
(`game/main.py`: `widgets.set_skin_hit_test(assets.hit_opaque)` right after `AssetStore`
is built, A8 phase). Unset seam or `skin=None` = rect-only. Panels are not click
targets — no hit-test wiring on `submit_panel`.

---

## 3. File scope + shared-file contract (binding)

A5′ runs **in parallel with A4** (editor slice-margins editor) and **B4**
(editor screen mode). A4 touches `editor/**` + `tools/tests/test_details_panel.py`
+ `tools/tests/test_editor_viewport.py` only. B4 touches `editor/**` only.
There is **no file overlap with A5′**.

A5′'s file scope — exactly these:

- `game/ui/widgets.py` — Button + `submit_panel` (the core + R2 hit seam).
- `game/main.py` — thread the held-mouse-down bool into the per-frame
  hover/update calls; wire the R2 hit seam. MINIMAL diff (§2.2).
- `game/ui/shell.py`, `game/ui/hud.py` (+ any other `game/ui/*.py` screen) —
  **only** to thread `mouse_down` / `anim_ms` through `update`/`hover`/`submit`.
  No behavior changes.
- `game/ui/CLAUDE.md` — doc update (skin hook + pressed state + anim clock + R2 seam).
- `tools/tests/` — a NEW file `tools/tests/test_button_skin.py` (the parity pin
  + skinned-state mapping + R2 seam tests). **`conftest.py` ownership:** this phase
  adds `"test_button_skin": "core"` to the TIERS dict — it is the **ONLY phase
  in the umbrella wave allowed to touch conftest.py** (B4 runs parallel and
  deliberately adds no test module).
- Do **NOT** edit `test_shell.py`, `test_hud_panel.py`, `test_10j_qol.py` unless
  a signature change forces it — and if it does, keep the diff minimal and say
  so in the PR.

**A5′ must NOT touch**: `engine/**`, `editor/**`, `data/**`.

---

## 4. Exit gate + Quick Test

### Commands

```
py tools/smoke.py
py tools/testgate.py check --affected
```

**Gate = ZERO failures.** No baseline talk — the new tests in `test_button_skin.py`
plus threading the purity tests must all pass, and no regressions in the game/ui
tests. `tools/testgate.py check --affected` runs the minimal set (affected modules
only) and must exit 0.

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

### New tests — R2 hit seam (all in `test_button_skin.py`)

8. **`test_no_seam_or_no_skin_is_rect_only`** — both conditions route to rect:
   `Button((10, 20, 100, 30), "GO")` with `_skin_hit_test = None` (default) →
   `hover(15, 25)` → hovered (rect hit), `hover(5, 5)` → not hovered (rect miss);
   same with `skin="ui_button"` (still rect if seam is None).

9. **`test_hover_and_hit_respect_the_injected_hit_test`** — wire a fake seam
   that always refuses (returns False): `set_skin_hit_test(lambda *_: False);
   addCleanup(set_skin_hit_test, None)` — CRITICAL for cleanup. `Button(rect,
   "GO", skin="ui_button").hover(inside_rect_point)` → not hovered (fake
   refused); `Button(...).hit(inside_rect_point)` → False (fake refused). Then
   swap the fake to always accept (`lambda *_: True`) and both hover/hit pass.

10. **`test_hit_seam_receives_canonical_silhouette`** — capture what the fake
    seam receives: `calls = []; set_skin_hit_test(lambda *args: (calls.append(args),
    True)[1]); addCleanup(...)`. `Button(…, skin="ui_button").hover(x, y)` →
    the captured `args` is `("ui_button", "idle", 0, (w, h), (rel_x, rel_y))`
    exactly (four args: slot, animation="idle", frame=0, dest_size tuple,
    rel_xy tuple). Never "hover" or any other frame.

11. **`test_panels_have_no_hit_test`** — `submit_panel(..., skin="ui_panel",
    anim_ms=50)` → no seam call is made, whether set or not; it emits a
    `HudSprite` but does not call `_skin_hit_test`. (Panels don't have a
    `hit()` method; this test just verifies the seam is not wired into
    `submit_panel`.)

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
3. **Verify pixel-perfect clicking:** hover over a transparent corner (if the
   sheet has them) → **not** hovered (the R2 seam at work). Hover over an opaque
   pixel → hovered. Click on transparent → no action. Press and drag onto the
   button from outside → becomes pressed once you cross into an opaque pixel.
4. Un-skinned buttons elsewhere (settings, pause, the HUD End Turn, the
   building panel) must look **exactly** as before.
5. **REVERT THE HARDCODED SKIN BEFORE COMMITTING.** Plan line 238: the skin
   assignment is 10L-B's screen JSON. A committed hardcoded `skin="…"` literal
   is a phase-scope violation — `git diff` your final tree and confirm no
   `skin="…"` literal survives outside tests and docstrings.
6. Also confirm a full round still plays (build → end turn → wave) — you
   touched `hud.update`, `panel.hover` and the `main.py` update block, so a
   TypeError there would surface immediately.
