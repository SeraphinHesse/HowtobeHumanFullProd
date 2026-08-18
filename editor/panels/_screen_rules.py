"""Pure "honest control" rules for screen mode (UH-3, plan decision D3: any
control that cannot take effect in the game must be disabled with an
explanatory tooltip, never silently accepted).

Qt-free, pygame-free — sibling in spirit to `editor.panels._screen_primitives`
(stdlib only). `screen_details.py` calls these to decide whether the Color
picker and the Label field should be enabled for the currently selected
widget; the module never touches Qt widgets itself.
"""

# -- skin resolution ---------------------------------------------------------

# A LITERAL mirror of editor/panels/viewport.py:924-929
# (`ViewportPanel._submit_screen_widget`'s skin resolution): per-widget
# `skin` override wins; else the screen doc's `defaults.button_skin` for
# kind == "button" / `defaults.panel_skin` for kind == "panel"; any other
# kind (or no default set) resolves to None (unskinned).
#
# DRIFT RISK: this is a deliberate duplication, not a shared import — UH-2
# owns viewport.py and UH-3 must not touch it. If viewport.py's resolution
# order ever changes, this copy goes stale and must be updated by hand.
def resolved_skin(spec, override, style):
    """The skin (a slot key) the widget currently renders with, or None if
    it renders through the flat-rect fallback. `spec` is the widget's entry
    from `data/ui/screen_defaults.json` (`{kind, label, rect}`); `override`
    is the screen doc's per-widget override dict; `style` is the screen
    doc's `defaults` dict."""
    skin = override.get("skin")
    if skin is None:
        kind = spec.get("kind")
        if kind == "button":
            skin = style.get("button_skin")
        elif kind == "panel":
            skin = style.get("panel_skin")
    return skin


# -- code-owned fill (color) resolution --------------------------------------

# Kinds for which the game NEVER reads a widget's `color` override, skinned
# or not — grounded in every color-consuming call site, not in the skin
# story alone (found by review: the brief's premise that unskinned
# panel/field fills read `.color` was false).
#
# `panel`: unlike buttons (`skinning.button_kwargs` generically forwards
# `.color`/`.text_color` for every id'd button), there is no `panel_kwargs`
# anywhere. Every `submit_panel(...)` call site passes a HARDCODED `fill=`
# regardless of the widget's own `.color`: `game/ui/cheat_menu.py:217`,
# `add_name.py:135`, `building_ui.py:239,932,1252`, `boss_cutscene.py:162`,
# `levelup.py:126`, `hud.py:313,345,438`. `hud.py`'s `love_panel` does not
# even call `submit_panel` — it is a raw `HudRect(pill, C_PANEL_STONE, ...)`
# (`hud.py:308`), ignoring skin AND color unconditionally. So `color` is
# dead on arrival for every `panel`-kind widget, with or without a skin.
# `field`: `cheat_menu.py`'s `round_field` draws a hardcoded
# `HudRect(self.field_rect, C_PANEL_STONE)` plus a hardcoded border
# (`cheat_menu.py:231-234`); no `.color` is ever read, and `resolved_skin`
# never resolves a skin for `field` either.
# `label`: every label-kind widget renders through `submit_centered(...,
# text_color)` only — `text_color` is genuinely live (the pink test
# exercises exactly that), but nothing ever reads a label's `.color`; there
# is no box to fill, on either side (`_screen_primitives.fallback_hud_items`
# draws no `HudRect` for `kind == "label"` either, `:58-60`). Conflating
# "no box to fill" with "the override still applies" was the bug — `color`
# is dead for `label` regardless of skin, exactly like `panel`/`field`.
#
# NOT in this set (verified live, do not add): `backdrop` — every screen's
# `_backdrop` reads `.color` directly (`HudRect(self._backdrop.rect,
# self._backdrop.color)`, e.g. `main_menu.py:107`, `add_name.py:132`,
# `boss_cutscene.py:134`, `credits.py:86`, `game_over.py:66`,
# `levelup.py:108`, `pause.py:92`, `settings.py:150`). `bar` — `hud.py`
# forwards `self._xp_bar.color` as `submit_bar`'s `bg=` (`hud.py:443`).
# `button` — `skinning.button_kwargs` forwards `.color` generically for
# every id'd button; `Button.submit`'s `fill = color or ...` reads it
# whenever unskinned (only a skin makes it dead, which `resolved_skin`
# already catches). That is the full six-kind split, no kind left
# unaccounted for: dead = `panel`/`field`/`label`, live = `button`/
# `backdrop`/`bar`.
_COLOR_DEAD_KINDS = frozenset({"panel", "field", "label"})


