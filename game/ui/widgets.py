"""Shared UI widgets + palette (Phase 9G).

``game/ui`` is pure logic: it emits the engine HUD primitives
(``HudRect``/``HudText``/``HudSprite``/``HudLines`` from ``engine/render/hud.py``)
via ``renderer.submit_hud`` and measures strings with
``engine.render.fonts.TextMetrics`` — it NEVER imports pygame (a purity test
enforces this). Colors mirror the prototype's ``src/core/constants.py`` palette
verbatim; hit-testing is plain rect math so it is fully headless-testable.

The C_* palette (UH-6, D5) is DATA-BACKED: ``data/ui/palette.json`` ships the
same values as committed content, loaded once at boot (``game/main.py``) and
applied via ``configure_palette`` — the literals below are the unconfigured
fallback (bare test/tool construction stays deterministic; a pin test proves
they equal the stock file). Every consumer reads ``widgets.C_GOLD`` etc. via
attribute access, never ``from .widgets import C_GOLD`` (an early binding a
later ``configure_palette`` rebind cannot reach) — see ``game/ui/CLAUDE.md``.
"""
import math
from types import SimpleNamespace

from engine.render import HudLines, HudRect, HudSprite, HudText, RenderItem
from engine.render.fonts import TextMetrics, layout_h

from . import sound          # SD-6: the pure UI-sound seam (leaf, no cycle)
from . import strings
from .skinning import is_visible

