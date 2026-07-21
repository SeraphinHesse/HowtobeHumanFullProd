"""Pure resolver: the ``(fit_tiles, scale)`` the GAME draws a slot at
(fix-editor-preview-footprint, ESV-2 follow-up). Stdlib + ``engine`` only —
Qt-free, pygame-free, in ``test_editor_viewport.TestPurity``'s import list.

**Why this exists**: `editor/panels/viewport.py` used to submit the entity
preview `RenderItem` — and derive the anchor handle's draw params — at the
dataclass defaults (`fit_tiles=0.0`, `scale=1.0`) regardless of what the
entity actually is, while the game draws an enemy at
`fit_tiles=float(EnemyTypes.<Type>.footprint)`,
`scale=float(EnemyTypes.<Type>.sprite_scale)` (`game/enemies/enemy.py`).
Where those disagree (`formation_stage_1`: game `s=0.5`, editor `s=1.0`) the
preview drew at the wrong size AND the anchor handle landed at the wrong
screen point — the same symptom `fix-anchor-origin-parity` closed for the
handle's ORIGIN, now closed for its SCALE.

**The editor may never import `game/` (D5)**, and the slot -> footprint
chain is otherwise expressible only in `game/enemies/enemy.py`'s Python
class constants (`REGISTRY_GROUP` + `STAT_SUBTREE`) — two of the five
`data/slots.json` enemies group labels do NOT match their
`data/balancing/enemies.json` `EnemyTypes` key by string convention
("Walker" -> "Standard", "Siege Cannon" -> "SiegeCannon"), so matching them
by name would be convention, not schema. `registry_group` (added to every
`EnemyTypes/<Type>` block, required) is that link expressed as DATA instead:
this module resolves a slot -> its top-level `data/slots.json` "enemies"
group label -> the `EnemyTypes` entry whose `registry_group` matches it.

Degrades to `(0.0, 1.0)` (the render defaults) for any slot with no
footprint concept (every non-enemy category today) and for anything
unresolvable (E-37) — this must never raise; the editor has to open on a
broken `data/` tree."""
from pathlib import Path

from editor.domains import balancing_path, schema_path
from engine import data_io
from engine.assets import load_registry

REPO = Path(__file__).resolve().parents[1]

DEFAULT_FIT = (0.0, 1.0)

_ENEMIES_CATEGORY = "enemies"


def _base(data_dir=None):
    return Path(data_dir) if data_dir is not None else REPO / "data"


def _enemy_registry_group(registry, slot_key):
    """The TOP-LEVEL `data/slots.json` "enemies" group label containing
    `slot_key` (e.g. "Formation") — a slot usually sits several levels
    deeper (an era child), but `REGISTRY_GROUP`/`registry_group` always
    names the top group. `None` when the category or the slot is absent."""
    try:
        category = registry.category(_ENEMIES_CATEGORY)
    except KeyError:
        return None
    for top in category.groups:
        try:
            slots = registry.group_slots(_ENEMIES_CATEGORY, (top.label,))
        except KeyError:
            continue
        if slot_key in slots:
            return top.label
    return None


def slot_draw_fit(data_dir, category_key, slot_key):
    """``(fit_tiles, scale)`` the GAME draws `slot_key` at — the values its
    `RenderItem` carries. `(0.0, 1.0)` for any slot with no footprint
    concept (every non-enemy category today) and for an unresolvable slot;
    never raises."""
    if category_key != _ENEMIES_CATEGORY:
        return DEFAULT_FIT
    base = _base(data_dir)
    try:
        registry = load_registry(base)
        group_label = _enemy_registry_group(registry, slot_key)
        if group_label is None:
            return DEFAULT_FIT
        enemies = data_io.load_validated(
            balancing_path("enemies", base), schema_path("enemies", base))
        for type_block in enemies["EnemyTypes"].values():
            if type_block.get("registry_group") == group_label:
                return (float(type_block["footprint"]),
                        float(type_block["sprite_scale"]))
    except Exception:
        return DEFAULT_FIT
    return DEFAULT_FIT
