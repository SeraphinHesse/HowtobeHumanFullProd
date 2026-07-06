"""Pure tile-map model (D-20/D-21) — the ONE authority for the map file
format, shared by game (render/load) and editor (paint/save). Phase 6
scope-approved engine addition: editor/ and game/ may never import each
other, so the cell→slot logic they must agree on lives here.

No pygame, no Qt, no game vocabulary: terrain cells are single-char codes
resolved through the map file's own schema-pinned legend, so tile slot
names stay in data. The checkerboard rule is PROTOTYPE-EXACT
(src/map/tile.py): a checker kind renders <slot>_b exactly when
(col + row + 1) % 2 == 1, i.e. col+row EVEN. Background kinds never
alternate. Spawning is a painted zone code — no spawn-point objects exist
in the format (D-20).

Loading fails LOUD (ValueError) on structural problems the schema cannot
express (row counts/lengths vs dims, out-of-bounds base/deco, id≠stem):
that is D-2 dev behavior — the E-37 log-and-placeholder tolerance is for
ART only.
"""
import copy
from dataclasses import dataclass
from pathlib import Path

from engine import data_io
from engine.render.item import RenderItem

ACTIVE_MAP_FILENAME = "active_map.json"


@dataclass
class TileMapDoc:
    map_id: str        # == filename stem of data/maps/<map_id>.json
    display_name: str
    cols: int
    rows: int
    legend: dict       # code -> {"slot": str, "checker": bool} (schema-pinned)
    terrain: list      # rows × cols nested lists of legend codes (mutable)
    base: dict         # {"col": int, "row": int, "slot": str}
    deco: list         # [{"col": num, "row": num, "slot": str}, ...]


# -- dict <-> doc (terrain rows are strings on disk, char lists in memory) --

def from_dict(data):
    return TileMapDoc(
        map_id=data["id"],
        display_name=data["display_name"],
        cols=data["cols"],
        rows=data["rows"],
        legend=copy.deepcopy(data["legend"]),
        terrain=[list(row) for row in data["terrain"]],
        base=dict(data["base"]),
        deco=[dict(d) for d in data["deco"]],
    )


def to_dict(doc):
    return {
        "base": dict(doc.base),
        "cols": doc.cols,
        "deco": [dict(d) for d in doc.deco],
        "display_name": doc.display_name,
        "id": doc.map_id,
        "legend": copy.deepcopy(doc.legend),
        "rows": doc.rows,
        "terrain": ["".join(row) for row in doc.terrain],
    }


def validate_doc(doc):
    """Cross-checks the schema cannot express. Raises ValueError (D-2)."""
    if len(doc.terrain) != doc.rows:
        raise ValueError(
            f"map {doc.map_id!r}: {len(doc.terrain)} terrain rows, rows={doc.rows}")
    for r, row in enumerate(doc.terrain):
        if len(row) != doc.cols:
            raise ValueError(
                f"map {doc.map_id!r}: terrain row {r} has {len(row)} cells, cols={doc.cols}")
        for c, code in enumerate(row):
            if code not in doc.legend:
                raise ValueError(
                    f"map {doc.map_id!r}: cell ({c},{r}) code {code!r} not in legend")
    if not (0 <= doc.base["col"] < doc.cols and 0 <= doc.base["row"] < doc.rows):
        raise ValueError(
            f"map {doc.map_id!r}: base {doc.base} outside {doc.cols}x{doc.rows}")
    for d in doc.deco:
        if not (0 <= d["col"] < doc.cols and 0 <= d["row"] < doc.rows):
            raise ValueError(
                f"map {doc.map_id!r}: deco {d} outside {doc.cols}x{doc.rows}")


# -- cell -> slot (wrinkle 7: prototype-exact parity) ------------------------

def slot_for_code(legend, code, col, row):
    """Slot a code renders with AT a cell — also what a paint ghost shows."""
    entry = legend[code]
    slot = entry["slot"]
    if entry["checker"] and (col + row + 1) % 2 == 1:
        return slot + "_b"
    return slot


def slot_for_cell(doc, col, row):
    return slot_for_code(doc.legend, doc.terrain[row][col], col, row)


def render_items(doc, *, terrain=True, base=True, deco=True, tint_for_code=None):
    """The map as RenderItems for the ONE pipeline (ED-22): ground tiles
    (optionally tinted per code — the editor's zone-tint eye), the base on
    the entities layer, deco on the deco layer (above entities, E-26).
    Keyword toggles are the editor's layer eyes; the game submits all."""
    items = []
    if terrain:
        tints = tint_for_code or {}
        for row in range(doc.rows):
            for col in range(doc.cols):
                items.append(RenderItem(
                    slot_for_cell(doc, col, row), (col, row), layer="ground",
                    tint=tints.get(doc.terrain[row][col])))
    if base:
        items.append(RenderItem(
            doc.base["slot"], (doc.base["col"], doc.base["row"]), layer="entities"))
    if deco:
        for d in doc.deco:
            items.append(RenderItem(d["slot"], (d["col"], d["row"]), layer="deco"))
    return items