_METRICS = TextMetrics()

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
    HudSprite wants (10L-A). ONE conversion, so no screen re-derives it.
    ``round``, not ``int``: repeated float dt accumulation lands a hair under
    the exact millisecond (10 * 0.1 == 0.9999999999999999) and truncation
    would silently eat a frame's worth of ms — the same class of drift
    Sec 1.5 rules out for per-frame accumulation, just at the read instead."""
    return round(clock_s * 1000)

# -- palette (prototype constants.py, verbatim RGB) -------------------------
C_GOLD = (255, 200, 50)
C_RED = (210, 55, 55)
C_HP_GREEN = (55, 195, 55)
C_HP_RED = (200, 55, 55)
C_GREEN_STAT = (80, 210, 80)
C_UI_PANEL = (42, 34, 68)
C_UI_BORDER = (80, 65, 120)
C_UI_BTN = (75, 60, 115)
C_UI_BTN_HOVER = (110, 90, 160)
C_UI_BTN_ACTIVE = (60, 140, 60)
C_UI_BTN_DISABLED = (50, 45, 70)
C_UI_TEXT = (235, 225, 195)
C_UI_TEXT_DIM = (150, 140, 120)
# VfxAuthoringPLAN VA-5 DELETED five highlight colour constants from this
# block — C_HIGHLIGHT, C_HIGHLIGHT2, C_RANGE_HIGHLIGHT (which were palette
# keys) and C_MOVE_HIGHLIGHT, C_TUTORIAL_HIGHLIGHT (which were bare code
# constants). All five are now `procedural.highlights.*` in
# data/balancing/vfx.json, read through `highlight_color(event)` below, so
# each has exactly one home (G-7/D8) and every one of them is editable and
# previewable in the VFX editor like any other effect.
# Construct panel: a tile that already hosted a Painter and paid out, so it
# can never host another one. A plain code constant, NOT palette-data-backed —
# it is not a highlight a designer authors, it is a "this is barred" grey.
C_PAINTER_USED = (110, 110, 110)     # grey — barred painter tile
C_PANEL_STONE = (40, 32, 58)         # HUD "stone pill" body
C_PANEL_INSET = (150, 135, 185)
C_PURPLE = (168, 105, 222)           # the house purple (matches the XP bar fill)

# data/ui/palette.json's keys, in the same order as the C_* block above (UH-6,
# D5) — snake_case with the C_ prefix dropped. configure_palette's key ->
# attribute mapping is the mechanical `"C_" + key.upper()`.
_PALETTE_KEYS = (
    "gold", "red", "hp_green", "hp_red", "green_stat", "ui_panel",
    "ui_border", "ui_btn", "ui_btn_hover", "ui_btn_active", "ui_btn_disabled",
    "ui_text", "ui_text_dim",
    "panel_stone", "panel_inset", "purple",
)


def configure_palette(doc):
    """Rebind every C_* module constant IN PLACE from a loaded
    ``data/ui/palette.json`` doc (D5/UH-6) — mirrors
    ``engine.render.fonts.configure_fonts``: the host (``game/main.py``)
    loads + schema-validates the file and passes the plain dict, so this
    module stays data-dir-free (bare construction — tests/tools — never
    needs a ``data/`` tree). Fails loud on an unknown/missing key (same
    "no silent break" argument as ``configure_fonts`` — a renamed/dropped
    key would otherwise leave some C_* constant silently un-rebound).

    Every consumer reads these through ``widgets.C_*`` attribute access
    (never ``from .widgets import C_GOLD``, an early binding a later
    rebind here cannot reach) — see ``game/ui/CLAUDE.md``."""
    unknown = set(doc) - set(_PALETTE_KEYS)
    missing = set(_PALETTE_KEYS) - set(doc)
    if unknown or missing:
        raise ValueError(
            f"palette.json key set mismatch: missing {sorted(missing)}, "
            f"unknown {sorted(unknown)}")
    for key, value in doc.items():
        globals()["C_" + key.upper()] = tuple(value)


# -- 10I: tile-condition labels + colours (prototype building_ui.py:23-27) --
# Shared by the panel badges/tooltips (building_ui) and the map overlays so
# the two surfaces cannot drift. Keyed by the TileCondition NAME (a plain
# string) so this module needs no game.map import. Colors stay code-owned
# (data/ui/palette.json's scope is the C_* block only, D5); the LABEL TEXT
# is Phase C's string-table content instead (data/ui/strings.json's
# widgets.condition.* ids).
_COND_COLORS = {
    "GRASS": (100, 180, 80),
    "MOUNTAIN": (160, 130, 90),
    "POND": (80, 160, 220),
    "FOREST": (70, 160, 70),
}
_COND_LABEL_IDS = {
    "GRASS": "widgets.condition.grass",
    "MOUNTAIN": "widgets.condition.mountain",
    "POND": "widgets.condition.pond",
    "FOREST": "widgets.condition.forest",
}


def cond_label(name):
    """(label, color) for a TileCondition NAME (10I). A FUNCTION, not a
    dict literal (Phase C: same reasoning as hud.py's ``_phase_color`` —
    a dict built at IMPORT time would freeze the pre-``configure_strings``
    fallback text and never see a later rebind; this resolves fresh via
    ``strings.T()`` on every call)."""
    return strings.T(_COND_LABEL_IDS[name]), _COND_COLORS[name]
# -- /10I --


def text_size(text, font_key, family=None):
    """(w, h) of ``text`` in the given font — pure metric, no blit.

    ``family`` (UH-Font-B) measures in a font family other than the active
    one. Legal here because these are DRAW-TIME-ONLY metrics (word wrap, a
    hover hint's width): nothing they produce lands in a stored rect or a
    captured stream, so they may track the real font. Layout math must keep
    using ``layout_h``, which has no family axis on purpose."""
    return _METRICS.size(text, font_key, family)


def text_h(font_key, family=None):
    return _METRICS.size("Ag", font_key, family)[1]


def pretty(slug):
    """``'stone_thrower'`` -> ``'Stone Thrower'`` (building display names)."""
    return slug.replace("_", " ").title()


def wrap_text(text, font_key, max_w, max_lines=None, family=None):
    """Greedy word wrap to ``max_w`` pixels. A word longer than the line is not
    broken (it just overhangs). Truncates to ``max_lines`` when given."""
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}" if current else word
        if current and text_size(trial, font_key, family)[0] > max_w:
            lines.append(current)
            current = word
            if max_lines is not None and len(lines) == max_lines:
                return lines
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def contains(rect, mx, my):
    x, y, w, h = rect
    return x <= mx < x + w and y <= my < y + h


def click(btn, mx, my):
    """``True`` when ``btn`` consumed this click — and the click sound is
    emitted exactly once (SD-6).

    The ROUTED-click twin of ``Button.hit``. ``hit`` stays a pure probe: it is
    called speculatively (``main.py``'s "am I over UI?" test, the tutorial's
    panel-click gate) and twice per click on the HUD, so a sound hook inside it
    would fire on non-clicks and double-fire on real ones. Screens whose
    ``hit()`` routes a click therefore call THIS instead.

    Visibility and ``enabled`` are honoured (``Button.hit`` already gates on
    ``enabled``), so an invisible/disabled button and empty space are silent.
    """
    if not is_visible(btn) or not btn.hit(mx, my):
        return False
    sound.play_click(btn)
    return True


def submit_panel(renderer, rect, *, fill=None, border=None, skin=None,
                 tint=None, anim_ms=0, animation="idle"):
    """A filled, bordered panel body. With ``skin`` (a slot key, 10L-A) the
    two flat rects are replaced by one nine-sliced HudSprite covering the same
    rect; ``fill``/``border`` are then ignored and ``tint`` (D6/UH-6 — the
    sheet-multiply color, ``None`` = unchanged) rides along instead. Panels
    carry no interaction state, so they animate the ``idle`` row unless the
    caller names another: a panel holder that owns a ``_state()`` (the three
    HUD life counters) passes its own row in, which is the ONLY way a
    panel-kind widget reaches the ``pressed``/``disabled`` sheet rows.
    Panels are not click targets — no hit-test wiring.

    ``fill``/``border`` default to ``None`` and resolve to the CURRENT
    ``C_UI_PANEL``/``C_UI_BORDER`` inside the body, never as a def-time
    default (UH-6: a default-arg literal is evaluated once at import and
    would never see a later ``configure_palette`` rebind — the one trap
    that survives switching every OTHER reference to attribute access)."""
    if fill is None:
        fill = C_UI_PANEL
    if border is None:
        border = C_UI_BORDER
    if skin:
        x, y, w, h = rect
        renderer.submit_hud(HudSprite(skin, (x, y), (w, h),
                                      animation=animation,
                                      anim_time_ms=anim_ms,
                                      tint=tint))
        return
    renderer.submit_hud(HudRect(rect, fill))
    renderer.submit_hud(HudRect(rect, border, width=1))


def announce_top_y(view_h):
    """Screen y of the TOP of the centred announce banner's first line
    (``effects.submit_announce``'s two ``xl`` lines: the boss banner and the
    "YOU / LOST 1 LIFE" banner). ONE home for that geometry, so the HUD's
    centred life icon cannot drift away from the text it hangs under.

    ``layout_h``, never a live measurement — this reaches a drawn position on
    every frame of the lost-life flight (game/ui/CLAUDE.md)."""
    return view_h // 2 - layout_h("xl") - 6


def announce_bottom_y(view_h):
    """Screen y of the BOTTOM of that banner's SECOND line — i.e. the first
    free row under the announce text. ``announce_top_y``'s companion; the two
    are the only places the banner's vertical layout is stated."""
    return announce_top_y(view_h) + 2 * layout_h("xl") + 8


def submit_text(renderer, text, pos, font_key, color, align="left",
                family=None):
    renderer.submit_hud(HudText(text, pos, font_key, color, align=align,
                                family=family))


def submit_centered(renderer, text, cx, cy, font_key, color, family=None):
    """Text centred horizontally on ``cx`` with its top at ``cy``."""
    renderer.submit_hud(HudText(text, (cx, cy), font_key, color,
                                align="center", family=family))


def label_holder(rect=(0, 0, 0, 0), *, text_id=None, label="", font_key="md",
                 font_family=None, text_color=None, align="left",
                 visible=True):
    """A ``label``-kind widget holder for an id'd piece of text (UT-1).

    The ``SimpleNamespace`` shadow object every screen already builds by hand
    for its static titles, with the two UT-1 fields folded in — written once
    here so the ~90 converted call sites do not each restate the field list.

    ``rect`` follows the text-label convention (``game/ui/CLAUDE.md``): an
    ``(x, y, 0, 0)`` ANCHOR POINT, W/H nominal ``0``, computed and STORED in
    ``layout()`` so a rect override moves the text and the exporter reads a
    real position.

    ``text_id`` names a ``data/ui/strings.json`` key: the text is resolved
    through ``T()`` at draw time, so the template is designer-editable and the
    live values stay code-owned. A holder with no ``text_id`` falls back to its
    static ``label`` — the pre-UT-1 behaviour, unchanged.

    ``font_family`` (UH-Font-B) is the font FAMILY the holder draws in — a
    ``data/fonts/font_manifest.json`` entry id, orthogonal to ``font_key``'s
    size/bold preset. ``None`` inherits the active family, so every holder
    that predates the per-text axis is unchanged. Like every other field
    here it is designer-ownable: ``ScreenSkinning.apply`` setattrs a
    ``font_family`` override straight onto the holder.
    """
    return SimpleNamespace(rect=rect, text_id=text_id, label=label,
                           font_key=font_key, font_family=font_family,
                           text_color=text_color,
                           align=align, visible=visible)


def _state_patch(widget, state):
    """The per-state appearance patch off ``widget.states`` (UL-5), or ``{}``.

    ``states`` reaches a widget through ``ScreenSkinning.apply``'s generic
    setattr loop the same way ``skin``/``tint`` do — a widget whose screen doc
    never named it simply has no attribute, hence the ``getattr``.

    The D9 fallback ladder, identical to ``engine.ui_layers``' own: the
    resolved state key wins when PRESENT (an explicitly-authored empty patch
    means "this state looks like the base"), an ABSENT key falls back to
    ``"idle"``, and an absent/empty ``states`` means no patch at all — which
    is what keeps an un-authored widget byte-identical to pre-UL-5.
    """
    states = getattr(widget, "states", None) or {}
    if not isinstance(states, dict):
        return {}
    if state in states:
        return states[state] or {}
    return states.get("idle") or {}


def _state_offset(patch):
    """A state patch's ``offset`` as ``(dx, dy, dw, dh)`` — a DRAW-TIME nudge.

    ``[dx, dy]`` moves without resizing (``dw``/``dh`` 0); ``[dx, dy, dw,
    dh]`` also resizes. Relative to the widget's OWN rect, never an absolute
    rect, and never written back onto it: ``self.rect`` stays the hit-test
    truth (``Button._surface_hit``/``hit`` read it directly the very next
    frame and know nothing about a state nudge). Anything malformed degrades
    to no nudge rather than raising — ``engine.ui_layers.validate_offsets``'
    rule, applied at the widget level.
    """
    value = patch.get("offset")
    if not isinstance(value, (list, tuple)) or len(value) not in (2, 4):
        return (0, 0, 0, 0)
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in value):
        return (0, 0, 0, 0)
    return (value[0], value[1], 0, 0) if len(value) == 2 else tuple(value)