def color_is_code_owned(kind):
    """True iff the game hardcodes this widget kind's fill in game code and
    never reads a `color` override for it at all, independent of skin state
    (see `_COLOR_DEAD_KINDS` for the call-site citations). Callers combine
    this with `resolved_skin` — a widget can be dead for either reason."""
    return kind in _COLOR_DEAD_KINDS


# -- code-owned label resolution ---------------------------------------------

# Pinned static-title exceptions (game/ui/CLAUDE.md, the main_menu.py:56-58
# pattern): a `label`-kind widget whose text a *screen* module writes as a
# fixed string at construction time, not a per-frame computed game-state
# value. Extend ONLY with a `file:line` citation proving the game draws that
# holder's `.label` — anything unproven stays disabled (disabling a static
# label is a smaller lie than enabling a dead one).
_STATIC_TITLE_IDS = frozenset({
    ("main_menu", "title"),
    ("main_menu", "subtitle"),
    ("pause", "title"),
    ("settings", "title"),
    ("credits", "title"),
    ("game_over", "title"),
    ("add_name", "title"),
})


def label_is_code_owned(screen_id, widget_id, kind, text_id=None):
    """True iff the game overwrites this widget's `.label` every frame with
    a live computed value, making an editor-authored `label` override dead
    on arrival (game/ui/hud.py's ~12 stable readouts; game/ui/CLAUDE.md).

    Rule, in order:
    0. a `text_id` -> False (UT-1/UT-3). The widget resolves its text through
       `data/ui/strings.json`, so the text IS designer-owned — the panel shows
       the TEMPLATE rather than the per-widget `label` override. This is the
       rule that retired most of this function's reach: before it, every
       dynamic readout was disabled with "edit it in game code, not here".
    1. `kind == "button"` -> False (editable; `game/ui/widgets.py:246-266`
       draws `self.label`, and `ScreenSkinning.apply` runs after layout so
       an override wins).
    2. `kind == "label"` -> False iff `(screen_id, widget_id)` is a pinned
       static title (`_STATIC_TITLE_IDS`), else True (dynamic HUD readout).
    3. any other kind (`panel`/`backdrop`/`bar`/`field`) -> True: the game
       draws no holder label for panels/backdrops (`submit_panel` takes no
       label, `game/ui/widgets.py:108-119`), `bar` text is live state, and
       `field` content is user-typed at runtime.
    """
    if text_id:
        return False
    if kind == "button":
        return False
    if kind == "label":
        return (screen_id, widget_id) not in _STATIC_TITLE_IDS
    return True


# -- tooltips -----------------------------------------------------------------
# Module-level so UH-6 can retarget exactly ONE symbol when it repurposes the
# Color control as Tint on skinned buttons. Keep both names stable.

TOOLTIP_COLOR_SKINNED = (
    "Colors come from the sprite sheet — this widget renders a skin. "
    "Clear the skin (or the screen's default skin) to color the flat "
    "fallback."
)

TOOLTIP_LABEL_CODE_OWNED = (
    "This text is written by game code at runtime — edit it in game code, "
    "not here."
)

TOOLTIP_COLOR_CODE_OWNED = (
    "This widget's fill is hardcoded in game code — a color override has "
    "nothing to apply to here."
)


