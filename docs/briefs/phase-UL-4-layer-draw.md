# Phase UL-4 — The game draws layers

Section S2 of `planning/UiLayeredWidgetsPLAN.md`. Runs AFTER UL-3 has landed
and merged into `ul-section-S2`. UL-3 adds `data/schemas/ui_screen.schema.json`'s
`layers` array and `engine/ui_layers.py` (the pure resolver) — this brief was
written before UL-3's code exists, so it specifies the CONTRACT this phase
relies on, not code already read.

## 1. Behavioral spec

**Goal (plan `planning/UiLayeredWidgetsPLAN.md:285-287`):** "A layer authored
in `data/ui/screens/<id>.json` appears in the game, in the right band, at the
right offset, following its owner when `layout()` moves it."

**D2 — offset geometry** (`planning/UiLayeredWidgetsPLAN.md:58-64`): a layer's
geometry is `offset: [dx, dy, w, h]` relative to the owner's POST-OVERRIDE
rect (never absolute) — `w`/`h` of `0` means "match the owner's". This is why
a layer must be resolved fresh every frame, after `ScreenSkinning.apply()` has
already moved the owner: resolving once at construction would detach the
instant `layout()` moved the widget.

**D3 — resolver contract, `engine/ui_layers.py`** (pure, pygame-free,
`planning/UiLayeredWidgetsPLAN.md:65-70`, S2 Publishes at
`planning/UiLayeredWidgetsPLAN.md:240-242`). By the time this phase's coder
runs, UL-3 guarantees:
- `resolve(layer_spec: dict, owner_rect: tuple, state: str = "idle") -> dict`
  — returns `{"rect": (x, y, w, h), "slot": ..., "text_id": ..., "label": ...,
  "font": ..., "align": ..., "color": ..., "text_color": ..., "tint": ...,
  "visible": ...}`, each key `None`/its default when the layer entry doesn't
  set it.
- `ordered(layers: list[dict], band: str) -> list[dict]` — filters to one band
  (`"under"` or `"over"`) and sorts by `z`; drops dangling/duplicate ids
  (never raises — matches the `editor/widget_tree.py` "hand-edited doc must
  never hang a paint handler" precedent cited at
  `planning/UiLayeredWidgetsPLAN.md:266-268`).
Do not use `validate_offsets` (schema-validation-time, not draw-time — not
this phase's concern).

**D4 — two submission bands, ONE call each**
(`planning/UiLayeredWidgetsPLAN.md:71-79`): the HUD pass has NO depth sort —
draw order IS submission order. Confirmed by the existing house rule
(`game/ui/CLAUDE.md`, "HUD submission order": `submit_hud`/`submit_panel`/
`submit_text` draw in call order, first = furthest back; house discipline
within one `submit()` is panel/background first, then buttons, then standalone
text). Each screen's `submit()` calls the layer submitter ONCE at the top
(`under` band) and ONCE at the end (`over` band); `z` orders layers WITHIN a
band. Accept and do not "fix": an `under` layer sits behind EVERYTHING on that
screen, not just behind its own owner — that is correct per D4's documented
trade-off, not a bug to route around.

**D5 — golden parity is the landing condition**
(`planning/UiLayeredWidgetsPLAN.md:80-83`, phase Tests at
`:299-302`). With NO `layers` authored anywhere — true of every shipped
`data/ui/screens/*.json` today — `submit_layers` must emit ZERO primitives, so
`tools/tests/test_ui_skinning.py`'s golden baselines and
`data/ui/screen_previews.json` stay byte-identical. Do not regenerate either
artifact. This must be the overwhelmingly common code path: a widget with no
`layers` key in its override produces zero calls, full stop.

**Existing precedent to mirror exactly** — `ScreenSkinning.submit_background`
(`game/ui/skinning.py:196-206`) is the SAME shape this phase is adding: one
call, no-op when the optional key is absent, emits a HUD primitive when
present. `submit_layers` is that pattern generalized to a per-widget list.
`ScreenSkinning.apply()` (`game/ui/skinning.py:143-160`) and its private
`_widgets_spec(screen_id)` helper (`game/ui/skinning.py:210-212`) are the
existing "read this screen's per-widget override dict, in memory, no disk I/O"
lookup — `submit_layers` reads the SAME `_widgets_spec(screen_id)[name]` dict,
just its `"layers"` key instead of the rect/skin keys `apply()` reads.

**Text resolution for a `text_id`/`label` layer** — mirror
`submit_label`'s existing text-resolution idiom (`game/ui/widgets.py:241-280`,
specifically the `text_id`-then-`label` fallback at `widgets.py:265-270`):
`text = strings.T(text_id) if text_id else (label or "")`; skip the layer
(draw nothing) if the resolved string is empty. `game/ui/strings.py` has no
imports of its own (verified — zero import lines), so `from . import strings`
in `skinning.py` introduces no circular import with `widgets.py` (which
already does `from . import strings` and separately `from .skinning import
is_visible`).

