# Phase UR-3 — Editor screen-preview parity at 640×360

Source plan: `planning/UiResolutionPLAN.md` §"Phase UR-3" (lines 163–180).

**Assume UR-1 and UR-2 have already landed.** You branch off an umbrella that
already contains them: `editor/panels/viewport.py`'s `SCREEN_W`/`SCREEN_H` read
`data/display.json` (no literals), and that file now says 640×360. Do **not**
re-do any of UR-1's de-hardcoding, and do not touch the constant's definition or
its prose comments — see §3.

All `file:line` citations below are against the tree as it stands **before**
UR-1 lands (that is the tree I read). UR-1 rewrites lines 109–115 and four
prose references; every other citation is in a region UR-1 does not touch, so
the numbers drift by at most a couple of lines.

---

## 1. Behavioral spec (with citations)

### 1.1 What screen mode does today

Screen mode is a **fixed logical canvas, scale-to-fit, no zoom**
(`editor/panels/viewport.py:435-449`, docstring; `editor/panels/CLAUDE.md`
"Phase B4 — screen mode"). The fit math is four lines:

```python
# editor/panels/viewport.py:537-543
def _screen_scale_offset(self):
    w, h = max(1, self.width()), max(1, self.height())
    scale = min(w / SCREEN_W, h / SCREEN_H)
    scaled_w, scaled_h = SCREEN_W * scale, SCREEN_H * scale
    return scale, (w - scaled_w) / 2, (h - scaled_h) / 2
```

Everything downstream consumes that triple: `_to_screen_rect`
(`viewport.py:545-547`) converts each widget's LOGICAL rect into SCREEN
(widget-surface) pixels, and every submission, hit-test and drag runs on the
converted rect — `_submit_screen_items` (`viewport.py:1723-1746`),
`_submit_screen_background` (`:1748-1760`), `_submit_screen_widget`
(`:1762-1799`), `_hit_widget` (`:559-573`), `_hit_resize_handle` (`:575-588`),
`_screen_move` (`:641-659`, which divides the mouse delta back by `scale`).

The render target is the **widget-sized** surface: `_resize_surface`
(`viewport.py:1473-1481`) allocates `pygame.Surface((widget_w, widget_h))` and
`render_frame` flushes into it (`viewport.py:1531`).

**Verified facts about that arrangement:**

1. **It already upscales — there is no 1:1 clamp.** `min(w/SCREEN_W,
   h/SCREEN_H)` is unbounded above (`viewport.py:541`). At the old 1280×720
   canvas a docked viewport was almost always *narrower* than 1280, so `scale`
   sat below 1 and the preview was a downscale. At 640×360 the same panel gives
   `scale ≈ 1.4–2.0` and the preview becomes an **upscale at a non-integer
   factor** — the first time this code path has ever run above 1.0 in practice.
   (The exact factor depends on the designer's dock layout: **verify at
   implementation** with a live `py editor/main.py`.)

2. **Geometry scales but TEXT DOES NOT — this is the actual parity bug this
   phase exists to fix.** A widget's box is submitted in scaled screen pixels
   (`viewport.py:1769` `dest = self._to_screen_rect(...)`), but its label is
   submitted as a `HudText` carrying only a **font key**, never a scale
   (`viewport.py:1789-1791` → `editor/panels/_screen_primitives.py:34-44`), and
   the backend renders a `HudText` at the preset's absolute pixel size straight
   into the target (`engine/render/backend.py:172-173` → `_draw_hud_text`; the
   font presets are `engine/render/fonts.py`'s `_FONT_SPECS`, driven by
   `data/ui/fonts.json`).
   So the label/box size ratio in the editor is wrong by exactly `1/scale`:
   - Before (1280 canvas, `scale ≈ 0.7`): text drew ~1.4× too LARGE for its box.
   - After (640 canvas, `scale ≈ 1.4–2.0`): text draws ~1.4–2.0× too SMALL.
   The error does not merely persist across UR-2, it **inverts and roughly
   doubles**, and it lands on exactly the two things UR-2 changed (box sizes
   halved, font presets deliberately left alone — plan lines 63-67). A designer
   who trusts this preview will re-tune fonts that are already correct. That is
   the failure mode UR-3 must prevent.

3. **The game does the opposite thing, and that is the parity target.** The
   game renders the whole UI into a 640×360 surface and lets `pygame.SCALED`
   upscale the *finished surface* to the monitor (plan lines 21-26;
   `game/main.py:133`). Text and boxes therefore scale together, always. The
   editor scales the *geometry* and leaves the glyphs at 1:1 — a structurally
   different pipeline, which is why it can disagree.