def submit_label(renderer, holder, *, text=None, color=None, align=None, **fmt):
    """Draw an id'd label holder (UT-1) — THE idiom for text a screen names in
    its ``ids`` dict.

    Text comes from ``T(holder.text_id, **fmt)`` when the holder carries a
    ``text_id``, else from its static ``holder.label``. Geometry, font, colour,
    alignment and visibility all come off the holder, i.e. from whatever
    ``ScreenSkinning.apply()`` last wrote onto it — which is why this must be
    called AFTER ``apply()``, like every other override-reading draw.

    ``text`` bypasses both for the handful of runs whose content is authored
    at RUNTIME rather than templated — a building's player-typed name, a live
    text-entry buffer. Those still get an id'd holder (so their position,
    font and colour are designer-owned); only the characters are not the
    designer's to write.

    ``color`` is the code-computed fallback used when no ``text_color``
    override is set (the "``None`` means compute" convention every other
    override key already follows); ``align`` likewise overrides the holder's
    own for a call site that varies it. An empty resolved string draws
    nothing — a hidden or unset label is a no-op, never a blank ``HudText``.
    """
    if not is_visible(holder):
        return
    text_id = getattr(holder, "text_id", None)
    if text is None:
        if text_id:
            text = strings.T(text_id, **fmt)
        else:
            text = getattr(holder, "label", "") or ""
    if not text:
        return
    tcol = getattr(holder, "text_color", None)
    if tcol is None:
        tcol = color if color is not None else C_UI_TEXT
    # UL-5: a plain holder has no ``_state()``, so its state is always
    # "idle" (``ScreenSkinning.state_of``'s rule) — an "idle" patch is the
    # only one a label/panel/backdrop can ever select. The patch is more
    # specific than the holder's own static ``text_color``, so it wins over
    # it; both spellings are accepted (``text_color`` is the holder's own
    # attribute name, ``color`` this function's parameter name). It does NOT
    # win over an explicit call-site ``color=``, mirroring ``Button.submit``'s
    # ``text_color=`` rule: a caller passing a computed semantic colour (the
    # ~13 ``C_UI_TEXT_DIM``/``C_GOLD`` sites in building_ui/settings/levelup/
    # boss_cutscene) is being more specific than the screen doc.
    patch = _state_patch(holder, "idle")
    pcol = patch.get("text_color", patch.get("color"))
    if color is None and pcol is not None:
        tcol = tuple(pcol)
    if align is None:
        align = getattr(holder, "align", "left") or "left"
    rect = holder.rect
    # Draw-time nudge only: ``holder.rect`` is the exporter's/editor's stored
    # truth and is never rewritten from here (dw/dh are meaningless for a
    # text anchor, whose w/h are nominal 0 — see game/ui/CLAUDE.md).
    dx, dy, _dw, _dh = _state_offset(patch)
    renderer.submit_hud(HudText(text, (rect[0] + dx, rect[1] + dy),
                                holder.font_key, tcol, align=align,
                                family=getattr(holder, "font_family", None)))


