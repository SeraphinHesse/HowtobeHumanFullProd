"""SD-4: game.sounds.GameSounds — the building + map trigger dispatcher.

Drives `GameSounds` DIRECTLY with a fake audio object that records every
`play_slot(default, override, bus=, key=, rng=)` call. No window, no
`game/main.py` boot, no live `data/` content — the balance dicts below are
pinned in-test.
"""
import random
import unittest

from game.buildings.components import Attacker
from game.sounds import BUILDING_KINDS, MAP_KINDS, GameSounds


def _slot(name):
    return {"clips": [{"file": name, "volume": 1.0, "start": 0.0, "end": 0.0}],
            "loop": False, "pick": "random"}


def _sounds_node(prefix):
    return {k: _slot("%s_%s.wav" % (prefix, k)) for k in BUILDING_KINDS}


# pinned fixture: the SD-1 shape, capital `Sounds` on the global node and
# lowercase `sounds` on the leaf families.
BUILDINGS = {
    "BuildingsGlobal": {"Sounds": _sounds_node("global")},
    "DefenceBuildings": {"BasicDefence": {"sounds": _sounds_node("basic")},
                         "AOEDefence": {}},
    "EconomyBuildings": {"Musicians": {"sounds": _sounds_node("musician")}},
}
MAP_BAL = {"Sounds": {k: _slot("map_%s.wav" % k) for k in MAP_KINDS}}


class FakeAudio:
    def __init__(self):
        self.calls = []

    def play_slot(self, default_slot, override_slot=None, *, bus="sfx",
                  key=None, rng=None, loop=None):
        self.calls.append({"default": default_slot, "override": override_slot,
                           "bus": bus, "key": key, "rng": rng})
        return True


class FakeBuilding:
    def __init__(self, subtree, *, building_type="basic", alive=True,
                 attacker=None):
        self.SUBTREE = subtree
        self.building_type = building_type
        self.alive = alive
        self._attacker = attacker

    def get_component(self, cls):
        return self._attacker if cls is Attacker else None


class FakeScene:
    def __init__(self, buildings):
        self._buildings = buildings

    def by_tag(self, tag):
        return list(self._buildings) if tag == "building" else []


class FakeTile:
    def __init__(self, occupant):
        self.occupant = occupant


class FakeTileMap:
    def __init__(self, cells):
        self._cells = cells

    def get(self, col, row):
        return self._cells.get((col, row))


class FakeState:
    def __init__(self, income_events=(), boost_events=()):
        self.income_events = list(income_events)
        self.boost_events = list(boost_events)


def _sounds(audio):
    return GameSounds(BUILDINGS, MAP_BAL, audio=audio,
                      rng=random.Random(1234))


class TestBuildingEvents(unittest.TestCase):
    def test_each_kind_plays_once_with_both_layers(self):
        for kind in BUILDING_KINDS:
            audio = FakeAudio()
            gs = _sounds(audio)
            gs.play_building_event(kind,
                                   FakeBuilding(("DefenceBuildings",
                                                 "BasicDefence")))
            self.assertEqual(len(audio.calls), 1, kind)
            call = audio.calls[0]
            self.assertEqual(call["default"],
                             BUILDINGS["BuildingsGlobal"]["Sounds"][kind])
            self.assertEqual(
                call["override"],
                BUILDINGS["DefenceBuildings"]["BasicDefence"]["sounds"][kind])
            self.assertEqual(call["bus"], "sfx")
            self.assertEqual(call["key"],
                             "buildings.BuildingsGlobal.Sounds." + kind)

    def test_family_without_sounds_still_calls_with_no_override(self):
        # the ENGINE owns the empty-clips rule: GameSounds must not skip.
        audio = FakeAudio()
        gs = _sounds(audio)
        gs.play_building_event("attack", FakeBuilding(("DefenceBuildings",
                                                       "AOEDefence")))
        self.assertEqual(len(audio.calls), 1)
        self.assertIn(audio.calls[0]["override"], (None, {}))
        self.assertEqual(audio.calls[0]["default"],
                         BUILDINGS["BuildingsGlobal"]["Sounds"]["attack"])

    def test_missing_global_and_unknown_subtree_do_not_crash(self):
        audio = FakeAudio()
        gs = GameSounds({}, {}, audio=audio)
        gs.play_building_event("death", FakeBuilding(("Nope", "Nope")))
        gs.play_building_event("death", None)
        self.assertEqual(len(audio.calls), 2)
        self.assertTrue(all(c["default"] is None for c in audio.calls))

    def test_case_split_is_load_bearing(self):
        # capital `Sounds` on the global, lowercase `sounds` on the leaf —
        # this assertion exists so the split cannot be silently "tidied".
        gs = _sounds(FakeAudio())
        b = FakeBuilding(("EconomyBuildings", "Musicians"))
        self.assertEqual(gs._family_sounds(b),
                         BUILDINGS["EconomyBuildings"]["Musicians"]["sounds"])
        self.assertEqual(gs._global_sounds(),
                         BUILDINGS["BuildingsGlobal"]["Sounds"])
        capitalised = {"BuildingsGlobal": {"sounds": _sounds_node("x")},
                       "EconomyBuildings": {"Musicians":
                                            {"Sounds": _sounds_node("y")}}}
        swapped = GameSounds(capitalised, {}, audio=FakeAudio())
        self.assertEqual(swapped._family_sounds(b), {})
        self.assertEqual(swapped._global_sounds(), {})


