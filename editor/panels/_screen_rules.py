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


def label_is_code_owned(screen_id, widget_id, kind):
    """True iff the game overwrites this widget's `.label` every frame with
    a live computed value, making an editor-authored `label` override dead
    on arrival (game/ui/hud.py's ~12 stable readouts; game/ui/CLAUDE.md).

    Rule, in order:
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