# ===========================================================================
# Tile highlights are DATA (VfxAuthoringPLAN VA-5)
# ===========================================================================
# The seven continuous tile highlights are effects now: colour, outline width
# and fill alpha come from `data/balancing/vfx.json`'s `procedural.highlights`,
# and each can be replaced outright by an imported `vfx_<event>` spritesheet
# through its `triggers` row.
#
# They live HERE rather than behind `FloaterManager` because they are drawn by
# `BuildingUI.submit` and by the host, neither of which holds the FX manager —
# and because this module already owns `submit_tile_diamond`, i.e. the one
# place a tile highlight has ever been drawn. The configure/fallback shape is
# `configure_palette`'s, deliberately: these values were palette keys until
# this phase, so the mechanism that replaces them is the one they came from.
#
# The literals below are the UNCONFIGURED FALLBACK (bare test/tool
# construction), equal to the pre-VA-5 constants; `test_highlight_data.py`
# pins them against the committed JSON so the two cannot drift.
_HIGHLIGHTS = {
    "tile_selected": {"color": (255, 230, 60), "border_width": 2, "fill_alpha": 0},
    "section_2x2": {"color": (255, 180, 60), "border_width": 2, "fill_alpha": 0},
    "attack_range": {"color": (180, 40, 40), "border_width": 2, "fill_alpha": 0},
    "move_target": {"color": (80, 200, 255), "border_width": 2, "fill_alpha": 0},
    "wall_edge": {"color": (255, 230, 60), "border_width": 4, "fill_alpha": 0},
    "upgrade_batch": {"color": (255, 230, 60), "border_width": 2, "fill_alpha": 0},
    "tutorial_highlight": {"color": (255, 255, 255), "border_width": 2,
                           "fill_alpha": 0},
}
# event -> (sprite_slot, draw_in_front), from the same doc's `triggers`.
_HIGHLIGHT_TRIGGERS = {name: ("", True) for name in _HIGHLIGHTS}

