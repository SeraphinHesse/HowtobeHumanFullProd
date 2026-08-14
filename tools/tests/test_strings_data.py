"""Phase C: data/ui/strings.json + game/ui/strings.py.

Mirrors tools/tests/test_theme_data.py's shape (D5's fonts/palette pin) for
the new string table: the unconfigured module defaults must equal the
fixture stock content, configuring from that fixture must be a no-op, and a
key-set mismatch must fail loud. Never reads live data/ui/strings.json in an
assertion — the fixture dict below pins TODAY's values independently of the
live file (house rule, tools/tests/test_fixture_guard.py).

Every test that calls configure_strings MUST addCleanup-restore the
module's unconfigured state — it mutates a module global, and a leaked
configure poisons any later test in the same process."""
import unittest

from game.ui import strings
from tools.tests.test_ui_skinning import _BASELINE, _screen_captures

# The stock values (Phase C) — verbatim from game/ui/strings.py's _STRINGS at
# the time data/ui/strings.json was authored. Hardcoded here (not read from
# the live file) so this module never depends on data/ content, per house
# rule.
_FIXTURE_STRINGS = {
    "add_name.hint": "Appears on the building-naming dice button.",
    "add_name.msg_added": "Added '{name}'!",
    "add_name.msg_duplicate": "'{name}' is already in the list.",
    "add_name.msg_empty": "Type a name first.",
    "add_name.placeholder": "type a name...",
    "add_name.pool_count": "Names in pool: {count}",
    "boss_cutscene.box_label": "{prefix}{option}",
    "boss_cutscene.headline_loss": "Cutscene: Round Lost :(",
    "boss_cutscene.headline_loss_reward":
        "Cutscene: Round Lost :(  +{love} love",
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
    "building.move_preview.cost": "Cost  {rounds} {unit}",
    "building.move_preview.cost_instant": "Cost  Instant",
    "building.move_preview.dest": "to ({col}, {row})",
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


def _snapshot():
    return dict(strings._STRINGS)


def _restore(snapshot):
    strings._STRINGS.clear()
    strings._STRINGS.update(snapshot)


class _ConfigureMixin:
    def _protect_module_state(self):
        snapshot = _snapshot()
        self.addCleanup(_restore, snapshot)
        return snapshot


class TestFallbackEqualsStock(unittest.TestCase):
    """The unconfigured module defaults (bare test/tool construction, the
    fonts.py/configure_palette precedent) must equal the fixture stock
    content — kills silent dual-store drift between the Python literal and
    the JSON content it mirrors."""

    def test_strings_default_equal_fixture(self):
        self.assertEqual(set(strings._STRINGS), set(_FIXTURE_STRINGS))
        for key, template in _FIXTURE_STRINGS.items():
            self.assertEqual(strings._STRINGS[key], template,
                             f"string id {key!r} drifted from its data fixture")


class TestConfigureStrings(_ConfigureMixin, unittest.TestCase):
    def test_configuring_stock_fixture_is_a_no_op(self):
        self._protect_module_state()
        strings.configure_strings(_FIXTURE_STRINGS)
        for key, template in _FIXTURE_STRINGS.items():
            self.assertEqual(strings._STRINGS[key], template)

    def test_configure_rebinds_in_place(self):
        self._protect_module_state()
        strings.configure_strings({**_FIXTURE_STRINGS,
                                   "hud.phase.building": "CONSTRUCTION"})
        self.assertEqual(strings.T("hud.phase.building"), "CONSTRUCTION")

    def test_missing_key_raises(self):
        self._protect_module_state()
        bad = dict(_FIXTURE_STRINGS)
        del bad["hud.phase.building"]
        with self.assertRaises(ValueError):
            strings.configure_strings(bad)

    def test_unknown_key_raises(self):
        self._protect_module_state()
        bad = {**_FIXTURE_STRINGS, "hud.phase.unknown_phase": "??"}
        with self.assertRaises(ValueError):
            strings.configure_strings(bad)


class TestStockParityPin(_ConfigureMixin, unittest.TestCase):
    """The crux (mirrors test_theme_data.py's TestStockParityPin): configuring
    from the STOCK fixture doc must reproduce exactly today's rendering — the
    golden baseline never moves. If this goes red, the phase is wrong, not
    the pin."""

    def test_stock_doc_reproduces_golden_baseline(self):
        self._protect_module_state()
        strings.configure_strings(_FIXTURE_STRINGS)
        captured = _screen_captures()
        self.assertEqual(set(captured), set(_BASELINE))
        for screen_id, items in captured.items():
            self.assertEqual(items, _BASELINE[screen_id],
                             f"{screen_id} drifted under stock string data")


class TestTFormats(unittest.TestCase):
    """T() substitutes kwargs via str.format over the CURRENT template —
    proves the plumbing every call site (hud.py, widgets.cond_label,
    levelup.py, boss_cutscene.py) relies on."""

    def test_no_placeholder_returns_verbatim(self):
        self.assertEqual(strings.T("hud.phase.building"), "BUILDING")

    def test_placeholder_substitution(self):
        self.assertEqual(
            strings.T("hud.lives", count=3), "LIVES 3")
        self.assertEqual(
            strings.T("hud.tiles", built=0, unlocked=4), "0/4 tiles")
        self.assertEqual(
            strings.T("hud.income_net", sign="+", net=5), "+5/round")
        self.assertEqual(
            strings.T("levelup.cost_paid", label="Cost", cost=5), "Cost  5")


if __name__ == "__main__":
    unittest.main()
