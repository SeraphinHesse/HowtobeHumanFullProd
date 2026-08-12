> **SUPERSEDED — historical record.** This brief predates the ZERO-failure
> gate. Any "baseline", "N pre-existing failures", "no NEW failures vs
> Development" or `unittest discover` instruction below is DEAD: the suite is
> green, the gate is ZERO, and a red test is yours. Which tests you may run is
> role-scoped — §"Test Suite Policy" in the root `CLAUDE.md` is the only
> authority. Do not follow this file's verification section.

# Phase ER-1 Brief — Render Sizing

> Coordination artifact for the ER-1..ER-4 subagent batch. Planner filled §1–§4;
> the coder treats §3 as a HARD boundary and §2 as a contract; the reviewer
> verifies the diff against §1/§2/§4. Source plan: `planning/EnemyReworkPLAN.md`
> (Context → "The sizing bug, precisely"; §1 decisions D1/D2/D3; Phase ER-1;
> Risks). Branch: `phase-ER-1-render-sizing` (under the ER umbrella).
>
> **This brief OVERRIDES the plan doc in four places** (all called out inline and
> marked ⚠ CORRECTION). Where they conflict, this brief wins.

**Phase goal:** an enemy's on-screen size derives from its tile footprint, never
from raw sheet pixels; undersized art imports cleanly (padded + centred); the
32px anchor cliff is gone — and buildings / tiles / deco / HUD are provably
untouched.

---

## Known repo state (verified against current source — do NOT re-derive)

- **Sizing has no scale concept.** `engine/render/renderer.py:78-98` is the whole
  of it: `w = frame.frame_w * zoom` (`:81`), `h = frame.frame_h * zoom` (`:82`),
  `anchor = tile_h * (2 if frame.frame_h > tile_h else 1)` (`:86`), and
  `dest = (px - w/2 + offset_x*zoom, py + anchor*zoom - h + offset_y*zoom)`
  (`:90-93`). `tile_h` comes from `coords.geometry.tile_h`; `data/geometry.json`
  is tile_w 64 / tile_h 32.
- **`world_to_screen(wx, wy)` returns the TOP CORNER of the tile's diamond**
  (`engine/coords/system.py:6-7,27-31`). The diamond spans `py .. py + tile_h*z`;
  its centre is `py + (tile_h/2)*z`. This is load-bearing for §2's anchor proof.
- **Frame-size precedence is 4-level**, not 2 (the plan says 2):
  `engine/assets/store.py:44-54` — manifest entry > registry > `frame_sizes` >
  `default_frame_size` ((64, 32)).
- **`SlotRegistry.frame_size()` returns the owning CATEGORY's size**
  (`engine/assets/registry.py:115-117`). There is no per-slot override anywhere.
  `data/slots.json:292-302` declares the `enemies` category at 64×96; its groups
  (Walker / Raider / Siege Cannon / Boss, `:302-425`) hold **bare-string** slot
  entries. `data/schemas/slots.schema.json:32-41` types `slots.items` as a bare
  string with `uniqueItems: true`.
- **Three importer call sites read `registry.frame_size`**: `editor/asset_import.py:26`
  (raises `ValueError` at `:29-32` when the image is smaller than one frame),
  `editor/panels/details.py:266` (`set_slot`, header text only) and `:288`
  (`import_sheet`). A fourth, `details.py:387` (`_load_sheet`), reads the sheet
  already on disk.
  ⚠ **CORRECTION 1 — the plan is wrong about `details.py`.** `import_sheet`
  (`:291-295`) does **NOT** raise: it sets a warning string and `return None`.
  The fix there replaces a return-None, not a raise.
- **What art actually exists** (committed `data/sprites/asset_manifest.json`, 108
  entries). Distinct frame sizes:
  | frame_h | count | who |
  |---|---|---|
  | 96 | 80 | every building / deco / core sheet, `boss_era_4` (124×96), 3× 68×96 |
  | 32 | 10 | every map tile |
  | 18 / 26 / 28 | 6 / 11 / 4 | raiders (12×18), walkers (22×26, 20×26), siege (36×28) |
  | 56 / 84 / 88 | 1 / 2 / 1 | `boss_era_0` (72×56), `boss_era_1..2` (108×84), `boss_era_3` (116×88) |
  | 270 | 1 | `main_menu_bg` (480×270) — drawn as a `HudSprite`, which **bypasses**
        the anchor code entirely (`renderer.py:113-122`) |
  **Every non-enemy world frame is 96 or 32 tall.** That fact is what makes D3
  provably safe (see §2).
- Slots with **no** manifest entry (`base_hole`, `camera_startpoint`,
  `start_area`, `ui_*`, `vfx_*`) render as a grey-X placeholder sized from the
  registry CATEGORY (`store.py:71-73`): core 64×96, ui/vfx **64×64**.