4. **Letterboxing works, but is invisible.** The offsets at `viewport.py:543`
   centre the canvas correctly; the bars are just `BACKGROUND` fill
   (`viewport.py:1505`). At 640×360 in a wide dock the side bars get much
   larger, and there is nothing drawn to say where the canvas ends — a screen
   whose own background is dark reads as "the canvas is the whole panel". Low
   severity, cheap to fix (§2.4).

5. **There is NO grid in screen mode.** Grid lines are map-mode only:
   `self._grid_lines` is consumed inside `_submit_map_items`
   (`viewport.py:1560-1570`) and `set_grid_lines` (`:889-890`) is wired to the
   map palette. The plan's "grid becomes unreadably fine or coarse" concern
   (plan line 168) **does not apply** — there is nothing to retune. Do not add
   one in this phase; if designers ask for a screen-mode alignment grid it is a
   new feature, not resolution parity.

6. **The nudge step is 1 LOGICAL px** (`viewport.py:115` `NUDGE_STEP = 1`, used
   at `:688` in `_nudge_selected`, `:677-689`). At 640×360 one logical px is
   twice the fraction of the screen it used to be, and (because `scale > 1`) it
   moves the on-screen preview by ~1.4–2.0 *widget* pixels instead of ~0.7.
   Nothing is broken: 1 logical px is still the finest edit the data can
   express, and the game's own pixels are now 1 logical px too. **Keep it at 1**
   (plan line 174). Sub-pixel rects are not representable — `_screen_move`
   rounds (`viewport.py:656`) and `_resized_rect` rounds (`:603-604`) — so a
   sub-1 step would be a no-op.

7. **Editor chrome is already in SCREEN pixels and should stay there.**
   `HANDLE_PX = 8` (`viewport.py:114`) is a screen-pixel hit box
   (`_hit_resize_handle`, `:586`), matching the entity preview's stated rule
   that handles "never scale with zoom" (`viewport.py:104-105`). At `scale ≈
   1.7` a handle drawn in logical space would balloon; keep handles, the
   selection outline, the UH-4 caption and the E-37 placeholder text at fixed
   screen size.

### 1.2 Required behaviour after this phase

- **What the preview draws for a screen at 640×360 is what
  `py game/main.py` draws for the same screen, up to a uniform scale factor.**
  In particular the *ratio* of label height to widget-box height must match the
  game's, at any viewport size. (This is the observable exit criterion; §4's
  Quick Test is how it is judged.)
- Scale-to-fit and centring keep their current contract: the whole canvas is
  always visible, no zoom, no pan, recomputed from the widget's live size every
  frame (`viewport.py:1478-1481`).
- Hit-testing, drag-move, drag-resize and arrow-nudge keep working unchanged in
  logical-pixel terms; the mouse→logical mapping stays `_screen_scale_offset`'s
  inverse (`viewport.py:649-650`).
- `NUDGE_STEP` stays **1 logical px**.
- The E-37 no-defaults path still renders its placeholder and never raises
  (`viewport.py:1726-1735`).

---

## 2. Architecture plan (the minimal change)

### 2.1 Order of work — measure first

Before writing code, run `py editor/main.py`, select a UI-screen leaf, and look
at it next to the game. Record the observed `scale` (print
`_screen_scale_offset()` once, or read the widget size). Everything below is
predicated on §1.1's finding 2 being visible in practice; it is derived from
the code, not from a screenshot, so **verify it live first** and say so in your
report.

### 2.2 The change: render screen mode through a logical canvas surface

Adopt the game's pipeline shape instead of the geometry-scaling one — render
the screen at its **logical** size, then scale the finished surface once.

In `render_frame` (`viewport.py:1503-1534`), for the `in_screen_mode()` branch
only:

1. Build (or reuse a cached) `pygame.Surface((SCREEN_W, SCREEN_H))`, filled
   with `BACKGROUND`. Size it off the loaded constants — **never a literal** —
   and rebuild it when `(SCREEN_W, SCREEN_H)` differs from the cached surface's
   size, so a `display.json` change needs no other edit.
2. Submit the screen's content with `scale=1.0, ox=0, oy=0`. `_submit_screen_*`
   already take `(scale, ox, oy)` as parameters
   (`viewport.py:1723,1748,1762`) — pass the identity triple; no arithmetic in
   those functions changes.
3. `self._renderer.flush(canvas)` — `flush(target)` is explicitly
   target-agnostic (`engine/render/renderer.py:133-136`), so this is a
   supported use, not a new render path (ED-22 unaffected: still one
   `Renderer`, still `engine/render`).