# The tile-buying tutorial topic's pulse/glow overlay on TOP of
# _HIGHLIGHTS["tutorial_highlight"]'s base colour/width (VfxAuthoringPLAN
# VA-5's configure/fallback shape, applied to a second, independent block —
# see tutorial_pulse_style below). The literals are the UNCONFIGURED
# FALLBACK, equal to the committed `procedural.tutorial_highlight_pulse`;
# `test_highlight_data.py` pins them against it.
_TUTORIAL_PULSE = {"alpha_min": 140, "alpha_max": 255,
                   "width_min": 2, "width_max": 4, "pulse_period_s": 0.8}


def configure_highlights(vfx_doc):
    """Rebind the highlight params + their trigger bindings from a loaded,
    schema-validated ``data/balancing/vfx.json`` (the host loads it; this
    module stays data-dir-free, exactly like ``configure_palette``).

    Fails loud on a key-set mismatch, for `configure_palette`'s reason: a
    renamed or dropped highlight would otherwise leave one silently on its
    fallback, which looks like "the designer's edit did nothing".
    """
    highlights = vfx_doc["procedural"]["highlights"]
    unknown = set(highlights) - set(_HIGHLIGHTS)
    missing = set(_HIGHLIGHTS) - set(highlights)
    if unknown or missing:
        raise ValueError(
            f"vfx.json procedural.highlights key set mismatch: missing "
            f"{sorted(missing)}, unknown {sorted(unknown)}")
    for name, block in highlights.items():
        _HIGHLIGHTS[name] = {"color": tuple(block["color"]),
                             "border_width": block["border_width"],
                             "fill_alpha": block["fill_alpha"]}
    triggers = vfx_doc.get("triggers", {})
    for name in _HIGHLIGHTS:
        row = triggers.get(name)
        if row is not None:
            _HIGHLIGHT_TRIGGERS[name] = (row["sprite_slot"],
                                         row["draw_in_front"])
    pulse = vfx_doc["procedural"]["tutorial_highlight_pulse"]
    _TUTORIAL_PULSE["alpha_min"] = pulse["alpha_min"]
    _TUTORIAL_PULSE["alpha_max"] = pulse["alpha_max"]
    _TUTORIAL_PULSE["width_min"] = pulse["width_min"]
    _TUTORIAL_PULSE["width_max"] = pulse["width_max"]
    _TUTORIAL_PULSE["pulse_period_s"] = pulse["pulse_period_s"]


def highlight_color(event):
    """``event``'s authored colour.

    For the handful of places that draw something OTHER than the tile diamond
    in a highlight's colour and would otherwise need a second home for it: the
    RANGE overlay pill, the move-instruction text and path line, the
    drag-select rectangle's fill. Read it at CALL time, never bind it to a
    module constant — the early-binding trap `configure_palette`'s consumers
    already live under.
    """
    return _HIGHLIGHTS[event]["color"]


