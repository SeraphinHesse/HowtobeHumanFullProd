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

**Per-era fits (BR-1/BR-5)**: the Boss is the ONE enemy type whose
`footprint`/`sprite_scale` are NOT flat at its `EnemyTypes` root — BR-1 moved
them into its per-era `stats[]` rows, so a flat read raised `KeyError` and
every `boss_era_*` preview silently degraded to `(0.0, 1.0)`. `_type_fit`
resolves either shape, and the era index comes from the slot's position among
its top group's CHILD groups ("Era 0" is child 0), which is the same
index-alignment `data/slots.json` and the `stats[]` array already share. The
game's own seam for this is `game/enemies/enemy.py`'s `Enemy.resolve_fit`
classmethod — deliberately NOT imported: `editor/` may never import `game/`
(D5), which is the whole reason `registry_group` exists as data.

Degrades to `(0.0, 1.0)` (the render defaults) for any slot with no
footprint concept (every non-enemy category today) and for anything
unresolvable (E-37) — this must never raise; the editor has to open on a
broken `data/` tree. **The safety net wraps the two LOADS only**, not the
resolution below them: a bare `except Exception` around everything is exactly
what swallowed the BR-1 `KeyError` for four phases, so the resolution path is
written to be total instead (explicit membership tests, no indexing that can
raise) and any exception it does throw is a real bug that must be loud."""
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


def _era_index(registry, group_label, slot_key):
    """Which era subgroup of `group_label` holds `slot_key` — 0 for the first
    child group, 1 for the second, … (the enemies tree is one child group per
    era, in era order, and `EnemyTypes.Boss.stats` is index-aligned with it).
    0 when the group has no children (a flat leaf group) or the slot is not
    found under any of them."""
    try:
        group = registry.group(_ENEMIES_CATEGORY, (group_label,))
    except KeyError:
        return 0
    for index, child in enumerate(group.children):
        try:
            slots = registry.group_slots(
                _ENEMIES_CATEGORY, (group_label, child.label))
        except KeyError:
            continue
        if slot_key in slots:
            return index
    return 0


def _type_fit(type_block, era):
    """`(footprint, sprite_scale)` off one `EnemyTypes/<Type>` block.

    PER-ERA for every type, in one of two places: an era-shaped type carries
    the pair in its `eras[]` rows, and the Boss — which has no `eras` — in its
    own `stats[]` rows (BR-1). Both clamp to the last authored row, exactly as
    `game`'s `Enemy.resolve_fit` does (endgame_scaling carries no factor for
    either key, so a clamp is the whole story past the table).

    The block root is still read as a last resort, so a hand-built or older
    document that kept them flat resolves instead of silently falling back to
    the render defaults — which is the shape of the BR-5 bug this function
    exists to prevent. Total by construction: an unexpected shape returns the
    defaults rather than raising, and nothing here can `KeyError`."""
    row = type_block
    for key in ("eras", "stats"):
        rows = type_block.get(key)
        if isinstance(rows, list) and rows:
            row = rows[min(max(int(era), 0), len(rows) - 1)]
            break
    if not isinstance(row, dict):
        return DEFAULT_FIT
    if "footprint" not in row or "sprite_scale" not in row:
        return DEFAULT_FIT
    return float(row["footprint"]), float(row["sprite_scale"])


def slot_draw_fit(data_dir, category_key, slot_key):
    """``(fit_tiles, scale)`` the GAME draws `slot_key` at — the values its
    `RenderItem` carries. `(0.0, 1.0)` for any slot with no footprint
    concept (every non-enemy category today) and for an unresolvable slot;
    never raises."""
    if category_key != _ENEMIES_CATEGORY:
        return DEFAULT_FIT
    base = _base(data_dir)
    # E-37: the editor must open on a broken/absent data tree. Only the two
    # LOADS are tolerated — see the module docstring on why the resolution
    # below deliberately sits outside this net.
    try:
        registry = load_registry(base)
        enemies = data_io.load_validated(
            balancing_path("enemies", base), schema_path("enemies", base))
    except Exception:
        return DEFAULT_FIT
    group_label = _enemy_registry_group(registry, slot_key)
    if group_label is None:
        return DEFAULT_FIT
    for type_block in enemies.get("EnemyTypes", {}).values():
        if type_block.get("registry_group") == group_label:
            return _type_fit(type_block, _era_index(registry, group_label,
                                                    slot_key))
    return DEFAULT_FIT
