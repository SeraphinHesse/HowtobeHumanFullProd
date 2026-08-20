"""Per-screen skin overrides (10L-B phase B2, plan lines 294-307).

Loads + schema-validates every ``data/ui/screens/*.json`` ONCE, at
``ScreenSkinning(data_dir)`` construction. ``apply(screen_id, ids)`` mutates a
screen's named widgets in place from the matching override — a pure in-memory
setattr loop, **zero disk I/O per call** — so a screen whose ``submit()`` calls
``layout()`` (and therefore ``apply()``) every frame (``cheat_menu.py``) never
re-reads a file. ``screen_background(screen_id)`` / ``submit_background(...)``
supply the whole-screen background: the screen's own override if it authored
one, else ``DEFAULT_BACKGROUND_SLOT`` — except for the ``WORLD_SCREENS``, which
draw over the live game world and so stay transparent by default.

``hit_layer(ids, widgets_spec, mx, my, state_of, actions)`` (UL-10) is the
click-path twin of ``submit_layers``: it asks the pure
``engine.ui_layers.hit`` which clickable layer (if any) a point lands on and
turns that into the SAME action value the screen's own ``hit()`` would
return. Pure — it never mutates a widget, the spec, or module state, which is
what lets ``Hud.hit()`` stay a pure read under ``main.py``'s two calls per
click (D8).

``submit_layers(screen_id, ids, band, state_of)`` (UL-4) draws a widget's
authored ``layers`` — one call per screen per band, resolved fresh each frame
through the pure ``engine.ui_layers`` so a layer follows its owner when
``layout()``/``apply()`` moves it. No ``layers`` authored, zero primitives.

The SAME two calls also draw the screen's ``custom_widgets`` — designer-
authored widgets no code owns, whose JSON entry is their DEFAULT GEOMETRY
only (everything paintable is an ordinary ``widgets/<same id>`` override).
They ride the existing two call sites deliberately: no screen's ``submit()``
gains a third call, so no ``custom_widgets`` key still means zero extra
primitives. They are never click targets — ``hit_layer`` does not see them.

Pure (no pygame) — a plain setattr loop over widget objects, and the three HUD
primitives it may emit (``HudRect``/``HudSprite``/``HudText``) are pure
dataclasses, the same sanctioned import ``widgets.py`` already makes.

**Widget id shape (the shared B3 contract, plan lines 122-169):**
``ids: {name: (kind, widget)}`` where ``kind`` is one of the six
``screen_defaults.schema.json`` values: ``"button" | "panel" | "label" |
"backdrop" | "bar" | "field"``. B3's exporter reads the same pair to emit
``{rect, kind, label}`` without type-sniffing — never change this shape.

**Graceful degrade (E-37):** a missing ``data/ui/screens/`` directory, a
missing/empty override file, or a corrupt one all resolve to "no override" for
that screen — never a crash. ``data/ui/screen_defaults.json`` (B3's output)
is used ONLY for id validation and may legitimately not exist yet; its absence
is likewise silent (``§1.4``).
"""
from pathlib import Path
from typing import Any, Dict, Optional

from engine import data_io, ui_layers
from engine.render import HudRect, HudSprite, HudText
from engine.render.fonts import layout_h

from . import strings

#: The whole-screen background every screen gets when its own JSON authors no
#: ``background`` key. A screen still overrides it freely (``credits.json``
#: picks black); this is the fallback, not a floor.
DEFAULT_BACKGROUND_SLOT = "ui_bg_main_menu"

#: Screens that draw ON TOP of the live game world, and therefore never take
#: ``DEFAULT_BACKGROUND_SLOT`` — a full-view opaque background there would
#: paint over the map, the buildings and the enemies. Derived from
#: ``game/main.py``'s ``_WORLD_STATES`` (+ ``PAUSED``): the world renders in
#: GAMEPLAY / GAME_OVER / PAUSED, so every screen that can be up during one of
#: those is listed. A screen NOT here is a shell screen with nothing behind it,
#: which is exactly what the default is for. A screen that authors its own
#: ``background`` is unaffected either way — the exemption only suppresses the
#: DEFAULT.
WORLD_SCREENS = frozenset((
    "hud",
    "overlays",
    "building_panel",
    "tutorial_message",
    "add_name",
    "levelup",
    "cheat_menu",
    "game_log",
    "enemy_intro",
    "boss_cutscene",
    "pause",
    "game_over",
))

_SCREENS_SUBDIR = ("ui", "screens")
_SCREEN_SCHEMA = "ui_screen.schema.json"
_DEFAULTS_FILE = ("ui", "screen_defaults.json")
_DEFAULTS_SCHEMA = "screen_defaults.schema.json"

#: JSON override key -> the widget attribute it mutates. Everything else
#: (rect/skin/label/color/text_color/visible/tint/text_id/font_family) maps
#: 1:1 onto the
#: same name — ``tint`` (D6/UH-6, the sheet-multiply color for a skinned
#: widget) and ``text_id`` (UT-1, the ``data/ui/strings.json`` key a label
#: holder resolves its text through — see ``widgets.submit_label``) need no
#: entry here for exactly that reason -- and neither does ``font_family``
#: (UH-Font-B), whose widget attribute is spelled the same as its JSON key
#: precisely because ``font``'s mismatch is the one wart in this table:
#: ``apply``'s generic setattr loop
#: already threads them onto the widget for free, the same way it always has
#: for ``skin``.
_SPEC_TO_ATTR = {"font": "font_key"}