def highlight_params(event):
    """``event``'s full param dict (colour, border width, fill alpha)."""
    return _HIGHLIGHTS[event]


def submit_highlight(renderer, event, col, row, assets=None, anim_time_ms=0,
                     pulse_color=None, pulse_width=None):
    """Draw one continuous tile highlight for ``event`` at ``(col, row)``.

    The sibling of ``FloaterManager._play`` for effects that are NOT one-shots
    (VA-5/D7): a selection outline is drawn every frame for as long as the
    tile stays selected, so ``PlayOnceVfx``'s despawn clock is the wrong
    mechanism — it would respawn the object every frame.

    Resolution order matches ``_play``'s: a bound ``sprite_slot`` with
    imported art wins, otherwise the procedural diamond runs. "Has art" is the
    same ``animation_total_ms(slot, "idle") is not None`` signal every other
    art-tolerant site uses, so the two paths cannot disagree about
    "imported". ``assets=None`` (a bare panel a test builds) simply takes the
    procedural path.

    ``draw_in_front`` becomes the depth rank (VA-3): +1 draws over a
    same-tile building, -1 behind it.

    ``pulse_color``/``pulse_width`` (the tile-buying tutorial topic's pulse,
    ``tutorial_pulse_style`` below) override the static border colour/width
    ONLY on the procedural-diamond fallback below — imported art still wins
    exactly as it does for every other event, unaffected by either.
    """
    slot, in_front = _HIGHLIGHT_TRIGGERS.get(event, ("", True))
    rank = 1 if in_front else -1
    if slot and assets is not None:
        if assets.animation_total_ms(slot, "idle") is not None:
            renderer.submit(RenderItem(
                slot, (col, row), animation="idle",
                anim_time_ms=anim_time_ms, rank=rank))
            return
    params = _HIGHLIGHTS.get(event)
    if params is None:
        return                      # unknown event: a silent no-op (E-37)
    color, width = params["color"], params["border_width"]
    border_color = pulse_color if pulse_color is not None else color
    border_width = pulse_width if pulse_width is not None else width
    alpha = params["fill_alpha"]
    if alpha:
        submit_tile_diamond_fill(renderer, col, row, color + (alpha,),
                                 border=border_color,
                                 border_width=border_width, rank=rank)
    else:
        submit_tile_diamond(renderer, col, row, border_color,
                            width=border_width, rank=rank)


def tutorial_pulse_style(clock_ms):
    """``(rgba, width)`` for the pulsing/glowing tutorial highlight at
    wall-clock time ``clock_ms`` milliseconds — border alpha AND width both
    breathe on a smooth sine cycle over ``procedural.tutorial_highlight_
    pulse``'s ``pulse_period_s`` seconds (``data/balancing/vfx.json``, the
    Drummer aura's alpha-breathe precedent, ``game/ui/CLAUDE.md``), composed
    onto ``highlight_color("tutorial_highlight")`` rather than a second
    colour home. Feeds every tutorial highlight draw call: the tile diamonds
    (``submit_highlight``'s ``pulse_color``/``pulse_width``) and the card/
    button UI-box rings (``submit_ui_box_highlight``'s ``color``/``width``).
    """
    p = _TUTORIAL_PULSE
    phase = (math.sin(2 * math.pi * (clock_ms / 1000.0)
                      / p["pulse_period_s"]) + 1) / 2
    alpha = round(p["alpha_min"] + phase * (p["alpha_max"] - p["alpha_min"]))
    width = round(p["width_min"] + phase * (p["width_max"] - p["width_min"]))
    color = highlight_color("tutorial_highlight") + (alpha,)
    return color, width


def submit_tile_diamond(renderer, col, row, color, width=2, rank=0):
    """A world-space diamond outline around tile ``(col, row)`` — a selection /
    range / unlock highlight. fix/depth-sorted-world-fills: goes through
    ``Renderer.submit_world_fill`` (world_pos=(col, row), the same anchor a
    building's own ``Transform`` uses), NOT ``submit_overlay_lines`` — this
    sorts into the SAME depth queue as buildings, so it can draw BEHIND a
    building standing on/near this tile instead of always on top of every
    sprite (see ``engine/render/CLAUDE.md``'s "Depth-sorted world fills")."""
    pts = [(col, row), (col + 1, row), (col + 1, row + 1), (col, row + 1)]
    renderer.submit_world_fill(pts, world_pos=(col, row), border=color,
                               border_width=width, rank=rank)