- **`era_sizes` / `sprite_w` / `sprite_h` are dead in code** — zero `.py` reads.
  They live in `data/balancing/enemies.json:71-92` (`era_sizes`, 5 rows) and
  `:133-174` (`sprite_h`/`sprite_w` on each of the 5 `Boss/stats` rows), are
  **required** by `data/schemas/enemies.schema.json:42-63` (`$defs/boss_stat`)
  and `:239,:296-303` (`Boss.era_sizes`), and are asserted by
  `tools/tests/balancing_parity_map.json`.
- **`footprint` and `sprite_scale` do not exist anywhere yet.**
- `RenderItem` (`engine/render/item.py:13-21`) is a **frozen** dataclass:
  `slot_key, world_pos, layer, animation, anim_time_ms, tint, flip`.
  `SpriteAnimator` (`engine/core/sprite_animator.py:13-34`) declares
  `slot_key / animation / phase_ms / anim_time_ms` and emits the item in
  `render_items(transform)`. `Component._check_type`
  (`engine/core/component.py:70-77`) accepts an `int` for a `float` field.
- `Enemy.__init__` (`game/enemies/enemy.py:93-122`) builds a fixed component list
  at `:99-107` including `SpriteAnimator(slot_key=slot, animation="walk",
  phase_ms=…)`. `Enemy.STAT_SUBTREE = ("Standard",)` (`:86`) exists but is
  **read by nothing** — no subclass overrides it (latent trap; ER-1 fixes it).

---

## 1. Behavioral spec

### 1.1 Per-slot frame size (D1 — `engine/assets`, `data/`)

- `data/slots.json` group leaf entries (`groups[].slots[]`) accept an **object
  form** `{"key": …, "frame_w": …, "frame_h": …}` beside today's bare string. A
  bare string keeps inheriting the category's `frame_w`/`frame_h`, so **every
  existing entry is byte-identical and every existing consumer is unaffected**.
- `SlotRegistry.frame_size(slot_key)` returns the per-slot override when present,
  else the owning category's size (E-34). Unknown slot still raises `KeyError`
  (`store.py:50-53` catches it; `tools/tests/test_assets_registry.py:82` pins it).
- **ER-1 does NOT add any override to `data/slots.json`'s content.** It ships the
  *capability* (schema + loader + editor writers) and nothing else. ER-4 is the
  first consumer (the `Formation` group at 128×128). Rationale: the D2 fit already
  removes the "too big" symptom for a 64×96-declared re-import (it can never
  exceed its footprint's width), so a backfill is not needed for correctness and
  would collide with ER-4's `data/slots.json` edit for no gain.

### 1.2 Downscale-only footprint fit (D2 — `engine/render`, `engine/core`, `game/enemies`)

Non-negotiable math (plan §1 D2):

```
target_w = footprint_tiles * tile_w            # 1 -> 64px, 2 -> 128px
scale    = min(1.0, target_w / frame_w) * sprite_scale
```

Downscale-only. Binding cases the tests must pin:
- 124×96 boss sheet at footprint 1 → **64px wide** (scale ≈ 0.516). *This is what
  actually fixes "too big".*
- 128×128 formation sheet at footprint 2 → exactly 128×128 (scale 1.0).
- 16×16 frame → **never upscaled** (binding user decision 2: "pad and centre,
  never upscale"). It renders 16px and small. `sprite_scale` (per type, default
  1.0, **may exceed 1**) is the deliberate knob. Listed as an accepted risk in the
  plan.

Consequence for today's art (compute it, don't guess): walkers (22 wide), raiders
(12), siege (36) all have `frame_w ≤ 64`, so at footprint 1 their fit factor is
`min(1, 64/22) = 1.0` — **unchanged size**. Only the four boss sheets (72/108/116/124
wide) shrink. That is the intended blast radius.

### 1.3 The anchor becomes continuous (D3 — `engine/render`)

⚠ **CORRECTION 2 — the plan's wording for D3 is unimplementable as written.**
The plan says the new rule "keeps the art's **bottom** on the tile at any frame
height". Taken literally (`frame bottom at py + tile_h*z`) a 64×96 building frame
would move **up 32px**, breaking the plan's own "pixel-pin buildings / deco /
tiles before merge" risk item. The correct rule is derived, not invented:

Today's two branches, written out with `py` = the diamond's top corner:
- `frame_h = 32` → `dest_y = py + 32z − 32z = py` → frame **centre** at `py + 16z`.
- `frame_h = 96` → `dest_y = py + 64z − 96z = py − 32z` → frame **centre** at `py + 16z`.

Both canonical branches are the *same* rule: **the frame's centre sits on the
tile's centre** (`py + (tile_h/2)·z`). The existing cliff is just that identity
expressed as two special cases. So D3's rule is:

```
dest_y = py + (tile_h/2) * zoom  -  h/2   (+ offset_y * zoom * scale)
dest_x = px - w/2                         (+ offset_x * zoom * scale)   # unchanged
```

continuous in `frame_h`, exactly reproducing today's output at `frame_h ∈ {32, 96}`
— i.e. at **every non-enemy world frame that exists** (see the table above), and
matching the prototype's enemy blit (`enemy.py:444`'s HP bar at `cy − 26` is
measured off the tile CENTRE, and the walker sheet is 26 tall).

**Full list of sprites this moves** (state it in the PR):
| what | frame_h | shift (at zoom 1) |
|---|---|---|
| raiders | 18 | 7px up |
| walkers | 26 | 3px up |
| siege | 28 | 2px up |
| `boss_era_0` | 56 | 20px up |
| `boss_era_1/2` | 84 | 6px up |
| `boss_era_3` | 88 | 4px up |
| `boss_era_4`, ALL buildings/deco/core, ALL tiles, `main_menu_bg` | 96 / 32 / HUD | **0px — byte-identical** |
| editor-preview-only: `ui_*` / `vfx_*` grey-X (64×64, no manifest entry, referenced by no `.py`) | 64 | 16px up — accepted, editor preview only |

### 1.4 Pad-and-centre import (ED-40/41 — `editor/`)

