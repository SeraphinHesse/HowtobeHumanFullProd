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
    "add_name.hint": "Appears on the building-naming dice button.",
    "add_name.msg_added": "Added '{name}'!",
    "add_name.msg_duplicate": "'{name}' is already in the list.",
    "add_name.msg_empty": "Type a name first.",
    "add_name.placeholder": "type a name...",
    "add_name.pool_count": "Names in pool: {count}",
    "boss_cutscene.box_label": "{prefix}{option}",
    "boss_cutscene.headline_loss": "Cutscene: Round Lost :(",
    "boss_cutscene.headline_win": "Cutscene: Round Won :)",
    "boss_cutscene.prefix_loss": "Loss",
    "boss_cutscene.prefix_win": "Win",
    "building.action.advance": "ADVANCE: {name}  {cost}",
    "building.action.max_tier": "MAX TIER",
    "building.action.not_adjacent": "NOT ADJACENT",
    "building.action.research": "RESEARCH REQUIRED",
    "building.action.tier_locked": "NEXT TIER LOCKED",
    "building.action.unlock": "UNLOCK  {cost}",
    "building.action.unlock_many": "UNLOCK {n} AREAS  {cost}",
    "building.action.upgrade": "UPGRADE  {cost}",
    "building.action.upgrade_many": "UPGRADE ×{n}  {cost}",
    "building.base_info.base_income": "Base income",
    "building.base_info.buildings": "Buildings",
    "building.base_info.enemies_killed": "Enemies killed",
    "building.base_info.income_value": "{amount}/round",
    "building.base_info.lives": "Lives",
    "building.base_info.title": "THE HOLE",
    "building.base_info.wave": "Wave",
    "building.boss.none_yet": "None yet",
    "building.boss.row": "Boss {n}: {outcome} {option}",
    "building.boss.title": "Boss Choices",
    "building.btn.boss_choices": "BOSS CHOICES",
    "building.btn.boss_close": "CLOSE",
    "building.btn.cancel": "CANCEL",
    "building.btn.close": "X",
    "building.btn.confirm": "CONFIRM",
    "building.btn.dice": "⚄",
    "building.btn.move": "MOVE BUILDING",
    "building.btn.move_blocked": "CANNOT BE MOVED",
    "building.construct.card": "{name}  {cost}",
    "building.construct.title": "BUILD",
    "building.flash.cannot_move": "CANNOT MOVE THERE",
    "building.flash.not_enough_love": "NOT ENOUGH LOVE",
    "building.flash.painter_tile_used": "ALREADY PAINTED HERE",
    "building.hint.research": "Research it on levelup",
    "building.hint.tier_locked": "Unlocks at round {round}",
    "building.hint.tier_unoffered": "Not yet offered",
    "building.hint.wall_rooted": "A wall builder is rooted to its tile",
    "building.log.moved": "Building moved",
    "building.log.moving": "Building moving — {rounds} rounds",
    "building.log.unlock_refused": "Can only unlock tiles touching your territory",
    "building.move.hint_1": "Cost and time grow with",
    "building.move.hint_2": "the distance moved.",
    "building.move.hint_cancel": "Click the panel to cancel.",
    "building.move.pick_tile": "Pick a highlighted tile",
    "building.move.title": "MOVE BUILDING",
    "building.move_preview.cost": "Cost  {cost}",
    "building.move_preview.cost_free": "Cost  Free",
    "building.move_preview.dest": "to ({col}, {row})",
    "building.move_preview.time": "Time  {rounds} {unit}",
    "building.move_preview.time_instant": "Time  Instant",
    "building.preview.click_to_name": "click to name",
    "building.preview.cost": "Cost  {cost}",
    "building.preview.name_label": "Name:",
    "building.preview.title_batch": "{name}  × {count}",
    "building.preview.unnamed": "Unnamed {title}",
    "building.stat.atk_speed": "Atk speed",
    "building.stat.atk_speed_base": "Atk speed base",
    "building.stat.boost": "Boost/turn",
    "building.stat.boost_damage": "Dmg boost/turn",
    "building.stat.boost_hp": "HP boost/turn",
    "building.stat.boost_speed": "Spd boost/turn",
    "building.stat.damage": "Damage",
    "building.stat.damage_base": "Damage base",
    "building.stat.hp": "HP",
    "building.stat.hp_base": "HP base",
    "building.stat.payout": "Payout",
    "building.stat.pays_in": "Pays in",
    "building.stat.progress": "Progress",
    "building.stat.range": "Range",
    "building.stat.streak": "Streak",
    "building.stat.upkeep": "Upkeep",
    "building.stat.value": "{value}",
    "building.stat.wall_hp": "Wall HP",
    "building.stat.yield": "Yield",
    "building.terrain_badge": "Terrain: {label}",
    "building.unlock.hint": "Unlocks a 2x2 area",
    "building.unlock.not_adjacent": "Must touch your territory",
    "building.unlock.title": "UNLOCK TILE",
    "building.upgrade.died_last_round": "DIED LAST ROUND",
    "building.upgrade.dmg_dealt": "Damage dealt",
    "building.upgrade.dmg_taken": "Damage taken",
    "building.upgrade.name_placeholder": "click here to change name",
    "building.upgrade.next_tier": "Next: {name}",
    "building.upgrade.next_tier_row": "{label}  {value}",
    "building.upgrade.tier_level": "{tier} — Level {level}",
    "cheat_menu.round_placeholder": "round",
    "credits.name": "{name}",
    "credits.role": "{role}",
    "effects.announce_line1": "SOMETHING BIG",
    "effects.announce_line2": "IS APPROACHING!",
    "effects.boss_bar_hp": "{hp}/{max_hp}",
    "effects.boss_bar_label": "BOSS",
    "effects.floater_gain": "+{amount}",
    "effects.floater_loss": "{amount}",
    "effects.floater_xp": "+{amount}",
    "game_log.building_killed": "{name} has been killed",
    "game_over.buildings_placed": "Buildings Placed: {count}",
    "game_over.enemies_killed": "Enemies Killed: {count}",
    "game_over.round_reached": "Round Reached: {n}",
    "hud.income.base": "Base",
    "hud.income.meditators": "Meditators",
    "hud.income.musicians": "Musicians",
    "hud.income.story": "Story",
    "hud.income.upkeep": "Upkeep",
    "hud.income_net": "{sign}{net}/round",
    "hud.level": "LVL {n}",
    "hud.lightning_cooldown": "⚡ {seconds}s",
    "hud.lightning_ready": "⚡ CLICK TO STRIKE",
    "hud.lives": "LIVES {count}",
    "hud.love_display": "{amount}",
    "hud.love_unaffordable": "-",
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
    "levelup.cost_paid": "{label}  {cost}",
    "levelup.heading": "CHOOSE YOUR REWARD",
    "levelup.tier_progress": "Tier {tier_no} of {tier_max}",
    "settings.display_mode": "Display Mode",
    "settings.master_audio": "Master Audio",
    "settings.no_audio": "(no audio yet)",
    "settings.toggle.bg_art": "Background Art",
    "settings.toggle.gore": "Gore",
    "settings.toggle.income_floaters": "Income Floaters",
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