def submit_tile_diamond_fill(renderer, col, row, rgba, border=None,
                             border_width=2, rank=0):
    """An alpha-FILLED world-space tile diamond with an optional outline —
    the prototype's SRCALPHA tile overlays (condition tint, RANGE, heatmap,
    tier overview). fix/depth-sorted-world-fills: same
    ``Renderer.submit_world_fill`` mechanism as ``submit_tile_diamond`` above
    — draws behind a building on/near this tile instead of always on top."""
    pts = [(col, row), (col + 1, row), (col + 1, row + 1), (col, row + 1)]
    renderer.submit_world_fill(pts, world_pos=(col, row), color=rgba,
                               border=border, border_width=border_width,
                               rank=rank)


def submit_ui_box_highlight(renderer, rect, color=None, width=3):
    """A highlight ring around a UI element (card / Confirm / End Turn) —
    the tutorial guided-chain highlight (D8, TU-6). Plain HUD-space rect;
    ``color`` defaults to the CURRENT tutorial-highlight colour, resolved
    inside the body (never as a def-time default — the same UH-6 rebind trap
    ``submit_panel``'s ``fill``/``border`` guards against; since VA-5 the
    value comes from ``procedural.highlights.tutorial_highlight`` rather than
    a module constant, which makes reading it late matter more, not less)."""
    if color is None:
        color = highlight_color("tutorial_highlight")
    renderer.submit_hud(HudRect(rect, color, width=width))


def submit_tutorial_banner(renderer, text, view_w, view_h, *, pad=12,
                            font_key="lg"):
    """A large, non-interactive, screen-centred banner (TU-8 Fix 2) — the
    ``submit_ui_box_highlight`` sibling for a full text hint (e.g. "right
    click anywhere to close"). A box filled in the tutorial highlight's own
    colour (``procedural.highlights.tutorial_highlight`` since VA-5, read at
    call time) with a dark border and dark centred text, sized to the text.
    Deliberately carries NO hit-test and consumes no input, UNLIKE
    ``TutorialMessageScreen`` — a banner instructing a right-click must never
    itself swallow it."""
    tw, th = text_size(text, font_key)
    w, h = tw + pad * 2, th + pad * 2
    x, y = (view_w - w) // 2, (view_h - h) // 2
    renderer.submit_hud(HudRect((x, y, w, h),
                                highlight_color("tutorial_highlight")))
    renderer.submit_hud(HudRect((x, y, w, h), C_UI_BORDER, width=3))
    submit_centered(renderer, text, view_w // 2, y + pad, font_key,
                    C_UI_PANEL)


def submit_bar(renderer, x, y, w, h, ratio, *, bg, fill, border=None):
    """A horizontal fill bar (HP / lives). ``ratio`` clamped to [0, 1]."""
    ratio = max(0.0, min(1.0, ratio))
    renderer.submit_hud(HudRect((x, y, w, h), bg))
    if ratio > 0:
        renderer.submit_hud(HudRect((x, y, int(w * ratio), h), fill))
    if border is not None:
        renderer.submit_hud(HudRect((x, y, w, h), border, width=1))


def submit_progress_ring(renderer, cx, cy, radius, ratio, *,
                          bg=None, fill=None, width=2, segments=96):
    """A small circular hold-progress indicator (cutscene hold-to-skip): a
    dim full ring plus a bright arc from 12 o'clock clockwise proportional
    to ``ratio`` (clamped to [0, 1]). Composed from ``HudLines`` — no arc/pie
    HUD primitive exists (`engine/render/hud.py`), the same reason
    ``submit_ui_box_highlight``/``submit_tutorial_banner`` above compose
    from existing primitives instead of adding a new engine one. Colors
    default to ``None`` and resolve here, not at def time — the UH-6
    rebind-safety convention every helper in this file follows.

    The arc's points sit on a FIXED angular grid (``i * (2*pi/segments)``,
    independent of ``ratio``) rather than being re-subdivided every frame —
    a point's screen position is therefore identical every frame from the
    moment it first appears; only one trailing fractional point (the exact
    tip) is recomputed each call. The previous version divided the arc into
    ``round(segments * ratio)`` steps, i.e. it re-subdivided the WHOLE arc
    on every call — since that step count changes every frame as ``ratio``
    grows, every already-drawn point's angle shifted slightly too, not just
    the tip, so the whole curve visibly "re-flowed" frame to frame. That,
    not the segment count, was the actual cause of the reported jitter."""
    if bg is None:
        bg = C_UI_TEXT_DIM
    if fill is None:
        fill = C_GOLD
    ratio = max(0.0, min(1.0, ratio))
    bg_pts = tuple(
        (cx + radius * math.sin(2 * math.pi * i / segments),
         cy - radius * math.cos(2 * math.pi * i / segments))
        for i in range(segments + 1))
    renderer.submit_hud(HudLines(bg_pts, bg, width=width, closed=True))
    if ratio > 0:
        step = 2 * math.pi / segments
        target_angle = 2 * math.pi * ratio
        full = int(target_angle / step)
        arc_pts = [
            (cx + radius * math.sin(i * step),
             cy - radius * math.cos(i * step))
            for i in range(full + 1)
        ]
        if target_angle > full * step + 1e-9:
            arc_pts.append((cx + radius * math.sin(target_angle),
                            cy - radius * math.cos(target_angle)))
        renderer.submit_hud(HudLines(tuple(arc_pts), fill, width=width))