#: The widget kinds a ``band`` override may RELOCATE (UL-14). A banded widget
#: is drawn generically by ``_submit_banded_widget`` from its AUTHORED
#: appearance — the same three kinds ``custom_widgets`` allows, and for the
#: same reason: only these have a meaningful code-free draw. ``button``/
#: ``bar``/``field`` carry behaviour (a click target, a live fill ratio, a
#: text buffer) that no generic draw can reproduce, so a ``band`` on one is
#: IGNORED and it keeps drawing where its screen always drew it — never
#: silently blanked.
_BANDABLE_KINDS = ("panel", "backdrop", "label")


def band_of(kind, spec) -> Optional[str]:
    """The band a CODE-OWNED widget of this ``kind`` is relocated into, or
    ``None`` for the normal case (drawn by its own screen, where it always
    was).

    Absent ``band`` means "not banded" — deliberately NOT the ``"under"`` a
    custom widget's absent band means. A custom widget has no other home to
    be drawn from, so it needs a default; a code-owned one does, and silently
    yanking every widget out of its screen's own ``submit()`` is not something
    an absent key may do."""
    band = (spec or {}).get("band")
    if band and kind in _BANDABLE_KINDS:
        return band
    return None


def _as_tuple(value):
    """JSON arrays decode as lists; every widget elsewhere stores rect/color
    as a tuple — keep overridden values the same shape callers already expect
    (rect unpacking, color arithmetic)."""
    return tuple(value) if isinstance(value, list) else value


def is_visible(widget) -> bool:
    """``True`` unless an override has set ``widget.visible = False``.
    ``Button``/holder objects carry no ``visible`` attribute until
    ``apply()`` setattrs one (only an override that names it does), so this
    is the one place every screen checks it — an invisible ``button``-kind
    widget must be neither drawn nor hit-tested (review HIGH 2)."""
    return getattr(widget, "visible", True)


def is_enabled(widget) -> bool:
    """``True`` unless the widget is a ``Button`` a screen has disabled.

    Only ``Button`` carries ``enabled``; icons, holders and readouts never do,
    so they default to ``True`` and behave exactly as before. Screens gate
    their own ``hit()`` through ``Button.hit``, which already checks this —
    ``hit_layer`` is the one path that does NOT go through it, which is why
    this exists (see ``hit_layer``'s ``enabled`` note)."""
    return getattr(widget, "enabled", True)


#: The three targets a clickable layer may name that are NOT a widget id in
#: its own screen (D7 as amended). ``noop`` is also what an UNROUTABLE target
#: resolves to — see ``hit_layer``'s Ruling 1.
RESERVED_TARGETS = ("close_window", "back", "noop")


def hit_layer(ids, widgets_spec, mx, my, state_of, actions=None):
    """The action a clickable LAYER produces for this click, or ``None``.

    PURE (D8). Nothing here mutates ``ids``, any widget, ``widgets_spec`` or
    module state — call it any number of times with the same arguments for the
    same answer. ``main.py`` calls ``Hud.hit()`` twice per click (the
    MOUSEBUTTONDOWN pan-arming probe, then the MOUSEBUTTONUP handler) and this
    function sits at the top of that path, so the guarantee is load-bearing.

    ``ids``: the screen's ``{name: (kind, widget)}`` dict (§1.2), read only.
    ``widgets_spec``: that screen's override ``widgets`` table, already in
        memory (``ScreenSkinning.widgets_spec(screen_id)``) — no disk I/O
        here, matching ``submit_layers``'s contract.
    ``state_of``: callable ``widget -> str``, normally
        ``ScreenSkinning.state_of``, resolved PER WIDGET (UL-5).
    ``actions``: optional ``{widget_id: action}`` for THIS screen — the
        screen's own action table, reversed. It is what makes a *retarget*
        possible: a layer whose ``target`` names another widget in the same
        screen fires that widget's own action. Screens pass the table they
        already have (``pause._ACTION_IDS`` reversed, ``main_menu``'s
        ``_SLOT_IDS``/``self.actions``, …) — never a second hand-rolled copy.

    Resolution, once a clickable layer is hit:

    * ``target`` in ``RESERVED_TARGETS`` -> that literal token; the caller
      routes it (``close_window`` / ``back`` / ``noop``).
    * ``target`` in ``actions`` -> that widget's own action (retarget).
    * anything else, INCLUDING a missing/empty ``target`` -> ``"noop"``.

    **Ruling 1 (UL-10): a dead target SWALLOWS the click, it does not fall
    through.** Returning ``None`` here would mean "no layer was hit", and the
    click would land on the widget UNDER the layer — so a typo'd target would
    silently behave as if the layer were never clickable at all, which is the
    exact failure the plan's risk bullet names. A swallowed click instead
    reads honestly as "this decal does nothing", the same thing ``noop``
    already means.

    A layer whose owning widget is invisible OR disabled is never hit (the
    ``is_visible`` rule every screen's ``hit()`` already applies, and the
    ``enabled`` gate ``Button.hit`` applies), and a non-clickable layer is
    transparent to the click — all enforced upstream in
    ``engine.ui_layers.hit``/here, never by mutating anything.

    **The ``enabled`` gate is load-bearing, not cosmetic.** This function runs
    BEFORE the screen's own hit path and returns early on a hit, so a widget's
    own ``hit()`` — the only place ``enabled`` was ever checked — never runs
    for a layer click. Every availability rule a screen expresses by clearing
    ``enabled`` therefore has to be re-checked here or it is simply bypassed:
    a layer on ``btn_end_turn`` fired ``end_turn`` during the ENEMY phase, and
    layers on ``btn_speed_*`` skipped ``speed_unlocked(idx)`` and
    ``_speed_buttons_visible`` (``game/ui/hud.py``, which folds all three
    gates into ``enabled``). Widgets that carry no ``enabled`` attribute at
    all (icons, holders) default to enabled, as they always were.
    """
    if not widgets_spec:
        return None
    actions = actions or {}
    for name, (_kind, widget) in ids.items():
        spec = widgets_spec.get(name)
        layer_list = (spec or {}).get("layers") or []
        if not layer_list or not is_visible(widget) or not is_enabled(widget):
            continue
        result = ui_layers.hit(layer_list, widget.rect, mx, my,
                               state_of(widget))
        # A ``None`` (missed entirely) or an ``{"kind": "owner"}`` hit both
        # mean "no clickable layer claimed this point" — keep scanning the
        # other widgets, then fall through to the screen's normal hit path.
        if not result or result.get("kind") != "layer":
            continue
        target = result.get("target")
        if target in RESERVED_TARGETS:
            return target
        if target in actions:
            return actions[target]
        return "noop"   # Ruling 1: unroutable target swallows the click
    return None