# -- UL-13: designer-authored CUSTOM widgets ---------------------------------
# A screen doc's optional `custom_widgets` table (data/schemas/
# ui_screen.schema.json) holds widgets no code owns. Each entry is the
# widget's DEFAULT GEOMETRY ONLY (`kind` + `rect`, plus the authoring-only
# `band`/`z`/`display_name`) — the designer-authored twin of ONE
# `data/ui/screen_defaults.json` widget entry. Everything paintable (skin,
# color, label, text_id, font, text_color, tint, align, visible, parent,
# layers, states) is an ORDINARY override under `widgets/<the same id>`,
# exactly as for a code-owned widget.
#
# That split is what makes the editor side cheap: fold the custom entries
# into the code-owned default map ONCE, here, and the outliner, the
# hit-test/drag, the per-field form and its reset buttons, `widget_tree`
# parenting and the layer machinery all keep working untouched.

def merge_custom_widgets(defaults_widgets, custom_widgets):
    """`defaults_widgets` (a screen's `screen_defaults.json` widget map) plus
    one synthetic default entry per `custom_widgets` id — the ONE definition
    of "what widgets exist on this screen" the viewport and the details panel
    both read, so they cannot disagree.

    A synthetic entry carries `{kind, rect, label: ""}` (+ `display_name`
    when the designer set one): the same shape the exporter writes, so every
    consumer of a default spec keeps working. `band`/`z` are deliberately NOT
    copied in — they are authoring metadata about PAINT ORDER, not part of a
    widget spec, and the drawing code reads them off the table itself.

    **A code-owned id WINS.** The session's add guard refuses to create a
    custom id that collides with one, so this can only be reached by a
    hand-edited doc; shadowing the real widget would hide the thing the game
    actually draws, which is the worse of the two lies.

    Returns `defaults_widgets` UNCHANGED (the same object) when there are no
    custom widgets — the overwhelmingly common path, called a few times per
    frame.
    """
    if not custom_widgets:
        return defaults_widgets
    merged = dict(defaults_widgets or {})
    for widget_id, entry in custom_widgets.items():
        if widget_id in merged or not isinstance(entry, dict):
            continue
        spec = {"kind": entry.get("kind"),
                "rect": list(entry.get("rect") or (0, 0, 0, 0)),
                "label": ""}
        if entry.get("display_name"):
            spec["display_name"] = entry["display_name"]
        merged[widget_id] = spec
    return merged


def is_custom(widget_id, custom_widgets):
    """True iff this id is designer-authored (in the screen doc's
    `custom_widgets` table) rather than code-owned. The ONE predicate the
    panel's enable/disable gating asks, so no call site re-derives it."""
    return bool(custom_widgets) and widget_id in custom_widgets


def custom_widgets_in_band(custom_widgets, band):
    """`[(id, entry), ...]` for the custom widgets drawn in `band`, ascending
    `z` — a LITERAL mirror of `game/ui/skinning.py::_custom_in_band` (absent
    band == "over", absent z == 0, `sorted` stable so authoring order is the
    tie-break). Duplicated rather than imported: `editor/` may never import
    `game/`, the same accepted drift `_screen_primitives` records."""
    if not custom_widgets:
        return []
    rows = [(name, entry) for name, entry in custom_widgets.items()
            if isinstance(entry, dict) and (entry.get("band") or "over") == band]
    return sorted(rows, key=lambda pair: pair[1].get("z") or 0)


# -- honest controls for a CUSTOM widget -------------------------------------
# `color_is_code_owned`/`label_is_code_owned` above answer for CODE-OWNED
# widgets, by citing what game code does at each holder's draw site. A custom
# widget has no such site: `skinning._submit_custom_widget` draws it, and its
# precedence is fixed and known, so the two questions get their own (much
# smaller) answers here rather than special cases inside those functions.

def custom_color_is_code_owned(kind):
    """True iff a custom widget of this kind never reads a `color` override.
    Only `label` — it draws text and no box at all. `panel`/`backdrop` fall
    back to `color` -> `HudRect` whenever no skin resolves."""
    return kind == "label"


def custom_label_is_code_owned(kind):
    """True iff a custom widget of this kind draws no text. Only `backdrop`
    (`_submit_custom_widget` gives it a box and no caption); a `panel` gets a
    centred caption and a `label` IS the text."""
    return kind == "backdrop"


def custom_tint_applies(kind):
    """True iff a SKINNED custom widget of this kind threads `tint` into its
    sprite — `panel`/`backdrop`, the two kinds that draw a `HudSprite` at
    all."""
    return kind in ("panel", "backdrop")