def visible_render_items(doc, col_min, col_max, row_min, row_max, *,
                         terrain=True, base=True, deco=True,
                         tall_margin=3, tint_for_code=None):
    """render_items bounded to a tile window (from
    CoordinateSystem.visible_tile_window) — windowed culling so an arbitrarily
    large map only ever generates the tiles that can be on screen. Identical
    output to render_items for the covered cells; the window is clamped to
    [0, cols/rows). Base/deco (tall sprites, possibly a few) are included when
    within the window expanded by `tall_margin`, since they anchor up to ~2
    tile-heights above their own cell and stay visible slightly off the top
    edge."""
    items = []
    if terrain:
        tints = tint_for_code or {}
        r0 = max(0, row_min)
        r1 = min(doc.rows, row_max + 1)
        c0 = max(0, col_min)
        c1 = min(doc.cols, col_max + 1)
        for row in range(r0, r1):
            trow = doc.terrain[row]
            for col in range(c0, c1):
                items.append(RenderItem(
                    slot_for_code(doc.legend, trow[col], col, row),
                    (col, row), layer="ground", tint=tints.get(trow[col])))
    tc0, tc1 = col_min - tall_margin, col_max + tall_margin
    tr0, tr1 = row_min - tall_margin, row_max + tall_margin
    if base and tc0 <= doc.base["col"] <= tc1 and tr0 <= doc.base["row"] <= tr1:
        items.append(RenderItem(
            doc.base["slot"], (doc.base["col"], doc.base["row"]), layer="entities"))
    if deco:
        for d in doc.deco:
            if tc0 <= d["col"] <= tc1 and tr0 <= d["row"] <= tr1:
                items.append(RenderItem(d["slot"], (d["col"], d["row"]), layer="deco"))
    return items


def band_render_items(doc, d_min, d_max, s_min, s_max, *, tint_for_code=None):
    """Ground RenderItems for an ISO-DIAGONAL band, addressed by the rotated
    coordinates ``d = col - row`` and ``s = col + row`` (both integers, always
    the same parity for a real cell). ``visible_render_items`` takes an
    axis-aligned *tile* rectangle, whose bounding box for a thin but long
    on-screen strip (a diagonal in tile space) balloons to almost the whole
    viewport — the wrong emitter for the ground cache's scroll-fill strips. A
    thin screen strip is a thin band in ``d`` (a vertical strip) or ``s`` (a
    horizontal one), so iterating ``d``/``s`` directly emits ONLY the tiles the
    strip actually covers, independent of map size. Ground layer only (base/deco
    live on other layers and are submitted separately by the caller)."""
    items = []
    tints = tint_for_code or {}
    cols, rows = doc.cols, doc.rows
    legend, terrain = doc.legend, doc.terrain
    for d in range(d_min, d_max + 1):
        s0 = s_min if (s_min - d) % 2 == 0 else s_min + 1
        for s in range(s0, s_max + 1, 2):
            col = (s + d) // 2
            row = (s - d) // 2
            if 0 <= col < cols and 0 <= row < rows:
                code = terrain[row][col]
                items.append(RenderItem(
                    slot_for_code(legend, code, col, row),
                    (col, row), layer="ground", tint=tints.get(code)))
    return items


# -- disk I/O (schema + cross-checks + id==stem, all fail loud) --------------

def load_map(path, schema_path):
    path = Path(path)
    doc = from_dict(data_io.load_validated(path, schema_path))
    if doc.map_id != path.stem:
        raise ValueError(f"map id {doc.map_id!r} != filename stem {path.stem!r}")
    validate_doc(doc)
    return doc


def save_map(doc, path, schema_path):
    path = Path(path)
    if doc.map_id != path.stem:
        raise ValueError(f"map id {doc.map_id!r} != filename stem {path.stem!r}")
    validate_doc(doc)
    data_io.write_validated(to_dict(doc), path, schema_path)


# -- creation ---------------------------------------------------------------

def defaults_from_schema(schema):
    """(legend, base_slot) dug out of map_file.schema.json's const pins —
    schemas over convention: no package hardcodes the tile vocabulary."""
    legend = {
        code: {
            "checker": sub["properties"]["checker"]["const"],
            "slot": sub["properties"]["slot"]["const"],
        }
        for code, sub in schema["properties"]["legend"]["properties"].items()
    }
    return legend, schema["properties"]["base"]["properties"]["slot"]["const"]


def default_fill_code(legend):
    """New-map fill / erase target: the first non-checker (background) code
    in sorted order — deterministic and data-driven."""
    return sorted(c for c, e in legend.items() if not e["checker"])[0]


def new_doc(map_id, display_name, cols, rows, schema_path):
    legend, base_slot = defaults_from_schema(data_io.load_json(schema_path))
    fill = default_fill_code(legend)
    return TileMapDoc(
        map_id=map_id,
        display_name=display_name,
        cols=cols,
        rows=rows,
        legend=legend,
        terrain=[[fill] * cols for _ in range(rows)],
        base={"col": cols // 2, "row": rows // 2, "slot": base_slot},
        deco=[],
    )


def duplicate_doc(doc, map_id, display_name):
    dup = from_dict(to_dict(doc))  # deep copy via the serialized form
    dup.map_id = map_id
    dup.display_name = display_name
    return dup


# -- data/ layout conventions (mirrors load_coordinate_system's style) -------

def map_path(data_dir, map_id):
    return Path(data_dir) / "maps" / f"{map_id}.json"


def map_schema_path(data_dir):
    return Path(data_dir) / "schemas" / "map_file.schema.json"


def active_map_path(data_dir):
    return Path(data_dir) / "maps" / ACTIVE_MAP_FILENAME


def active_map_schema_path(data_dir):
    return Path(data_dir) / "schemas" / "active_map.schema.json"


def list_map_ids(data_dir):
    """Sorted map ids on disk (the editor's Maps branch), pointer excluded."""
    maps_dir = Path(data_dir) / "maps"
    return sorted(
        p.stem for p in maps_dir.glob("*.json") if p.name != ACTIVE_MAP_FILENAME)


def load_active_map(data_dir):
    """The game's entry: follow data/maps/active_map.json (D-21), fail loud."""
    data_dir = Path(data_dir)
    pointer = data_io.load_validated(
        active_map_path(data_dir), active_map_schema_path(data_dir))
    return load_map(map_path(data_dir, pointer["active"]), map_schema_path(data_dir))