def button_kwargs(btn) -> Dict[str, Any]:
    """``color=``/``text_color=`` for ``Button.submit()``, taken from an
    override (``None`` — i.e. the button's own hover/flash/disabled logic —
    when absent). A skin, when set, ignores ``color`` entirely (``submit_panel``
    /``Button.submit``'s own long-standing precedence) — ``text_color`` still
    applies to the label overlay."""
    return {"color": getattr(btn, "color", None),
            "text_color": getattr(btn, "text_color", None)}


def load_screen_overrides(data_dir) -> Dict[str, Optional[dict]]:
    """``{screen_id: override_doc_or_None}`` for every
    ``data/ui/screens/*.json``. A missing directory yields ``{}``; a missing/
    empty/corrupt file resolves to ``None`` for that one screen id (its
    filename stem) rather than failing the whole load."""
    data_dir = Path(data_dir)
    screens_dir = data_dir.joinpath(*_SCREENS_SUBDIR)
    schema_path = data_dir / "schemas" / _SCREEN_SCHEMA
    overrides: Dict[str, Optional[dict]] = {}
    if not screens_dir.is_dir():
        return overrides
    for path in sorted(screens_dir.glob("*.json")):
        try:
            doc = data_io.load_validated(path, schema_path)
        except Exception:
            overrides[path.stem] = None
            continue
        overrides[path.stem] = doc or None
    return overrides


def load_screen_defaults(data_dir) -> Optional[dict]:
    """``data/ui/screen_defaults.json`` (B3's exporter output) if present and
    valid; ``None`` otherwise — B2 ships before B3, so its absence is normal,
    not an error."""
    path = Path(data_dir).joinpath(*_DEFAULTS_FILE)
    if not path.is_file():
        return None
    schema_path = Path(data_dir) / "schemas" / _DEFAULTS_SCHEMA
    try:
        return data_io.load_validated(path, schema_path) or None
    except Exception:
        return None


