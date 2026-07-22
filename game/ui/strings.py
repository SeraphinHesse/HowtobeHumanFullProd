"""Global UI string table (Phase C) — a module-level cache + configure()
pattern mirroring ``engine/render/fonts.py``'s ``_FONT_SPECS``/
``configure_fonts`` and ``game/ui/widgets.py``'s ``configure_palette``.

Phase B (``game/ui/skinning.py``'s ``ScreenSkinning.apply()``) already made
every per-widget ``label`` override real for text that is exactly ONE FIXED
string per STATIC id'd widget (a screen's title, a button's caption). This
module covers what that mechanism structurally cannot: text that varies by
runtime/enum state (the phase banner, a win/loss headline) or is BUILT FROM A
TEMPLATE with live values (``"LIVES {count}"``, ``"ROUND {n}"``) — there is no
single fixed string to attach to a widget id for those.

``_STRINGS`` is seeded with today's literal text so an unconfigured import
(bare test/tool construction) still renders byte-identical output — the same
"unconfigured module defaults equal the shipped fixture content" precedent
``fonts.py``/``widgets.configure_palette`` establish. ``configure_strings``
rebinds it IN PLACE from a loaded ``data/ui/strings.json`` doc (called at
boot, ``game/main.py``, alongside fonts.json/palette.json). Every call site
resolves text via ``T(string_id, **kwargs)`` — never indexes ``_STRINGS``
directly — so there is no C_*-style early-binding trap to guard against here:
nothing outside this module holds a reference to a stale value, only to the
function.
"""

_STRINGS = {
    "boss_cutscene.headline_loss": "Cutscene: Round Lost :(",
    "boss_cutscene.headline_win": "Cutscene: Round Won :)",
    "hud.income.base": "Base",
    "hud.income.meditators": "Meditators",
    "hud.income.musicians": "Musicians",
    "hud.income.story": "Story",
    "hud.income.upkeep": "Upkeep",
    "hud.income_net": "{sign}{net}{heart}/round",
    "hud.level": "LVL {n}",
    "hud.lightning_cooldown": "⚡ {seconds}s",
    "hud.lightning_ready": "⚡ CLICK TO STRIKE",
    "hud.lives": "LIVES {count}",
    "hud.love_display": "{heart} {amount}",
    "hud.love_unaffordable": "{heart} -",
    "hud.phase.boss_cutscene": "CUTSCENE",
    "hud.phase.building": "BUILDING",
    "hud.phase.enemy": "COMBAT!",
    "hud.phase.income": "PAYDAY",
    "hud.phase.levelup": "LEVEL UP",
    "hud.phase.round_end": "REBUILDING",
    "hud.round": "ROUND {n}",
    # TU-9: shown instead of hud.round during the tutorial's round 0.
    "hud.round_tutorial": "Tutorial",
    "hud.tiles": "{built}/{unlocked} tiles",
    "hud.tooltip_income": "{label}: +{amount}",
    "hud.tooltip_story": "Story upgrades: +{amount}",
    "hud.tooltip_upkeep": "Upkeep: {amount}",
    "hud.xp_progress": "{current}/{threshold}",
    "levelup.cost_free": "FREE",
    "levelup.cost_paid": "{label}  {heart}{cost}",
    "levelup.heading": "CHOOSE YOUR REWARD",
    "levelup.tier_progress": "Tier {tier_no} of {tier_max}",
    "widgets.condition.forest": "Forest",
    "widgets.condition.grass": "Grass",
    "widgets.condition.mountain": "Mountain",
    "widgets.condition.pond": "Pond",
}


def configure_strings(doc):
    """Replace ``_STRINGS``'s entries IN PLACE from a loaded
    ``data/ui/strings.json`` doc (``{string_id: template}``) — mirrors
    ``engine.render.fonts.configure_fonts`` / ``game.ui.widgets.
    configure_palette``. The HOST (``game/main.py``) loads + schema-validates
    the file and passes the plain dict, so this module stays data-dir-free
    (bare construction — tests/tools — never needs a ``data/`` tree).

    Fails loud on a key-set mismatch (same "no silent break" argument as
    ``configure_fonts``/``configure_palette``): a renamed/dropped id would
    otherwise leave some ``T()`` call reading stale or missing text instead
    of raising."""
    unknown = set(doc) - set(_STRINGS)
    missing = set(_STRINGS) - set(doc)
    if unknown or missing:
        raise ValueError(
            f"strings.json key set mismatch: missing {sorted(missing)}, "
            f"unknown {sorted(unknown)}")
    for key, value in doc.items():
        _STRINGS[key] = value


def T(string_id, **kwargs):
    """Resolve ``string_id`` to its current (possibly templated) text,
    substituting ``kwargs`` via ``str.format`` — the ONE way any call site
    reads a string-table entry (never index ``_STRINGS`` directly, so a
    later ``configure_strings`` rebind always reaches every caller). The
    placeholders a given id's template accepts are documented per-property
    in ``data/schemas/strings.schema.json``."""
    return _STRINGS[string_id].format(**kwargs)
