"""Per-screen skin overrides (10L-B phase B2, plan lines 294-307).

Loads + schema-validates every ``data/ui/screens/*.json`` ONCE, at
``ScreenSkinning(data_dir)`` construction. ``apply(screen_id, ids)`` mutates a
screen's named widgets in place from the matching override — a pure in-memory
setattr loop, **zero disk I/O per call** — so a screen whose ``submit()`` calls
``layout()`` (and therefore ``apply()``) every frame (``cheat_menu.py``) never
re-reads a file. ``screen_background(screen_id)`` / ``submit_background(...)``
supply the optional whole-screen background override.

Pure (no pygame) — a plain setattr loop over widget objects, and the two HUD
primitives it may emit (``HudRect``/``HudSprite``) are pure dataclasses, the
same sanctioned import ``widgets.py`` already makes.

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

from engine import data_io
from engine.render import HudRect, HudSprite

_SCREENS_SUBDIR = ("ui", "screens")
_SCREEN_SCHEMA = "ui_screen.schema.json"
_DEFAULTS_FILE = ("ui", "screen_defaults.json")
_DEFAULTS_SCHEMA = "screen_defaults.schema.json"

#: JSON override key -> the widget attribute it mutates. Everything else
#: (rect/skin/label/color/text_color/visible/tint) maps 1:1 onto the same
#: name — ``tint`` (D6/UH-6, the sheet-multiply color for a skinned widget)
#: needs no entry here for exactly that reason: ``apply``'s generic setattr
#: loop already threads it onto the widget for free, the same way it always
#: has for ``skin``.
_SPEC_TO_ATTR = {"font": "font_key"}


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
        if not widgets_spec:
            return
        for name, (_kind, widget) in ids.items():
            spec = widgets_spec.get(name)
            if not spec:
                continue
            for key, value in spec.items():
                setattr(widget, _SPEC_TO_ATTR.get(key, key), _as_tuple(value))

    def defaults(self, screen_id: str) -> Dict[str, Any]:
        """The screen's ``defaults`` section (``button_skin``/``panel_skin``/
        ``font``/``text_color``), or ``{}`` when unset — the styling surface
        for DYNAMIC-count content that cannot carry a stable id (construct
        cards, the boss-history popup, levelup's option boxes, …; B3's
        "dynamic content inherits defaults" rule). Reads the already-in-memory
        override — no disk I/O, safe every frame/every construction."""
        override = self._overrides.get(screen_id)
        return (override or {}).get("defaults") or {}

    def screen_background(self, screen_id: str) -> Optional[Dict]:
        """``{"slot": ...}`` or ``{"color": (...)}`` for a submit-time
        background override, or ``None``. Reads the already-in-memory
        override — no disk I/O, safe every frame."""
        override = self._overrides.get(screen_id)
        bg = (override or {}).get("background") if override else None
        if not bg:
            return None
        if "color" in bg:
            return {"color": _as_tuple(bg["color"])}
        return {"slot": bg["slot"]}

    def submit_background(self, renderer, screen_id: str, view_w, view_h) -> None:
        """Draw the full-view background override (if any) — one call at the
        top of a screen's ``submit()``. A no-op with no ``background`` key
        (every shipped screen JSON today), so it never changes parity."""
        bg = self.screen_background(screen_id)
        if bg is None:
            return
        if "slot" in bg:
            renderer.submit_hud(HudSprite(bg["slot"], (0, 0), (view_w, view_h)))
        else:
            renderer.submit_hud(HudRect((0, 0, view_w, view_h), bg["color"]))

    # -- internal ----------------------------------------------------------

    def _widgets_spec(self, screen_id):
        override = self._overrides.get(screen_id)
        return (override or {}).get("widgets") or {}

    def _validate_ids(self, screen_id, widgets_spec):
        """Fail loud on an unknown widget id (catches a renamed/typo'd id) —
        but ONLY once ``screen_defaults.json`` exists AND names this screen
        (§1.4); before B3 lands, or for a screen it hasn't covered yet, every
        id is accepted silently."""
        if not widgets_spec:
            return
        defaults = self._defaults or {}
        known = ((defaults.get(screen_id) or {}).get("widgets") or {})
        if not known:
            return
        unknown = set(widgets_spec) - set(known)
        if unknown:
            raise ValueError(
                f"screen {screen_id!r}: unknown widget id(s) "
                f"{sorted(unknown)} — known ids: {sorted(known)}")