class ScreenSkinning:
    """Every screen override, loaded once. ``apply()`` is safe to call every
    frame (no disk I/O — the cheat_menu ``layout()``-every-frame case)."""

    def __init__(self, data_dir):
        self._overrides = load_screen_overrides(data_dir)
        self._defaults = load_screen_defaults(data_dir)
        self._validated_ids = set()  # screen ids whose override was checked

    @classmethod
    def from_overrides(cls, overrides):
        """A disk-free instance over an IN-MEMORY ``{screen_id: doc}`` map
        (UT-2). The preview generator uses it to record what a designer's
        UNSAVED screen doc would look like in game, without staging a whole
        temp ``data/`` tree. Id validation stays off (no defaults doc), which
        is right for a preview: an editor mid-edit is allowed to be wrong."""
        self = cls.__new__(cls)
        self._overrides = dict(overrides or {})
        self._defaults = None
        self._validated_ids = set()
        return self

    @classmethod
    def empty(cls):
        """A disk-free no-op instance — the default for any screen/Shell
        built without an explicit ``ScreenSkinning`` (tests, standalone
        screen construction). Behaves exactly like "no override file"."""
        self = cls.__new__(cls)
        self._overrides = {}
        self._defaults = None
        self._validated_ids = set()
        return self

    def apply(self, screen_id: str, ids: Dict[str, Any]) -> None:
        """``ids``: ``{name: (kind, widget)}`` (§1.2). For every name with a
        matching entry in ``data/ui/screens/<screen_id>.json``'s ``widgets``
        table, setattr the overridden fields onto ``widget`` IN PLACE. A
        screen with no override (or an empty one) leaves every widget
        untouched — the golden parity contract."""
        widgets_spec = self._widgets_spec(screen_id)
        if screen_id not in self._validated_ids:
            self._validate_ids(screen_id, widgets_spec)
            self._validated_ids.add(screen_id)
        # The screen-level default skin for CODE-OWNED buttons. The editor
        # has always previewed this fallback (``editor/panels/viewport.py``'s
        # `_submit_screen_widget`, mirrored in `_screen_rules.resolved_skin`)
        # while the game read only the per-widget `skin` — so picking a
        # screen's *Button skin* default changed the editor and nothing else.
        # Resolving it here is what makes the two agree.
        #
        # BUTTONS ONLY, deliberately: `panel_skin` has the same editor/game
        # gap, but `hud.json` and `building_panel.json` already set it and
        # ~70 of their panels carry no per-widget skin, so honouring it would
        # silently reskin most of the HUD and every construct card. That is a
        # separate, art-directed decision — not this fix (user decision).
        default_button_skin = self.defaults(screen_id).get("button_skin")
        if not widgets_spec and not default_button_skin:
            return
        for name, (kind, widget) in ids.items():
            spec = widgets_spec.get(name)
            if not spec:
                # No per-widget override at all: the screen default is still
                # this button's skin (an id absent from `widgets` is
                # un-customized, not opted out).
                if default_button_skin and kind == "button":
                    widget.skin = default_button_skin
                continue
            # A per-widget `skin` WINS (including an explicit null, which is
            # how a designer opts one button out of the screen default) —
            # same precedence as the editor's `resolved_skin`.
            if (default_button_skin and kind == "button"
                    and "skin" not in spec):
                widget.skin = default_button_skin
            for key, value in spec.items():
                setattr(widget, _SPEC_TO_ATTR.get(key, key), _as_tuple(value))
            # UL-14: a BANDED widget is drawn by ``submit_layers``'s band
            # pass, not by its own screen — so the screen must skip it. The
            # seam is ``visible``, forced False here, because that is the ONE
            # flag every screen already consults at BOTH its draw sites and
            # its hit sites (``is_visible``, and the two holders that read
            # ``.visible`` directly). That makes a banded widget INERT as
            # well as relocated, exactly like a custom widget: a click passes
            # straight through to whatever is under it. Which is why
            # ``_BANDABLE_KINDS`` excludes ``button`` — banding a control
            # would silently kill its clicks, and the editor refuses it too.
            #
            # ``_submit_banded_widget`` therefore reads ``visible`` off the
            # SPEC, never off the widget: this write would otherwise hide the
            # widget from the very pass that is supposed to draw it.
            if band_of(kind, spec):
                widget.visible = False

    def state_of(self, widget) -> str:
        """Which of the four D9 states ``widget`` is in: ``"idle" | "hover" |
        "pressed" | "disabled"`` (UL-4's seam, given its real body by UL-5).

        The ONE place a widget's state is normalized for the layer/per-state
        draw path. A ``Button`` answers through its own ``_state()`` — the
        same call its skin row and flat fill already use, so a third
        appearance layer can never disagree with those two. Every other
        widget (panel/label/backdrop holders are plain ``SimpleNamespace``
        objects with no state machine at all) resolves to ``"idle"``, always:
        only a ``states.idle`` patch is reachable on one of those today.
        """
        fn = getattr(widget, "_state", None)
        return fn() if callable(fn) else "idle"

    def defaults(self, screen_id: str) -> Dict[str, Any]:
        """The screen's ``defaults`` section (``button_skin``/``panel_skin``/
        ``font``/``text_color``), or ``{}`` when unset — the styling surface
        for DYNAMIC-count content that cannot carry a stable id (construct
        cards, the boss-history popup, levelup's option boxes, …; B3's
        "dynamic content inherits defaults" rule). Reads the already-in-memory
        override — no disk I/O, safe every frame/every construction."""
        override = self._overrides.get(screen_id)
        return (override or {}).get("defaults") or {}

    def widget_rect(self, screen_id: str, name: str) -> Optional[tuple]:
        """The authored ``rect`` for ONE widget id, or ``None`` when the
        designer never moved it. The companion to ``defaults()``: dynamic-count
        content (construct cards, …) is laid out in CODE and so cannot be
        re-authored id-by-id in the editor, but it still has to sit INSIDE a
        container the designer *did* move. Reading that container's rect here
        is what lets it follow. Reads the already-in-memory override — no disk
        I/O, safe every frame/every construction."""
        spec = self._widgets_spec(screen_id).get(name)
        rect = (spec or {}).get("rect")
        return _as_tuple(rect) if rect else None

    def widgets_spec(self, screen_id: str) -> Dict[str, Any]:
        """This screen's override ``widgets`` table (``{}`` when unset) — the
        public accessor `hit_layer`'s callers pass in, alongside the existing
        ``defaults()``/``widget_rect()`` public readers. Already in memory, so
        safe every frame / every click."""
        return self._widgets_spec(screen_id)

    def screen_background(self, screen_id: str) -> Optional[Dict]:
        """``{"slot": ...}`` or ``{"color": (...)}`` for a submit-time
        background, or ``None``. Reads the already-in-memory override — no
        disk I/O, safe every frame.

        **Default background**: a screen that authors no ``background`` key
        falls back to ``DEFAULT_BACKGROUND_SLOT`` rather than to nothing, so
        the shell screens share one look without each having to repeat the
        slot in its JSON. A screen listed in ``WORLD_SCREENS`` is EXEMPT and
        still returns ``None`` — see that constant for why. An explicit
        ``background`` (including ``credits.json``'s black) always wins, so
        the default is only ever what an un-authored screen gets."""
        override = self._overrides.get(screen_id)
        bg = (override or {}).get("background") if override else None
        if not bg:
            if screen_id in WORLD_SCREENS:
                return None
            return {"slot": DEFAULT_BACKGROUND_SLOT}
        if "color" in bg:
            return {"color": _as_tuple(bg["color"])}
        return {"slot": bg["slot"]}

    def backdrop_fill_hides_background(self, screen_id: str) -> bool:
        """True when this screen's full-view ``backdrop`` fill would paint
        OVER the background ``submit_background`` just drew, hiding it.

        Every shell screen builds its ``backdrop`` holder with an opaque
        code-default colour (``SimpleNamespace(..., color=_BG)``) and draws it
        immediately after the background — which predates backgrounds existing
        and is why a screen could resolve a background and still look flat.
        A screen that draws its backdrop through ``widgets.submit_backdrop``
        passes this as ``skip_fill`` so the fill yields to the art.

        Two things it deliberately does NOT suppress:

        * a designer's ``backdrop.skin`` — ``submit_backdrop`` handles that
          precedence itself, and a skin is an explicit choice to cover.
        * a designer's ``backdrop.color`` authored in ``data/ui/screens/
          <id>.json`` — an explicit fill beats an inherited background, the
          same way an explicit ``background`` key beats the default one.
        """
        if self.screen_background(screen_id) is None:
            return False
        return "color" not in self._widgets_spec(screen_id).get("backdrop", {})

    def submit_background(self, renderer, screen_id: str, view_w, view_h,
                          anim_ms: int = 0) -> None:
        """Draw the full-view background override (if any) — one call at the
        top of a screen's ``submit()``. A no-op with no ``background`` key
        (every shipped screen JSON today), so it never changes parity.

        ``anim_ms``: the owning screen's animation clock, threaded into the
        sprite exactly like ``submit_layers``' — a background slot with a
        multi-frame ``idle`` row otherwise draws frame 0 forever, which is
        what every background did before this argument existed. Defaults to
        0 so a caller that omits it keeps the old still-frame behaviour
        rather than crashing."""
        bg = self.screen_background(screen_id)
        if bg is None:
            return
        if "slot" in bg:
            renderer.submit_hud(HudSprite(bg["slot"], (0, 0), (view_w, view_h),
                                          anim_time_ms=int(anim_ms)))
        else:
            renderer.submit_hud(HudRect((0, 0, view_w, view_h), bg["color"]))

    def submit_layers(self, renderer, screen_id: str, ids: Dict[str, Any],
                      band: str, state_of, anim_ms: int = 0,
                      view: Optional[str] = None,
                      hidden_customs=()) -> None:
        """Draw every widget's ``band``-side layer stack — ONE call per screen
        per band (UL-4 D4), at the top (``"under"``) or the end (``"over"``)
        of a screen's ``submit()``. The HUD pass has no depth sort, so draw
        order IS submission order; ``z`` orders layers WITHIN a band.

        ``ids``: the same ``{name: (kind, widget)}`` dict every screen already
        builds (§1.2). ``state_of``: a CALLABLE ``widget -> str`` — normally
        ``self.state_of``, passed by reference and resolved PER WIDGET, not
        once per screen, because UL-5 makes it vary per widget.

        ``anim_ms``: the owning screen's animation clock, threaded into every
        layer sprite so an authored MULTI-FRAME row actually plays. A screen
        that omits it draws frame 0 forever, which is what every layer did
        before the lost-life flight needed a moving dying row.

        ``view``: which of this screen's VIEWS is on screen right now — the
        caller's own mode name (``BuildingUI.mode``; ``"preview"`` for the two
        modals). It gates CUSTOM widgets only, and only the ones that named a
        view: everything else is already view-scoped by construction, because
        a mode only puts the widgets it built into ``ids``. A screen with one
        view passes nothing and nothing filters.

        This exists because a screen ID is not a screen. ``building_panel``
        is five modes plus two modals that all declare the same id, so a
        custom widget drawn off the id alone shows up in every one of them at
        once — a decorative plate authored for the build list also landing on
        the unlock and upgrade panels, and on top of an open preview. Naming
        a view in the entry is how a designer says which one it belongs to.

        ``hidden_customs``: custom-widget names the CALLER wants dropped this
        frame. The ``view`` gate above is static (a widget belongs to a mode
        or it does not); this one is for decoration whose reason to exist is
        live state the designer cannot express in the doc — a plate sized to
        back N stat rows has nothing to back on a building with fewer
        (``BuildingUI._hidden_stat_backdrops``). Empty by default, so every
        other screen is unchanged.

        A widget with no ``layers`` entry in this screen's override produces
        ZERO calls — the golden parity case (D5), and the overwhelmingly
        common path today (no shipped screen authors any layer)."""
        widgets_spec = self._widgets_spec(screen_id)
        customs = self._custom_in_band(screen_id, band, view, hidden_customs)
        # The "no override at all" fast path — the golden parity case (D5).
        # It has to test BOTH tables: a screen may author custom widgets and
        # no per-widget overrides, and an early return on ``widgets_spec``
        # alone would silently draw none of them.
        if not widgets_spec and not customs:
            return
        # UL-14: the code-owned widgets this screen RELOCATED into a band.
        # Both bands are collected, not just ours: a widget banded ``over``
        # must be skipped by the ``under`` pass's layer loop too, or its
        # layers would draw twice (once here, once at its own z below).
        banded_here, banded_any = self._banded_in_band(screen_id, ids, band)
        for name, (_kind, widget) in ids.items():
            if name in banded_any:
                continue        # drawn, layers and all, at its own z below
            spec = widgets_spec.get(name)
            layer_list = (spec or {}).get("layers") or []
            if not layer_list:
                continue
            state = state_of(widget)
            for entry in ui_layers.ordered(layer_list, band):
                resolved = ui_layers.resolve(entry, widget.rect, state)
                if resolved.get("visible") is False:
                    continue
                self._submit_one_layer(renderer, resolved, state, anim_ms)
        # Custom widgets and banded code-owned widgets share ONE z ordering
        # (UL-14) — that is the whole point of banding a code-owned widget.
        # ``sorted`` is stable, so a z tie keeps this list's own order:
        # customs first (file order), then banded widgets (``ids`` order).
        in_band = [(e.get("z") or 0, "custom", n, e) for n, e in customs]
        in_band += [((widgets_spec.get(n) or {}).get("z") or 0, "code", n,
                     (k, w)) for n, k, w in banded_here]
        for _z, origin, name, payload in sorted(in_band, key=lambda r: r[0]):
            if origin == "custom":
                self._submit_custom_widget(renderer, screen_id, name,
                                           payload, band, anim_ms)
            else:
                self._submit_banded_widget(renderer, screen_id, name, payload,
                                           band, anim_ms)

    def custom_widgets(self, screen_id: str) -> Dict[str, Any]:
        """This screen's ``custom_widgets`` table (``{}`` when unset) — the
        designer-authored widgets that have no code owner. Already in memory,
        so safe every frame."""
        override = self._overrides.get(screen_id)
        return (override or {}).get("custom_widgets") or {}

    # -- internal ----------------------------------------------------------

    def _banded_in_band(self, screen_id, ids, band):
        """``([(name, kind, widget), ...], {every banded name})`` — the
        code-owned widgets this screen RELOCATED into ``band`` (UL-14), plus
        the set of names banded into EITHER band.

        The second value is what ``submit_layers``' layer loop skips on: a
        banded widget's layers travel WITH it to its z slot, so the pass for
        the OTHER band must not draw them at their owner's normal position.

        Unbanded is the norm and stays free — a screen whose override table
        names no ``band`` returns two empties after one dict lookup per id.
        A ``band`` on a ``button``/``bar``/``field`` is ignored here exactly
        as ``band_of`` says: that widget is not relocated and not skipped."""
        widgets_spec = self._widgets_spec(screen_id)
        if not widgets_spec:
            return [], frozenset()
        here, every = [], set()
        for name, (kind, widget) in ids.items():
            widget_band = band_of(kind, widgets_spec.get(name))
            if widget_band is None:
                continue
            every.add(name)
            if widget_band == band:
                here.append((name, kind, widget))
        return here, every

    def _banded_spec(self, name, kind, widget, screen_id):
        """The appearance a banded widget draws from: its ``widgets/<name>``
        override, with the LIVE widget's own attributes underneath.

        The override wins (it is the designer's word), but a code-set value
        the designer never touched still draws — which is what makes banding
        an icon holder whose ``skin`` is assigned in ``layout()`` do the
        obvious thing rather than vanish.

        **What a banded widget canNOT reproduce**: appearance the screen
        computes at its own draw site and never stores on the holder — a
        hand-coded fill colour (``hud``'s love pill), a live text value passed
        as ``submit_label(..., text=)``. Those are code-owned by construction
        (the same reason ``label`` is not an override key for a HUD readout);
        a banded widget draws its AUTHORED appearance, and a designer who
        wants a box there gives it a ``skin`` or a ``color``."""
        spec = dict(self._widgets_spec(screen_id).get(name) or {})
        for key, attr in (("skin", "skin"), ("tint", "tint"),
                          ("color", "color"), ("label", "label"),
                          ("text_id", "text_id"), ("font", "font_key"),
                          ("font_family", "font_family"),
                          ("text_color", "text_color"), ("align", "align")):
            if spec.get(key) is None:
                value = getattr(widget, attr, None)
                if value is not None:
                    spec[key] = value
        # ``kind`` rides along so the draw reads one object, matching
        # ``_submit_custom_widget``'s ``entry["kind"]``.
        spec["kind"] = kind
        return spec

    def _submit_banded_widget(self, renderer, screen_id, name, pair, band,
                              anim_ms: int = 0) -> None:
        """Draw ONE code-owned widget that a ``band`` override RELOCATED into
        this band (UL-14), then its own layers — the ``_submit_custom_widget``
        twin, and deliberately the same primitives in the same precedence, so
        a banded ``panel`` and a custom ``panel`` cannot look different.

        Two things it does NOT share with that method:

        * **The rect is the LIVE widget's**, not the spec's. A code-owned
          widget's rect is computed by its screen's ``layout()`` every frame
          (and only then overridden), so reading the spec would freeze a HUD
          readout at whatever the designer typed and strand every unauthored
          one at the origin.
        * **``visible`` is read off the SPEC.** ``apply()`` forces
          ``widget.visible = False`` on every banded widget — that is the
          seam that stops its own screen drawing it — so the widget's flag
          says nothing here. An authored ``visible: false`` still suppresses
          the whole thing, the rule every screen applies.
        """
        kind, widget = pair
        spec = self._banded_spec(name, kind, widget, screen_id)
        if spec.get("visible") is False:
            return
        rect = _as_tuple(getattr(widget, "rect", None) or (0, 0, 0, 0))
        x, y, w, h = rect
        defaults = self.defaults(screen_id)
        state = self.state_of(widget)
        if kind in ("panel", "backdrop"):
            skin = spec.get("skin")
            if kind == "panel" and not skin:
                skin = defaults.get("panel_skin")
            if skin:
                renderer.submit_hud(HudSprite(
                    skin, (x, y), (w, h), animation=state,
                    anim_time_ms=anim_ms, tint=_as_tuple(spec.get("tint"))))
            else:
                color = spec.get("color")
                if color:
                    renderer.submit_hud(HudRect((x, y, w, h),
                                                _as_tuple(color)))
            if kind == "panel":
                self._submit_custom_text(renderer, spec, defaults, rect,
                                         center=True)
        elif kind == "label":
            self._submit_custom_text(renderer, spec, defaults, rect,
                                     center=False)
        for layer in ui_layers.ordered(spec.get("layers") or [], band):
            resolved = ui_layers.resolve(layer, rect, state)
            if resolved.get("visible") is False:
                continue
            self._submit_one_layer(renderer, resolved, state, anim_ms)

    def _custom_in_band(self, screen_id, band, view=None, hidden=()):
        """``[(name, entry), ...]`` for this screen's custom widgets whose
        band matches, ascending ``z`` (absent band == ``"under"``, absent
        ``z`` == 0). Ties keep authoring (dict/JSON) order — ``sorted`` is
        stable — so a designer's file order is the tie-break, not chance.

        **The absent-band default is ``"under"``, NOT the ``"over"`` an
        undecorated LAYER entry gets** (``engine/ui_layers.ordered``, which is
        unchanged). A custom widget is decoration a designer invented; the
        screen's own readouts, counters and buttons are the information the
        player needs, and a decorative box defaulting on top of them hides
        the game. Over is still authorable per widget — it is just no longer
        what you get by saying nothing.

        ``view`` drops any entry that named a DIFFERENT view (see
        ``submit_layers``). An entry with no ``view`` is unscoped and always
        kept — both the single-view case and every widget authored before the
        key existed — and a caller that passes no view keeps everything, so
        nothing filters on a screen that has no views.

        ``hidden`` drops entries by NAME — the caller's live-state gate (see
        ``submit_layers``), applied on top of both filters above."""
        table = self.custom_widgets(screen_id)
        if not table:
            return []
        rows = [(n, e) for n, e in table.items()
                if (e.get("band") or "under") == band
                and (view is None or not e.get("view")
                     or e.get("view") == view)
                and n not in hidden]
        return sorted(rows, key=lambda pair: pair[1].get("z") or 0)

    def _submit_custom_widget(self, renderer, screen_id, name, entry,
                              band, anim_ms: int = 0) -> None:
        """Draw ONE designer-authored custom widget, then its own layers.

        Deliberately NOT folded into ``_submit_one_layer``: that method's
        "one role, FIRST MATCH WINS" precedence is a design decision, and a
        ``panel`` here emits TWO primitives (its box AND a centred caption).

        The ``custom_widgets`` entry supplies ONLY the default rect (and the
        band/z that placed us here). Everything paintable is read off the
        ORDINARY ``widgets/<name>`` override, exactly as for a code-owned
        widget — including the ``rect``, which wins over the creation rect
        when the designer moved it, and ``visible: false``, which suppresses
        the whole thing (the ``is_visible`` rule every screen already
        applies, read off the spec because a custom widget has no object).

        Per kind, mirroring ``editor/panels/_screen_primitives.
        fallback_hud_items``' semantics (matched by eye, never imported —
        ``editor/`` and ``game/`` may not import each other, the same
        accepted drift that module's own docstring records):

        * ``panel``    — ``skin`` (falling back to this screen's
          ``defaults.panel_skin``) → ``HudSprite``, else ``color`` →
          ``HudRect``; THEN a CENTRED ``HudText`` when it carries
          ``label``/``text_id``.
        * ``backdrop`` — the same box with NO text and NO kind-matched
          default skin (there is none in the existing code, so only its own
          ``skin`` counts).
        * ``label``    — ``HudText`` only, through ``strings.T`` exactly as
          ``_submit_one_layer`` does; an empty resolved string draws NOTHING.

        State is always ``"idle"``: a custom widget has no state machine, the
        same answer ``state_of`` gives any non-``Button`` holder. It still
        rides the owning screen's ``anim_ms`` clock, so a MULTI-FRAME idle
        row plays instead of freezing on frame 0 (it used to omit the clock
        entirely, which is why every skinned custom panel sat still).
        """
        spec = self._widgets_spec(screen_id).get(name) or {}
        if spec.get("visible") is False:
            return
        rect = _as_tuple(spec.get("rect") or entry["rect"])
        x, y, w, h = rect
        kind = entry.get("kind")
        defaults = self.defaults(screen_id)
        if kind in ("panel", "backdrop"):
            skin = spec.get("skin")
            if kind == "panel" and not skin:
                skin = defaults.get("panel_skin")
            if skin:
                renderer.submit_hud(HudSprite(
                    skin, (x, y), (w, h), animation="idle",
                    anim_time_ms=anim_ms,
                    tint=_as_tuple(spec.get("tint"))))
            else:
                color = spec.get("color")
                if color:
                    renderer.submit_hud(HudRect((x, y, w, h),
                                                _as_tuple(color)))
            if kind == "panel":
                self._submit_custom_text(renderer, spec, defaults, rect,
                                         center=True)
        elif kind == "label":
            self._submit_custom_text(renderer, spec, defaults, rect,
                                     center=False)
        # Then its own layers, from the SAME widgets/<name> override, against
        # this rect, filtered to the band we were called for. Always "idle".
        for layer in ui_layers.ordered(spec.get("layers") or [], band):
            resolved = ui_layers.resolve(layer, rect, "idle")
            if resolved.get("visible") is False:
                continue
            self._submit_one_layer(renderer, resolved, "idle", anim_ms)

    def _submit_custom_text(self, renderer, spec, defaults, rect,
                            *, center) -> None:
        """The ``HudText`` half of a custom widget, or nothing at all.

        Text resolves through ``strings.T`` when ``text_id`` is set, else the
        static ``label`` — the ``_submit_one_layer``/``widgets.submit_label``
        ladder, and an empty resolved string draws NOTHING rather than a
        blank ``HudText``. Font/colour fall back to this screen's
        ``defaults`` and then to the label-holder constants. ``center``
        centres on BOTH axes inside ``rect`` (a ``panel``'s caption), which
        needs the text's own height — ``HudText``'s own ``align="center"`` only
        shifts x, the same reason ``_screen_primitives.centered_label_item``
        measures. That height comes from the PINNED ``layout_h`` table, never
        a live ``TextMetrics`` measurement: this y lands in the captured
        HUD-primitive stream, and Windows/Linux measure SysFont heights
        ±1px apart (the layout-heights rule in ``game/ui/CLAUDE.md``)."""
        text_id = spec.get("text_id")
        label = spec.get("label")
        if not text_id and not label:
            return
        text = strings.T(text_id) if text_id else (label or "")
        if not text:
            return
        from .widgets import C_UI_TEXT
        font = spec.get("font") or defaults.get("font") or "md"
        # UH-Font-B: the family resolves down the SAME chain as the size
        # preset one line up -- widget override, then the screen's defaults,
        # then None, which `get_font` reads as "the active family". A screen
        # doc with neither key draws exactly as it did before the axis
        # existed.
        family = spec.get("font_family") or defaults.get("font_family") or None
        color = _as_tuple(spec.get("text_color")
                          or defaults.get("text_color") or C_UI_TEXT)
        x, y, w, h = rect
        if center:
            # layout_h, never a family-aware measurement: this y lands in a
            # captured primitive stream, and the family axis is deliberately
            # absent from the pinned heights (engine/render/fonts.py).
            text_h = layout_h(font)
            renderer.submit_hud(HudText(text, (x + w / 2, y + h / 2 - text_h / 2),
                                        font, color, align="center",
                                        family=family))
            return
        renderer.submit_hud(HudText(text, (x, y), font, color,
                                    align=spec.get("align") or "left",
                                    family=family))

    def _submit_one_layer(self, renderer, resolved, state: str = "idle",
                          anim_ms: int = 0) -> None:
        """Emit the ONE primitive a resolved layer describes.

        ``state``/``anim_ms`` reach the sprite branch only: a layer sheet is
        addressed by the SAME four-state row vocabulary its owner resolves
        through, on the owning screen's clock. The manifest falls back to
        ``idle`` for a row a sheet does not carry, so a partial sheet is fine.

        A layer picks ONE role — this precedence is a design decision, not an
        accident of iteration order. Checked in this exact order, FIRST MATCH
        WINS, and a layer matching none of them draws nothing:

        1. ``slot``       -> ``HudSprite`` (an imported sheet beats everything)
        2. ``text_id``/``label`` -> ``HudText`` (resolved through
           ``strings.T`` exactly like ``widgets.submit_label``; an empty
           resolved string draws nothing, never a blank ``HudText``)
        3. ``color``      -> ``HudRect`` (the plain flat-fill fallback)
        4. nothing        -> skip
        """
        x, y, w, h = resolved["rect"]
        slot = resolved.get("slot")
        if slot:
            renderer.submit_hud(HudSprite(slot, (x, y), (w, h),
                                          animation=state,
                                          anim_time_ms=anim_ms,
                                          tint=resolved.get("tint")))
            return
        text_id = resolved.get("text_id")
        label = resolved.get("label")
        if text_id or label:
            text = strings.T(text_id) if text_id else (label or "")
            if not text:
                return
            # Fallbacks are the label-holder defaults (``widgets.label_holder``
            # / ``submit_label``), not new constants — imported lazily because
            # ``widgets`` imports this module.
            from .widgets import C_UI_TEXT
            renderer.submit_hud(HudText(
                text, (x, y), resolved.get("font") or "md",
                resolved.get("text_color") or C_UI_TEXT,
                align=resolved.get("align") or "left",
                family=resolved.get("font_family") or None))
            return
        color = resolved.get("color")
        if color:
            renderer.submit_hud(HudRect((x, y, w, h), color))

    def _widgets_spec(self, screen_id):
        override = self._overrides.get(screen_id)
        return (override or {}).get("widgets") or {}

    def _validate_ids(self, screen_id, widgets_spec):
        """Fail loud on an unknown widget id (catches a renamed/typo'd id) —
        but ONLY once ``screen_defaults.json`` exists AND names this screen
        (§1.4); before B3 lands, or for a screen it hasn't covered yet, every
        id is accepted silently.

        A DESIGNER-AUTHORED custom widget is known too. Its overrides live
        under ``widgets/<id>`` like any other widget's, but by construction
        it has no ``screen_defaults.json`` record (no code owns it), so
        without this every screen carrying one would raise at load."""
        if not widgets_spec:
            return
        defaults = self._defaults or {}
        known = ((defaults.get(screen_id) or {}).get("widgets") or {})
        if not known:
            return
        known = set(known) | set(self.custom_widgets(screen_id))
        unknown = set(widgets_spec) - set(known)
        if unknown:
            raise ValueError(
                f"screen {screen_id!r}: unknown widget id(s) "
                f"{sorted(unknown)} — known ids: {sorted(known)}")