4. `pygame.transform.scale` the canvas to `(SCREEN_W*scale, SCREEN_H*scale)`
   and blit it at `(ox, oy)` from `_screen_scale_offset()`. Use
   `transform.scale`, not `smoothscale` — the pixel-art rule in
   `engine/render/CLAUDE.md` ("Nine-slice" section) applies for the same
   reason.
5. Then submit **editor chrome** (selection outline + corner handles + UH-4
   caption + the E-37 placeholder) in SCREEN pixels as today and
   `flush(self._surface)` a second time. Two flushes are required because
   `flush` clears the queue; both go through the same `Renderer`.

Why this and not a smaller patch: text is the whole problem, and `HudText`
carries no scale field (`engine/render/hud.py`; `_draw_hud_text`
`backend.py:172-173`). The only alternatives are (a) picking a different font
preset per scale — a lie about which preset the game uses, and it can't
represent fractional factors; or (b) plumbing a scale factor through `HudText`
→ backend → font cache, which is an `engine/` change outside this phase's file
scope and touches every HUD consumer in the game. Scaling the finished surface
is what the game already does and costs one blit.

**What this does NOT change:** `_screen_scale_offset` keeps its signature and
its callers (hit-test/drag still map mouse→logical through it, unchanged);
`_to_screen_rect` is unchanged; the session/undo/selection model is untouched.

### 2.3 Scale policy above 1.0 — one decision, defaulted

`_screen_scale_offset` (`viewport.py:541`) has no upper clamp, so at 640×360 a
docked viewport gives a **fractional upscale** (~1.4–2.0), which under §2.2
means uneven pixel duplication across the whole preview — pixel art shown at
1.67× has some source pixels doubled and some not.

**Default (implement this):** when the fitted `scale` is ≥ 1.0, snap it DOWN to
the nearest integer (`math.floor`), i.e. draw at exactly 1×, 2×, 3×; below 1.0
leave the fractional downscale exactly as today. This mirrors the game
(`SCALED` is an exact integer multiple on 16:9 sizes — plan lines 237-239) and
is the honest answer to "what will a player see". Keep the snap in
`_screen_scale_offset` so hit-testing, dragging and the blit all agree by
construction — never snap at the blit only.

The cost: at `scale ≈ 1.9` the canvas is drawn at 1× and leaves a wide
letterbox. That is a taste call — see the open question in §4 and defer any
change to UR-5's eyeball pass rather than inventing a compromise here.

### 2.4 Letterbox visibility (small, recommended)

In the chrome pass, submit a 1px closed `HudLines` rectangle around the drawn
canvas (`ox, oy, SCREEN_W*scale, SCREEN_H*scale`) in a muted colour, so the
canvas edge is unambiguous at any fit. ED-22-clean — the same primitive the
selection outline already uses (`viewport.py:1743-1746`, `HudLines`).

### 2.5 `NUDGE_STEP`

No change. Leave the value at 1 (`viewport.py:115`). Its *comment* names the
old resolution and is **UR-1's edit, not yours** (§3).

---

## 3. File scope + shared-file contract

**You may edit exactly these:**

| File | What you own |
|---|---|
| `editor/panels/viewport.py` | The screen-mode **behaviour**: `render_frame`'s screen branch (`:1503-1534`), the logical-canvas surface + scaled blit, `_screen_scale_offset`'s scale POLICY (`:537-543`), the chrome pass, the letterbox outline. |
| `editor/panels/CLAUDE.md` | The "Phase B4 — screen mode" bullet's description of the render path (it currently says "fixed 1280×720 logical canvas … scaled-to-fit the widget (`_screen_scale_offset`)"). |
| `tools/tests/test_editor_viewport.py` | **Bare minimum**: one new test for §2.2/§2.3 (see §4). Do not restructure `TestViewportScreenMode`. |

The test file is outside the plan's "Files" list for UR-3 but is named in its
"Tests" line (plan line 177); it is the only place the exit gate can be
expressed. Touch nothing else in it.

**Everything else is out of scope**, including `engine/render/**`,
`editor/panels/_screen_primitives.py`, `data/**`, and `game/**`.

### Shared-file contract with UR-1 (`editor/panels/viewport.py`)

Both phases edit this file. The split is by REGION and there is no overlap if
you respect it:

- **UR-1 owns**, and UR-3 must not touch:
  - the `SCREEN_W, SCREEN_H` **definition** and its comment (`viewport.py:110`
    today; becomes a `data/display.json` read),
  - the four prose references naming a literal size (module docstring
    `:11`, `:25`; `set_screen_mode` docstring `:437`; `_screen_scale_offset`
    docstring `:538`) and the inline comment at `:237`,
  - `NUDGE_STEP`'s **comment** (`:115`).