⚠ **CORRECTION 3 — pad-and-centre is centred in BOTH axes, not bottom-anchored.**
The plan's parenthetical "(bottom-anchored)" is inconsistent with (a) its own
binding decision name ("**pad and centre**, never upscale") and (b) §1.3's anchor.
Proof it must be centred: a 16×16 PNG bottom-anchored in a 64×96 frame occupies
frame rows 80..96; with the frame's centre pinned to the tile's centre, the art
lands `py + 48z .. py + 64z` — **16..32px BELOW the tile diamond**, floating off
the ground. Centred in the frame it lands `py + 8z .. py + 24z`, inside the
diamond. Centred is the only self-consistent choice, and it is exactly the
convention the existing 64×96 building sheets already use ("art authored centred
in the 96px frame", `renderer.py:8-14`).

Art smaller than one declared frame is padded onto a transparent canvas and
centred, instead of being rejected. Both importer paths (`editor/asset_import.py`
raise; `editor/panels/details.py` return-None) change. Pillow is already a dep.

### 1.5 Dead-data deletion (`data/`, parity gate)

`era_sizes` (`enemies.json:71-92`), and `sprite_w`/`sprite_h` on all five
`Boss/stats` rows (`:133-174`), are deleted from content **and** schema.

⚠ **CORRECTION 4 — the parity map needs TWO different treatments, not one.**
The plan says "retag the deleted keys as `DROPPED:<reason>`". That is correct for
exactly one entry:
- `tools/tests/balancing_parity_map.json:111` `"BOSS_ERA_SIZES"` lives in the
  MAIN mapping table, whose consumer `test_balancing_parity.py:84-85` skips
  `DROPPED:` strings → **retag it** `"DROPPED:<reason>"`.
- The ten `sprite_w`/`sprite_h` entries live in **`_py_only`** (`:244-251`,
  `:288-295`, `:332-339`, `:376-383`, `:420-427`). Their consumer
  `test_py_only_boss_eras_expectations` (`test_balancing_parity.py:101-108`)
  indexes `entry["path"]` / `entry["expect"]` with **no `DROPPED:` branch** — a
  bare string there raises `TypeError: string indices must be integers`.
  → **DELETE those ten entries outright.** Do not retag them. Do not add a
  `DROPPED:` branch to the test (the `_py_only` table is a literal-expectation
  table, not a coverage table — nothing asserts it is exhaustive).

Requirement IDs in play: **E-20** (RenderItem), **E-21/E-22** (Renderer),
**E-23/E-33** (grey-X at the slot's frame size), **E-34** (data-driven slot
registry), **ED-30/31** (invalid input unrepresentable; all writes via the
validating writer), **ED-40/41** (importer parity), **D-2/D-3** (schema-valid,
deterministic writes), **D-12** (description on every leaf; `minimum`+`maximum`
on every numeric leaf), **D-32** (slots.json).

---

## 2. Architecture plan

### 2.1 `engine/render/item.py` — `RenderItem` (frozen)

Append two fields **at the end** (positional construction sites stay valid;
`engine/tilemap.py`, `editor/panels/viewport.py`, `tools/render_demo.py`,
`engine/core/sprite_animator.py` and the tests all construct with ≤ the existing
arity):

```python
@dataclass(frozen=True)
class RenderItem:
    slot_key: str
    world_pos: tuple
    layer: str = "entities"
    animation: str = "idle"
    anim_time_ms: int = 0
    tint: tuple = None
    flip: bool = False
    fit_tiles: float = 0.0   # 0 = no fit (raw frame size, today's behaviour)
    scale: float = 1.0       # extra multiplier applied after the fit
```

Engine-generic names only — **no game vocabulary in `engine/`** (engine hard
rule). `fit_tiles` / `scale`, never `footprint` / `sprite_scale`.

### 2.2 `engine/core/sprite_animator.py` — `SpriteAnimator`

Two new declared component fields (JSON-safe floats; `Component._check_type`
already accepts an `int` for a `float`), threaded straight into the emitted item:

```python
class SpriteAnimator(Component):
    slot_key: str = ""
    animation: str = "idle"
    phase_ms: int = 0
    anim_time_ms: float = 0.0
    fit_tiles: float = 0.0
    scale: float = 1.0

    def render_items(self, transform):
        yield RenderItem(
            self.slot_key,
            transform.world_pos,
            layer=transform.layer,
            animation=self.animation,
            anim_time_ms=self.anim_time_ms + self.phase_ms,
            fit_tiles=self.fit_tiles,
            scale=self.scale,
        )
```

### 2.3 `engine/render/renderer.py` — the sizing block (`:78-98`)

Replace the body of the per-item loop with:

```python
tile_w = coords.geometry.tile_w        # NEW local, beside the existing tile_h
half_h = tile_h / 2                    # NEW local
...
for item in ordered:
    frame = self._assets.frame(item.slot_key, item.animation, item.anim_time_ms)
    px, py = coords.world_to_screen(*item.world_pos)
    fit = 1.0
    if item.fit_tiles > 0.0 and frame.frame_w > 0:
        fit = min(1.0, (item.fit_tiles * tile_w) / frame.frame_w)   # downscale only
    s = fit * item.scale
    w = frame.frame_w * zoom * s
    h = frame.frame_h * zoom * s
    # The frame is CENTRED on the tile: horizontally on the world position,
    # vertically on the tile diamond's centre (py + tile_h/2). Continuous in
    # frame_h — the old two-branch anchor was this same rule spelled out for
    # frame_h == tile_h and frame_h == 3*tile_h.
    draw_calls.append(DrawCall(
        surface=frame.surface,
        dest=(px - w / 2 + frame.offset_x * zoom * s,
              py + half_h * zoom - h / 2 + frame.offset_y * zoom * s),
        size=(w, h),
        tint=item.tint,
        flip=item.flip,
    ))
```

**Hard invariant (pin it with a test):** with the defaults `fit_tiles == 0.0` and
`scale == 1.0`, `s == 1.0` and the expression collapses to
`dest = (px − w/2 + offset_x·z, py + (tile_h/2)·z − (frame_h·z)/2 + offset_y·z)`,
which is **identical** to today for `frame_h ∈ {32, 96}` (see §1.3's algebra) —
so buildings, tiles, deco and the HUD pass are provably untouched.

Manifest offsets are multiplied by `s` as well: they are authored in FRAME pixels,
so they must ride the same scale. At `s == 1.0` this is a no-op, so the invariant
above still holds exactly.

Update the module docstring (`renderer.py:7-14`) — it currently documents the old
two-branch anchor.

### 2.4 `engine/assets/registry.py` — the per-slot override

The **critical constraint**: `GroupNode.slots` is consumed as a tuple of *key
strings* by `editor/selection.py:34,46,59-62,86`, `editor/panels/selector.py:226`,
`editor/panels/palette.py:206-241`, `game/enemies/enemy.py:59` (via `group_slots`)
and `tools/tests/test_assets_registry.py:55-72`. **The object form must be
normalised away at parse time and must never leak out of the registry.**

```python
def _slot_key(entry):
    """A slots[] entry is a bare key string, or {key, frame_w, frame_h}."""
    return entry if isinstance(entry, str) else entry["key"]


def _parse_group(raw):
    return GroupNode(
        label=raw["label"],
        slots=tuple(_slot_key(s) for s in raw.get("slots", ())),   # keys ONLY
        children=tuple(_parse_group(c) for c in raw.get("children", ())),
    )
```

`GroupNode` keeps its exact current shape. Overrides are collected on a second
walk over the RAW doc in `SlotRegistry.__init__` into
`self._slot_frame: dict[str, tuple[int, int]]`, then:

```python
def frame_size(self, slot_key):
    category = self._slot_category[slot_key]        # KeyError on unknown — keep
    return self._slot_frame.get(slot_key, (category.frame_w, category.frame_h))
```

**Fail-loud cross-check** (the schema cannot express it, so the loader must —
same pattern as the existing "slot in two categories" `ValueError` at
`registry.py:70-74`): the same slot key declared with **two different** frame-size
overrides, or once bare and once with an override, raises `ValueError`. A slot key
may still legitimately repeat across groups of ONE category (shared art) as long
as every occurrence agrees.

### 2.5 `data/schemas/slots.schema.json` — the object form

Add a `$defs/slot_entry` and widen `$defs/group_node.properties.slots.items`
(`:32-41`):

```json
"slot_entry": {
  "additionalProperties": false,
  "description": "A slot key that overrides its category's frame size (D1): how the SHEET is sliced. Use the bare-string form to inherit the category size.",
  "properties": {
    "frame_h": {"description": "Sprite frame height in pixels for this slot, overriding the category's.", "maximum": 1024, "minimum": 1, "type": "integer"},
    "frame_w": {"description": "Sprite frame width in pixels for this slot, overriding the category's.", "maximum": 1024, "minimum": 1, "type": "integer"},
    "key": {"description": "The slot key.", "pattern": "^[a-z][a-z0-9_]*$", "type": "string"}
  },
  "required": ["key", "frame_w", "frame_h"],
  "type": "object"
}
```

```json
"slots": {
  "description": "Slot entries in this group, in display order. Either a bare key (inherits the category frame size) or a {key, frame_w, frame_h} object that overrides it (D1: slicing != drawing). The same key may appear under two groups of ONE category (shared art) but never in two categories, and every occurrence must agree on its frame size (loader-enforced).",
  "items": {"oneOf": [
    {"pattern": "^[a-z][a-z0-9_]*$", "type": "string"},
    {"$ref": "#/$defs/slot_entry"}
  ]},
  "minItems": 1,
  "type": "array",
  "uniqueItems": true
}
```

**`uniqueItems` interaction — call it out in `data/CLAUDE.md`.** `uniqueItems`
compares whole *values*: once objects are legal, `"foo"` and
`{"key": "foo", …}` are two distinct items, so the schema alone no longer
guarantees key-level uniqueness inside a group. Keep `uniqueItems: true` (it still
catches literal duplicates, and it is the D-3 house style) and enforce **key-level
uniqueness within a group** in `SlotRegistry.__init__` (fail loud, §2.4) — schemas
for what schemas can express, loader cross-checks for what they cannot
(the `engine/tilemap.py` precedent).

### 2.6 `editor/registry_ops.py` — object-form tolerance (REQUIRED, not optional)

`_all_slots` (`:46-57`) does `out.update(node.get("slots", ()))` → a dict entry
would land in a `set` and raise `TypeError: unhashable type: 'dict'`.
`next_variant_key` (`:33-43`) does `_stem(existing_slots[0])` → a dict breaks the
regex. Both must go through `_slot_key(...)`:

- `_all_slots`: `out.update(_slot_key(s) for s in node.get("slots", ()))`.
- `add_variant` (`:101-102`): compute the stem from **keys**
  (`[_slot_key(s) for s in child["slots"]]`) and keep appending a **bare string**
  (a new variant inherits the group's frame size — an override for it is ER-5's
  editor feature).
- Same for `_append_slot` (`:150-151`).

Add a module-private `_slot_key` (do NOT import it from `engine.assets.registry` —
`registry_ops` is deliberately a pure `engine.data_io`-only module and stays in
`test_editor_viewport.TestPurity`; a 2-line local helper is cheaper than a new
coupling). ER-1 introduces no object entry into `data/slots.json`, but the schema
now permits one and ER-4 will add one — this must not be a latent crash.

### 2.7 `editor/asset_import.py` + `editor/panels/details.py` — pad and centre

One shared, pure helper. Put it in `editor/asset_import.py` (already Qt-free,
pygame-free and in `TestPurity`) and import it from `details.py` (which already
imports Pillow):

```python
def pad_to_frame(image, fw, fh):
    """Grow `image` (a PIL Image) so it is at least one fw x fh frame, with the
    original art CENTRED on a fully transparent canvas. Never upscales, never
    shrinks, never crops. Returns (image, padded: bool) — `padded` False means
    the image already covered a frame in both axes and is byte-untouched."""
    w, h = image.size
    if w >= fw and h >= fh:
        return image, False
    pad_w, pad_h = max(w, fw), max(h, fh)
    canvas = Image.new("RGBA", (pad_w, pad_h), (0, 0, 0, 0))
    canvas.paste(image.convert("RGBA"), ((pad_w - w) // 2, (pad_h - h) // 2))
    return canvas, True
```

Per-axis semantics fall out cleanly: an axis that already covers a frame is left
alone (offset 0 on that axis), so a 128×16 strip into a 64×96 slot pads only
vertically and still detects 2 columns.

- `import_idle_sheet` (`:16-65`): open the image, `pad_to_frame`, then **if
  padded → `padded.save(destination)`, else keep the existing
  `shutil.copyfile`** (byte-identical copies preserve
  `tools/migrate_prototype_assets.py`'s idempotency, pinned by
  `test_migrate_prototype_assets.py`). Compute `cols, rows` from the PADDED size
  (both now ≥ 1). **Delete the `ValueError` at `:29-32`** and update the docstring
  (`:22-23` still promises the raise).
- `details.py::import_sheet` (`:281-308`): same — pad, save-or-copy, drop the
  `return None` at `:291-295`, set an informational (not ⚠) message when padding
  happened, e.g. `f"padded {w}×{h} → {pad_w}×{pad_h} (centred in the {fw}×{fh}
  frame)"`, and fall through to the normal `_load_sheet` + `_emit_draft` path.
- `details.py::_load_sheet` (`:386-401`) needs **no change**: the sheet on disk is
  now always ≥ one frame. Leave its `⚠ sheet too small` branch as the guard for
  legacy/hand-placed files.
- `details.py::set_slot` (`:266`) needs **no change** beyond inheriting the new
  `frame_size` (it only formats the header).

### 2.8 `data/balancing/enemies.json` + `data/schemas/enemies.schema.json`

**Add** to each of the four `EnemyTypes` blocks (`Standard`, `Raider`,
`SiegeCannon`, `Boss`) — required properties, not optional (D-12: the editor
derives its spinbox ranges from the bounds, and a required key keeps
`additionalProperties:false` + full `required` house style):

```json
"footprint": 1,
"sprite_scale": 1.0
```

Schema (both leaves need a `description` AND, being numeric, both a `minimum` and
a `maximum` — `tools/tests/test_balancing_data.py:107-129` walks every leaf):

```json
"footprint": {
  "description": "Tile footprint: the unit occupies footprint x footprint tiles. Drives BOTH the render fit (its sprite is downscaled to footprint*tile_w wide, never upscaled) and, from ER-2, clearance pathing. 1 = a normal one-tile enemy.",
  "maximum": 8, "minimum": 1, "type": "integer"
},
"sprite_scale": {
  "description": "Extra render multiplier applied AFTER the footprint fit (1.0 = fit exactly). The deliberate knob for low-res art, which is never auto-upscaled; may exceed 1.",
  "maximum": 8, "minimum": 0.1, "type": "number"
}
```

Add both to each type's `required` list, and extend the schema's top-level
`description` bounds policy line (`:161`) with `footprint tiles 1-8; sprite_scale
multiplier 0.1-8`.

**Delete**: `$defs/era_size` (`:67-89`) entirely; `sprite_h`/`sprite_w` from
`$defs/boss_stat` `properties` (`:42-53`) and `required` (`:55-64`);
`Boss.properties.era_sizes` (`:239-247`) and `"era_sizes"` from `Boss.required`
(`:296-303`); and fix `Boss`'s description (`:228`), which names `era_sizes[N]` in
its index-alignment sentence. Content: delete `era_sizes` (`enemies.json:71-92`)
and the ten `sprite_h`/`sprite_w` lines in `Boss/stats` (`:133-174`).

Write through `engine.data_io.write_validated` / re-emit with
`dumps_deterministic` — sorted keys, 2-space indent, trailing newline (D-3).
`test_balancing_data.test_files_are_canonical_on_disk` will catch a hand-format.

### 2.9 `game/enemies/enemy.py` — thread it through

`STAT_SUBTREE` (`:86`) is currently declared once and never read. **Make it real**
rather than adding a parallel attribute:

- `Enemy.STAT_SUBTREE = ("Standard",)` (already), and add
  `Raider.STAT_SUBTREE = ("Raider",)`, `SiegeCannon.STAT_SUBTREE = ("SiegeCannon",)`,
  `Boss.STAT_SUBTREE = ("Boss",)`.
- In `Enemy.__init__` (`:93-107`), before building the component list:
  ```python
  block = enemies_balance["EnemyTypes"]
  for seg in self.STAT_SUBTREE:
      block = block[seg]
  footprint = block["footprint"]
  sprite_scale = block["sprite_scale"]
  ```
  and pass them into the animator (`:105-106`):
  ```python
  SpriteAnimator(slot_key=slot, animation="walk",
                 phase_ms=(col * 137 + row * 251) % 2000,
                 fit_tiles=float(footprint), scale=float(sprite_scale)),
  ```
  Direct indexing, no `.get()` default — the keys are schema-required and the
  tests load the real `data/balancing/enemies.json` via `game.core.balance.load_balance`
  (`tools/tests/test_enemies.py:23,36`). A code-side default would reintroduce the
  py+json dual value store the root `CLAUDE.md` forbids.
- Do **not** touch `PathAgent` — footprint-aware pathing is ER-2.

---

## 3. File scope + shared-file contract

ER-1 runs alone in its wave, but ER-2/ER-3/ER-4 touch some of the same files.
**Region ownership is binding.**

### Files ER-1 owns outright (no later phase touches them)

| File | Change |
|---|---|
| `engine/render/renderer.py` | `:1-15` docstring; the `flush` per-item block `:78-98` (fit + centre anchor + `tile_w`/`half_h` locals) |
| `engine/render/item.py` | `RenderItem` `:13-21` — append `fit_tiles`, `scale` |
| `engine/core/sprite_animator.py` | `:13-34` — two fields + pass-through in `render_items` |
| `engine/assets/registry.py` | `_slot_key` helper; `_parse_group` `:31-36`; `SlotRegistry.__init__` `:53-75` (`_slot_frame` + fail-loud cross-check); `frame_size` `:115-117` |
| `editor/asset_import.py` | new `pad_to_frame`; `import_idle_sheet` `:16-65` (drop the `ValueError`) |
| `editor/panels/details.py` | `import_sheet` `:281-308` only (drop the `return None`) |
| `editor/registry_ops.py` | `_all_slots` `:46-57`, `next_variant_key` `:33-43`, `add_variant` `:101-102`, `_append_slot` `:150-151` |
| `data/schemas/slots.schema.json` | new `$defs/slot_entry`; `$defs/group_node.properties.slots.items` `:32-41` |
| `engine/render/CLAUDE.md`, `engine/assets/CLAUDE.md`, `data/CLAUDE.md` | docs (§4) |

### Shared files — ER-1's regions ONLY

| File | ER-1 owns | Left to later phases |
|---|---|---|
| `data/balancing/enemies.json` | `footprint` + `sprite_scale` keys inside the four `EnemyTypes/*` blocks; **deletion** of `Boss/era_sizes` (`:71-92`) and of `sprite_h`/`sprite_w` in `Boss/stats` (`:133-174`) | **ER-3**: the `death_spawn` block (+ re-expressing `Boss/death_spawns` `:44-70`). **ER-4**: the whole new `EnemyTypes/Formation` block. ER-1 must NOT pre-create `Formation` or touch `death_spawns`. |
| `data/schemas/enemies.schema.json` | `footprint`/`sprite_scale` properties + `required` in the four type blocks; deletion of `$defs/era_size`, of `sprite_h`/`sprite_w` in `$defs/boss_stat`, of `Boss.era_sizes`; the bounds-policy sentence in the top-level `description` | **ER-3**: a `$defs/death_spawn`. **ER-4**: `EnemyTypes.Formation` + its `required` entry. |
| `tools/tests/balancing_parity_map.json` | `:111` `BOSS_ERA_SIZES` → `DROPPED:` (retag); **delete** the ten `_py_only` `sprite_w`/`sprite_h` entries (`:244-251`, `:288-295`, `:332-339`, `:376-383`, `:420-427`) | **ER-3**: re-point `Boss/death_spawns` at its new path. Nothing else. |
| `data/slots.json` | **NOTHING — do not edit this file.** (§1.1: ER-1 ships the object-form capability in the schema only.) | **ER-4**: the `Formation` group with its 128×128 per-slot override. |
| `game/enemies/enemy.py` | `STAT_SUBTREE` on the three subclasses (`:154-212`); the `SpriteAnimator(...)` construction + the balance read in `Enemy.__init__` (`:93-107`) | **ER-2**: `PathAgent(footprint=…)` in the same component list. **ER-3**: threshold death / `alive`. **ER-4**: the `Formation` subclass + `ENEMY_CLASSES`. Keep the ER-1 diff to those two hunks so the later merges are clean. |

### Files ER-1 must NOT touch (hard boundary)

`game/map/pathfinder.py` · `game/enemies/combat.py` · `game/enemies/components.py` ·
`game/core/session.py` · `game/enemies/spawner.py` · `game/ui/**` · `game/main.py` ·
`engine/assets/store.py` (its 4-level precedence already does the right thing once
`registry.frame_size` is fixed) · `engine/coords/**` · `data/slots.json`.

---

## 4. Exit gate + Quick Test

### Gate (both commands, from the repo root)

```
py tools/smoke.py
py -m unittest discover -s tools/tests -t .
```

**ZERO NEW failures** against the known `Development` baseline: **17 pre-existing
failures** (10 editor/Qt-env + 6 balancing-parity + 1 skip) out of ~856 tests.
Compare failure *names*, not counts. Data changed → smoke's schema validation must
pass (it validates all of `data/`).

### Tests to write / update (named, not optional)

**`tools/tests/test_render.py`** (extend `TestAnchoring`, add a `TestFootprintFit`):
- Fit math, all three binding cases: a 124×96 frame at `fit_tiles=1` → `size[0] == 64`;
  a 128×128 frame at `fit_tiles=2` → `size == (128, 128)`; a 16×16 frame at
  `fit_tiles=1` → `size == (16, 16)` (**never upscaled**).
- `sprite_scale`: `scale=2.0` on the 16×16 case → `(32, 32)`; `scale` applies with
  `fit_tiles=0` too.
- **`fit_tiles=0, scale=1.0` is pixel-identical to today**: keep
  `test_ground_tile_anchor` (`:88-95`, dest `(-32.0, 0.0)`) and
  `test_tall_entity_anchor` (`:97-109`, dest `(-32.0, 0.0)`, size `(64, 96)`)
  **unchanged and passing** — they are the pin. Add a `test_zoom` case at zoom 2.
- **Anchor continuity across the old 32px cliff**: sweep `frame_h` over
  `range(1, 129)` at `fit_tiles=0` and assert `dest_y` is monotone and has no jump
  > 1px between consecutive heights (today's rule jumps 32px between 32 and 33).
- **Pixel-pin the non-enemy world**: a table-driven test over the frame sizes that
  actually ship — `(64,32)`, `(64,96)`, `(68,96)`, `(124,96)` — asserting the new
  `dest`/`size` equal the OLD formula's (`py + tile_h*(2 if fh > tile_h else 1)*z − fh*z`).
  Buildings / deco / tiles / core must be byte-identical; the enemy heights
  (18/26/28/56/84/88) are the documented, asserted deltas from §1.3's table.
- Manifest `offset_x`/`offset_y` still nudge, and ride `s` (assert at `s == 1` it
  is a no-op).

**`tools/tests/test_assets_registry.py`**: a per-slot override beats the category
size; a bare string in the same group still inherits; an unknown slot still raises
`KeyError`; a key declared with two conflicting overrides (or once bare, once
overridden) raises `ValueError` at load; `GroupNode.slots` is still a tuple of
**strings** for an object-form group (the anti-leak pin), and `group_slots()`
returns strings. Build the fixture doc in-memory (the file at `:110-120` already
does this) — do **not** edit `data/slots.json`.

**`tools/tests/test_editor_asset_import.py`**: **replace**
`test_image_smaller_than_one_frame_raises` (`:69-72` — it asserts the removed
raise; leaving it is a NEW failure) with: a 16×16 PNG into `enemy_stage_1_v1`
(64×96) imports with no raise, `(cols, rows) == (1, 1)`, the copied PNG on disk is
64×96, and the art is centred (assert the pasted pixel block's bounding box, e.g.
via `Image.getbbox()` on the alpha, is `(24, 40, 40, 56)`). Also: a 128×16 strip
into a 64×96 slot pads only vertically → `(cols, rows) == (2, 1)`; an image that
already covers a frame is **byte-identical** on disk (the `shutil.copyfile` path).

**`tools/tests/test_details_panel.py`**: `import_sheet` with a sub-frame PNG
returns a `(cols, rows, clean)` tuple instead of `None` and leaves no `⚠` in the
info label.

**`tools/tests/test_balancing_data.py`** and **`test_balancing_parity.py`**: no new
code — they must stay green. `test_balancing_data` is what enforces D-12 on the two
new leaves; `test_balancing_parity` is what CORRECTION 4 is about (it currently
contributes 6 known baseline failures — confirm the count does not grow).

**`tools/tests/test_registry_ops.py`**: `add_variant` still works when the target
group contains an object-form entry (build a temp slots.json with one).

### Quick Test (verbatim from `planning/EnemyReworkPLAN.md` ER-1)

> `py game/main.py`, play into round 1 — walkers, raiders and siege sit **on**
> their tile at a sane size, and a boss no longer overflows its tile. Then
> `py editor/main.py`, import a 16×16 PNG onto `enemy_stage_1_v1` and see it
> centred in the preview rather than rejected.

Add, for the D3 risk: open the editor on a map and eyeball that **buildings, deco
and tiles have not moved** (they are pixel-pinned by the test above, but the plan's
Risks section explicitly demands a look).

### Docs to update (package docs only — not the root router)

- **`engine/render/CLAUDE.md`** — rewrite the "Anchor convention" section (`:22-30`):
  the frame is centred on the tile's centre (`py + tile_h/2`), continuous in
  `frame_h`, and the old two-branch rule was this same rule spelled out for 32 and
  96. Add the downscale-only `fit_tiles`/`scale` contract and the
  `fit_tiles == 0 ∧ scale == 1 ⇒ unchanged` invariant.
- **`engine/assets/CLAUDE.md`** — the per-slot frame-size override (D1): slicing vs
  drawing; precedence is now manifest entry > **per-slot registry override** >
  registry category > `frame_sizes` > default; the loader's fail-loud
  conflicting-override check.
- **`data/CLAUDE.md`** — the `slots.json` shape section: the `slots[]` object form,
  why `uniqueItems` no longer implies key uniqueness, and where the loader picks up
  the slack. Note the two new enemy balancing leaves.

### Report exactly what was verified

Smoke test / full unittest run / live `py game/main.py` / live `py editor/main.py`
— name which, per the root router's exit gate.