**HUD primitive dataclasses** (`engine/render`, already the sanctioned import
`game/ui/skinning.py:31` makes for `HudRect`/`HudSprite`, and
`game/ui/widgets.py:21` additionally imports `HudText` from the same module —
add `HudText` to skinning.py's existing `from engine.render import HudRect,
HudSprite` line):
- `HudRect(rect: tuple, color: tuple, border_radius: int = 0, width: int = 0)`
- `HudText(text: str, pos: tuple, font_key: str, color: tuple, align: str = "left")`
- `HudSprite(slot_key, dest: tuple, size: tuple, animation=..., anim_time_ms=..., tint=..., crop=..., hidden_frames=...)`
  — positional order `(slot_key, dest, size)`, then keyword `tint=`.

## 2. Architecture plan

### 2a. `game/ui/skinning.py` — two additions

**`ScreenSkinning.submit_layers`**, a public method alongside
`submit_background`:

```python
def submit_layers(self, renderer, screen_id: str, ids: Dict[str, Any],
                  band: str, state_of) -> None:
    """Draw every widget's ``band``-side layer stack — ONE call per screen
    per band (D4), at the top (``"under"``) or end (``"over"``) of
    ``submit()``. ``ids``: the same ``{name: (kind, widget)}`` dict every
    screen already builds. ``state_of``: a CALLABLE ``widget -> str``
    (§ state_of below) — resolved per-widget, not once per screen, because a
    future phase (UL-5) makes it vary per widget.

    A widget with no ``layers`` entry in this screen's override produces
    ZERO calls — the D5 parity case, and the overwhelmingly common path
    today (every shipped screen has no ``layers`` authored anywhere)."""
    widgets_spec = self._widgets_spec(screen_id)
    if not widgets_spec:
        return
    for name, (_kind, widget) in ids.items():
        spec = widgets_spec.get(name)
        layer_list = (spec or {}).get("layers") or []
        if not layer_list:
            continue
        for entry in ui_layers.ordered(layer_list, band):
            resolved = ui_layers.resolve(entry, widget.rect, state_of(widget))
            if resolved.get("visible") is False:
                continue
            self._submit_one_layer(renderer, resolved)
```

Factor the primitive emission into a small private helper
(`_submit_one_layer` or inline — coder's call, keep it short) implementing
this PRECEDENCE, checked in this exact order, first match wins, else skip
(nothing to draw):
1. `resolved["slot"]` is truthy -> `HudSprite(slot, (x, y), (w, h), tint=resolved.get("tint"))`
   where `(x, y, w, h) = resolved["rect"]`.
2. elif `resolved["text_id"]` or `resolved["label"]` truthy -> resolve text via
   `strings.T(text_id)` (fallback `label`, per §1 above), skip if the resolved
   string is empty; else `HudText(text, (x, y), resolved.get("font") or
   <fallback>, resolved.get("text_color") or <fallback>, align=resolved.get("align") or "left")`.
   For the font/color fallback when the layer doesn't set one, use the SAME
   values `apply()`/the widget's own defaults would use for a label holder —
   check `Label(...)`'s defaults (`game/ui/widgets.py` around its `Label`
   factory, near line 220) rather than inventing new fallback constants.
3. elif `resolved["color"]` truthy -> `HudRect((x, y, w, h), resolved["color"])`.
4. else -> skip, draw nothing.

Document this precedence as a docstring on the helper — it is a design
decision (a layer picks ONE role), not an accident of iteration order.

**`state_of` stub** — an INSTANCE METHOD on `ScreenSkinning` (correction —
NOT a top-level function: every call site below reads `self.skinning.state_of`,
and `self.skinning` is a `ScreenSkinning` *instance* per the existing
`self.skinning.apply(...)`/`self.skinning.submit_background(...)` pattern
this whole file already uses, so `state_of` must be bound the same way
`submit_layers` is):

```python
    def state_of(self, widget) -> str:
        """Per-widget draw state for layer/appearance resolution (D9). THIS
        PHASE (UL-4) always returns ``"idle"`` — a placeholder. UL-5 (landing
        right after this phase, same section) replaces ONLY this method's
        BODY with real per-widget state resolution (hover/pressed/disabled).
        Every call site passes this method BY REFERENCE
        (``self.skinning.state_of``, a bound method), never a hardcoded
        ``"idle"`` literal, so UL-5's diff is a single-method-body change,
        not 14 call-site edits."""
        return "idle"
```

**This is a hard contract for this phase**: no screen's `submit()` may
hardcode the string `"idle"` at its `submit_layers(...)` call site. Always
pass `self.skinning.state_of` (the bound method) as the `state_of` argument —
`submit_layers`'s own body calls it as `state_of(widget)`, which works
correctly for a bound method (no manual `self` needed at the call site inside
`submit_layers`).

### 2b. Per-screen `submit()` — two calls, `under` first / `over` last

The general shape, per screen:
```python
self.skinning.submit_layers(renderer, self.screen_id, self.ids, "under", self.skinning.state_of)
... existing submit() body unchanged ...
self.skinning.submit_layers(renderer, self.screen_id, self.ids, "over", self.skinning.state_of)
```
Placement rule: the `under` call goes as early as possible in `submit()` —
literally the first statement, or immediately after an existing
`self.skinning.submit_background(...)` call if the screen already opens with
one — but it must sit AFTER any earlier statement that (a) builds `self.ids`
(some screens build `ids` fresh inside `submit()`, see game_log.py below) or
(b) is a genuine "nothing to draw" early-return guard (some screens return
before doing any work when invisible — see enemy_intro.py below). Do not draw
layers for a screen that itself decided not to draw this frame. The `over`
call goes as the LAST statement, after every other draw call in `submit()`.

**Confirmed per-file exceptions to the plain "first/last statement" rule**
(verify each against the file before editing — do not assume the general
shape applies verbatim):
- `game/ui/enemy_intro.py:168-170` — `submit()` opens with
  `if not self.visible or self.entry is None: return`. Put the `under` call
  AFTER this guard, not before it.
- `game/ui/game_log.py:74-79` — `submit()` builds `self.ids` itself
  (`self.ids = {"log": (...)}`, line 76) then calls `self.skinning.apply(...)`
  (line 77), then guards `if not self._style.visible: return` (line 78). Put
  the `under` call AFTER line 78's guard (so `self.ids` exists and the guard
  has already run).
- `game/ui/building_ui.py` — `SCREEN_ID = "building_panel"` (line 81) is
  shared by THREE separate classes, each with its own `submit()` and its own
  `self.ids`: `ConstructPreview.submit()` (~line 441), `MovePreview.submit()`
  (~line 634), and `BuildingUI.submit()` (~line 1995). Add the two calls to
  ALL THREE `submit()` methods (each against its own `self.ids`), not just
  one. In `BuildingUI.submit()`, place the `under` call right after
  `self.skinning.apply(self.screen_id, self.ids)` / the existing
  `self.skinning.submit_background(...)` call (~lines 2035-2038) and AFTER the
  `if not self.visible: return` guard at ~line 2025-2026 (world-space overlay
  drawing above that guard is unrelated to widget layers and must stay
  untouched). `ConstructPreview`/`MovePreview` call `self.skinning.apply()`
  elsewhere (layout-time, not inside `submit()`); their `under`/`over` calls
  are simply first/last statements of their own `submit()`.
- `game/ui/overlays.py` — `SCREEN_ID = "overlays"` (line 65); `self.ids` is
  built at layout time (~line 170), NOT inside `submit()`
  (`submit(self, renderer, tilemap, scene, window)`, line 263) — a world-space
  overlay screen with no `submit_background` call. Its `under`/`over` calls
  are simply first/last statements of `submit()`, reading the already-built
  `self.ids`.
- Every other screen (`add_name`, `boss_cutscene`, `credits`, `game_over`,
  `hud`, `levelup`, `main_menu`, `pause`, `settings`, `cheat_menu`) opens
  `submit()` with `self.skinning.submit_background(renderer, self.screen_id,
  view_w, view_h)` as (or near) its first statement — put the `under` call
  immediately after that line; the `over` call as the last statement of
  `submit()`.

## 3. File scope + shared-file contract

**Modified — `game/ui/skinning.py`.** Add `HudText` to the existing
`from engine.render import HudRect, HudSprite` import; add
`from . import strings` and `from engine import ui_layers` (module path per
UL-3's contract, §1 above — confirm the exact import path UL-3 actually used
once its code has landed in this tree; `from engine import ui_layers` is the
expected shape per the plan's `engine/ui_layers.py` naming). Add
`submit_layers` and `state_of` as `ScreenSkinning` INSTANCE METHODS
(corrected — not top-level functions; see §2a), as specified there.

**Shared-file contract — UL-5 touches this same file next.** UL-5 (same
section, lands right after this phase) replaces ONLY `state_of`'s BODY with
real per-widget state resolution. This phase's `submit_layers` implementation
and `state_of`'s SIGNATURE and NAME must not need to change for that — every
call site already routes through `self.skinning.state_of` (a bound method) by
reference (§2a), so UL-5's diff is a single-method-body change, not 14
call-site edits. Do not inline the `"idle"` return anywhere else, and do not
rename `state_of` or turn it into a bare module-level function.

**Modified — all 14 exported screens' `submit()`** (list confirmed against
`tools/export_ui_layouts.py:52-56`'s `SCREEN_IDS`; two calls each per §2b):

| screen_id | File |
|---|---|
| `add_name` | `game/ui/add_name.py` |
| `boss_cutscene` | `game/ui/boss_cutscene.py` |
| `building_panel` | `game/ui/building_ui.py` (three classes: `ConstructPreview`, `MovePreview`, `BuildingUI` — all three, see §2b) |
| `cheat_menu` | `game/ui/cheat_menu.py` |
| `credits` | `game/ui/credits.py` |
| `enemy_intro` | `game/ui/enemy_intro.py` |
| `game_log` | `game/ui/game_log.py` |
| `game_over` | `game/ui/game_over.py` |
| `hud` | `game/ui/hud.py` |
| `levelup` | `game/ui/levelup.py` |
| `main_menu` | `game/ui/main_menu.py` |
| `overlays` | `game/ui/overlays.py` |
| `pause` | `game/ui/pause.py` |
| `settings` | `game/ui/settings.py` |

**New — `tools/tests/test_ui_layer_draw.py`.** Build a fixture screen doc via
`ScreenSkinning.from_overrides(...)` (disk-free constructor,
`game/ui/skinning.py:119-130`) with one `under` and one `over` layer entry on
a fake `ids` entry (a `SimpleNamespace` with a `.rect` is enough — match
whatever minimal shape `widget.rect` needs, do not build a real widget
class). Fake the renderer with the SAME `RecordingRenderer` pattern
`tools/tests/test_ui_skinning.py:65-74` uses (`submit_hud(item)` appends to a
list) — copy that class, do not invent a new fake. Assertions:
1. `submit_layers(..., "under", lambda w: "idle")` then `submit_layers(...,
   "over", lambda w: "idle")` against the fixture produces the expected
   primitives, in the expected order (under-band items before over-band, `z`
   order honored within a band).
2. A second test: move the owner via `apply()` (an override `rect` on the
   widget), then call `submit_layers` — assert the layer's resolved rect
   reflects the owner's NEW position (D2, "follows its owner").
`tools/tests/test_ui_skinning.py`'s golden baselines MUST be byte-unchanged
(D5) — run it explicitly as part of the exit gate below, not just incidentally
included, to prove this phase adds zero visual output when no `layers` are
authored.

**Not in scope for this phase:** `data/schemas/ui_screen.schema.json`,
`engine/ui_layers.py` (both UL-3's, already landed and merged — read, never
edit), and `state_of`'s real logic (UL-5's).

## 4. Exit gate + Quick Test

```
py tools/smoke.py
py -m pytest tools/tests/test_ui_layer_draw.py tools/tests/test_ui_skinning.py -q
```

**Quick Test (in game, run by the orchestrator/user, not the coder):**
hand-author one `under` layer on `hud.love_text` pointing at an imported `ui`
slot in `data/ui/screens/hud.json`, run `py game/main.py`, confirm the
background sits behind the love number and moves with it when the widget's
`rect` override is changed.