class Button:
    """A rectangular click target that emits its own HUD frame + centred label.

    Pure: ``hit`` is rect math, ``submit`` is HUD primitives. The host feeds
    mouse position through ``hover(mx, my)`` and clicks through ``hit(mx, my)``.
    A ``flash`` timer (set by ``start_flash``) redraws it red — the
    not-enough-love feedback (prototype ``_draw_btn_red``).

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

    def __init__(self, rect, label, font_key="lg", enabled=True, skin=None,
                 font_family=None):
        self.rect = rect
        self.label = label
        self.font_key = font_key
        # UH-Font-B: the font FAMILY this button's label draws in, or None for
        # the active one. Appended LAST in the signature on purpose — the
        # shipping call sites pass (rect, label, font_key) positionally, so
        # `enabled`/`skin` must keep their places.
        self.font_family = font_family
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
        self.flash = duration
        self.flash_label = label

    def update(self, dt):
        if self.flash > 0:
            self.flash = max(0.0, self.flash - dt)
            if self.flash == 0:
                self.flash_label = None

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
        # UL-5: the per-state appearance patch, resolved through the SAME
        # ``_state()`` the skinned sprite row uses below — so the flat fill,
        # the skin row and this patch can never disagree about the state.
        patch = _state_patch(self, self._state())
        if self.flash > 0:
            fill, tcol = C_RED, C_UI_TEXT
            label = self.flash_label or self.label
        elif not self.enabled:
            fill, tcol, label = C_UI_BTN_DISABLED, C_UI_TEXT_DIM, self.label
        else:
            fill = color or (C_UI_BTN_HOVER if self.hovered else C_UI_BTN)
            tcol = text_color or C_UI_TEXT
            label = self.label
        if text_color is None and patch.get("text_color") is not None:
            # An explicit per-call ``text_color=`` is MORE specific than a
            # state patch (``skinning.button_kwargs``' override), so it wins;
            # otherwise the patch recolours the label for this state.
            tcol = tuple(patch["text_color"])
        # The nudge applies to what is DRAWN this frame only. ``self.rect`` is
        # never reassigned: ``_surface_hit``/``hit`` read it directly on the
        # next frame and have no notion of "the rect I drew offset by".
        dx, dy, dw, dh = _state_offset(patch)
        x, y, w, h = x + dx, y + dy, w + dw, h + dh
        if self.skin:
            # 10L-A: the sprite replaces both rects; ``color`` (a fill
            # override) has nothing to fill and is ignored. Label unchanged.
            # D6/UH-6: ``tint`` (a sheet-multiply color, ``None`` = unchanged)
            # rides along the same setattr an override applies — only a
            # skinned button (or one whose screen doc assigned it) ever
            # carries the attribute, so ``getattr`` covers dynamic
            # (non-id'd) buttons too, which never gain one.
            renderer.submit_hud(HudSprite(self.skin, (x, y), (w, h),
                                          animation=self._state(),
                                          anim_time_ms=anim_ms,
                                          tint=getattr(self, "tint", None)))
        else:
            renderer.submit_hud(HudRect((x, y, w, h), fill, border_radius=3))
            renderer.submit_hud(HudRect((x, y, w, h), C_UI_BORDER,
                                        border_radius=3, width=1))
        # layout_h, not text_h: this positions every Button label recorded in
        # the parity/exporter streams (engine/render/fonts.py "layout_h").
        ty = y + (h - layout_h(self.font_key)) // 2
        # layout_h above takes no family (the pinned-layout rule): a family
        # swap changes the glyphs this line draws, never where it draws them.
        submit_centered(renderer, label, x + w // 2, ty, self.font_key, tcol,
                        family=getattr(self, "font_family", None))