class TestMapEvents(unittest.TestCase):
    def test_each_map_kind_fires_once(self):
        audio = FakeAudio()
        gs = _sounds(audio)
        gs.play_map_event("buy_plot")
        gs.play_map_event("tile_placement")
        self.assertEqual([c["key"] for c in audio.calls],
                         ["map.Sounds.buy_plot", "map.Sounds.tile_placement"])
        self.assertEqual(audio.calls[0]["default"],
                         MAP_BAL["Sounds"]["buy_plot"])
        self.assertTrue(all(c["override"] is None for c in audio.calls))
        self.assertTrue(all(c["bus"] == "sfx" for c in audio.calls))


class TestWatch(unittest.TestCase):
    def test_death_fires_once_on_the_edge(self):
        audio = FakeAudio()
        gs = _sounds(audio)
        b = FakeBuilding(("DefenceBuildings", "BasicDefence"))
        scene = FakeScene([b])
        gs.watch(scene)
        self.assertEqual(audio.calls, [])
        b.alive = False
        gs.watch(scene)
        keys = [c["key"] for c in audio.calls]
        self.assertEqual(keys, ["buildings.BuildingsGlobal.Sounds.death"])
        gs.watch(scene)
        self.assertEqual(len(audio.calls), 1)

    def test_attack_fires_on_a_grown_cooldown_only(self):
        audio = FakeAudio()
        gs = _sounds(audio)
        at = Attacker(cooldown=0.5)
        b = FakeBuilding(("DefenceBuildings", "BasicDefence"), attacker=at)
        scene = FakeScene([b])
        gs.watch(scene)          # priming pass: no previous value
        at.cooldown = 0.2        # ticked DOWN: not a shot
        gs.watch(scene)
        self.assertEqual(audio.calls, [])
        at.cooldown = 1.0        # RESET (grew): a shot just landed
        gs.watch(scene)
        self.assertEqual([c["key"] for c in audio.calls],
                         ["buildings.BuildingsGlobal.Sounds.attack"])


class TestPayday(unittest.TestCase):
    def test_one_upkeep_boost_per_family(self):
        audio = FakeAudio()
        gs = _sounds(audio)
        fam = ("DefenceBuildings", "BasicDefence")
        tiles = {(0, 0): FakeTile(FakeBuilding(fam)),
                 (1, 0): FakeTile(FakeBuilding(fam)),
                 (2, 0): FakeTile(FakeBuilding(("EconomyBuildings",
                                                "Musicians")))}
        state = FakeState(income_events=[(0, 0, -3, "upkeep"),
                                         (1, 0, -3, "upkeep"),
                                         (2, 0, 7, "income")],
                          boost_events=[(2, 0, "+1")])
        gs.payday(state, FakeTileMap(tiles))
        self.assertEqual(len(audio.calls), 2)   # one per distinct family
        self.assertTrue(all(
            c["key"] == "buildings.BuildingsGlobal.Sounds.upkeep_boost"
            for c in audio.calls))
        self.assertEqual(
            audio.calls[0]["override"],
            BUILDINGS["DefenceBuildings"]["BasicDefence"]["sounds"]
            ["upkeep_boost"])


if __name__ == "__main__":
    unittest.main()
