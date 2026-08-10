"""Wall-era-art sync (wall-hp-boost/wall-era-art feature pair).

Mirrors ``game/core/lightning.py``'s ``sync_level_from_tier``/
``unlock_from_placement`` shape exactly: a pure, DUCK-TYPED helper called from
``game/ui/building_ui.py`` at placement and every upgrade/tier-advance, so a
WallBuilder's art era is stamped there and nowhere else. Never called on a
bare round tick — a wall's look changes only when the WallBuilder itself is
upgraded, per the user's explicit design decision (never live off the round
clock).

Pure Python (no pygame); imports only ``engine.era_math``, never
``game.buildings`` — the same "core reaches down, buildings never reach up"
direction ``lightning.py`` already holds.
"""
from engine import era_math


def sync_wall_art_era(state, building, enemies_balance):
    """Freeze the CURRENT global era onto ``building``'s wall art, iff it is
    a WallBuilder (duck-typed via ``hasattr(building, "stamp_era")`` — no
    type-string check, the same G-3 discipline ``lightning.py``'s tag checks
    follow). No-op for every other building type. The era clock is the SAME
    one ``game/enemies`` uses (``EnemyScaling.rounds_per_era``) rather than a
    parallel buildings-side config, so "era" means one thing across the whole
    game."""
    stamp_era = getattr(building, "stamp_era", None)
    if stamp_era is None:
        return
    era = era_math.era_of_round(state.round_num,
                                enemies_balance["EnemyScaling"]["rounds_per_era"])
    stamp_era(era)