- **UR-3 owns**: the BODY of `_screen_scale_offset` (`:540-543`), the
  screen-mode branch of `render_frame` (`:1506-1531`), any new private helper
  for the canvas surface, and the chrome/letterbox submissions. `NUDGE_STEP`'s
  **value** is UR-3's to change and this brief says: don't.

Practical rule for a clean merge: **read `SCREEN_W`/`SCREEN_H` exactly as they
are exposed after UR-1 and add no second read path** to `data/display.json`
(UR-1's brief bans one). If UR-1 turned them into a function or a lazily
initialised module value rather than module constants, adapt to whatever it
exposes — do not reintroduce module-level constants. If your canvas surface
needs the size once per frame, ask the same accessor every frame (it is a dict
lookup, not a file read; if UR-1 made it a file read, say so in your report
rather than caching around it).

`_screen_scale_offset`'s **signature and return shape** `(scale, ox, oy)` is a
contract for six other call sites in this file (`:564, :580, :647, :1724`) —
keep it.

---

## 4. Exit gate + Quick Test

### Gate

Per the router's test-suite policy, this phase's gate is the targeted Qt-tier
run — **not** the full suite, **not** `--affected`:

```bash
py -m pytest tools/tests/test_editor_viewport.py -x -q
```

Zero failures, zero unexpected skips. `TestPurity` (the layering guard) and
`TestViewportScreenMode` (`test_editor_viewport.py:551-675`) must stay green
untouched — note that `TestViewportScreenMode.make_viewport` resizes the panel
to `(SCREEN_W, SCREEN_H)` on purpose ("scale 1.0, offset 0 — trivial math",
`:570`), so those tests exercise the identity path and should be unaffected by
a correct implementation. *(Inferred: their fixture rects and click
coordinates are 1280-scale literals (`:92-96`, `:641-658`) but are delivered
straight to the widget by `QTest` and compared in the same space, so a 640
canvas at scale 1.0 keeps the math identical — **verify by running**, and if a
click-coordinate assertion does move, re-pin the fixture rather than changing
production behaviour to suit it.)*

**One new test, bare minimum** — a `_screen_scale_offset` contract test at
sizes the identity path does not cover:
- widget smaller than the canvas on one axis → `scale < 1`, canvas centred
  (offsets non-negative, `SCREEN_W*scale + 2*ox == widget_w` on the letterboxed
  axis);
- widget ≥ 2× the canvas → `scale` is an integer (§2.3).
No pixel assertions, no new fixture screens.

Do **not** run `py tools/testgate.py check` as part of this phase — the
umbrella orchestrator runs the full gate once after all UR phases land.

### Quick Test (in-game / in-editor, by eye)

1. `py game/main.py` → main menu → screenshot it. Open the building panel and
   the pause screen; screenshot those too.
2. `py editor/main.py` → selector ▸ **ui** ▸ **Screens** ▸ `main_menu`.
3. Compare against the screenshot: **the buttons' text must fill the same
   fraction of each button** as in the game, the widgets must sit in the same
   relative positions, and the canvas must be fully visible and centred with
   the letterbox bars clearly outside the drawn canvas edge.
4. Resize the editor window / drag the viewport dock wider and narrower: the
   canvas re-fits, stays centred, and nothing clips or overflows the panel.
5. Select a button, press ← four times: it moves 4 logical px, Ctrl+Z reverses
   them one at a time, and the on-screen motion is small but clearly visible.
6. Repeat step 2–3 for `building_panel` (pick the `unlock` view) — it is the
   only screen with per-view leaves (UH-2) and the densest layout.

Report what you exercised as a **live editor run** vs a static read, per
`editor/CLAUDE.md`'s "Verify before finishing".

### Open questions for the orchestrator / user

1. **Integer scale snapping above 1.0 (§2.3)** — default is snap-down to an
   integer (game-faithful, leaves a bigger letterbox). The alternative
   (fractional upscale, fills the panel, uneven pixels) is a designer-taste
   call. If the Quick Test makes the 1× view feel uselessly small, flag it for
   UR-5 rather than changing it silently.
2. **`NUDGE_STEP`** stays 1 per the plan (line 174). If a live playtest says a
   1px nudge is now too coarse *or* too fine, that is a UR-5 finding, not a
   UR-3 edit.
3. **No screen-mode grid exists** (§1.1 finding 5). If the plan's grid line
   meant "add one", that is a new feature and needs a decision before it is
   scoped anywhere.
