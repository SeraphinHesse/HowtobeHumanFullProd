# Phase A7 — Editor: per-variant pixel size (frame-size inheritance)

Slice 10L-A (`planning/UI_EDITOR_PLAN.md` lines 250–256). Branch:
`phase-10L-finish-umbrella` (umbrella execution). Package: **editor only**
(`editor/registry_ops.py` + `tools/tests/test_registry_ops.py`).

**Design**: when a family's stem (`slots[0]`) carries a per-slot frame-size
override (the dict form `{key, frame_w, frame_h}`), `+ Variant` appends a new
variant inheriting that same frame size; bare-string stems stay bare. This fixes
the known follow-up (plan lines 49–55): `ui_bg_main_menu` v2 now gets 480×270
instead of the category default 64×64, so 10L-B's background picker can safely
source from `ui` Backgrounds. **ALL categories**, not ui-only — a variant family
is interchangeable art for one thing; the schema (lines 33–46,
`slots.schema.json`) already allows the object form everywhere.

---

## 1. Behavioral spec

### 1a. Current behavior (baseline, cite:line)

`editor/registry_ops.py::add_variant` (line 124–155):
- Locates the target subcategory (`child`)
- Generates a new variant key via `next_variant_key()` (lines 40–51)
- **Appends a bare string** (line 153: `child["slots"].append(new_key)`)
- Validates and writes

A bare stem like `enemy_stage_2` yields bare variant `enemy_stage_2_v2`. An
override stem like `{"key": "ui_bg_main_menu", "frame_w": 480, "frame_h": 270}`
today yields bare variant `ui_bg_main_menu_v2`, which on load inherits the
category's default (64×64). **This is the bug.**

### 1b. New behavior: frame-size inheritance

Line 153 is replaced with logic:

1. Check if `child["slots"][0]` (the template stem) is a dict (object form).
2. If dict: extract `template["frame_w"]` and `template["frame_h"]`; append a
   new dict `{"key": new_key, "frame_w": template["frame_w"],
   "frame_h": template["frame_h"]}` — inheriting the stem's override.
3. If bare string: append a bare string as today — regression pin for enemies
   and deco prop types, which have no overrides in live data.

**Scope: ALL categories** — enemies, deco, ui, map, buildings, vfx, core (wherever
a family might exist). The schema allows the object form in `slots[]` at any
category (`slots.schema.json` lines 32–47: `oneOf [ string | slot_entry ]` with no
category guard).

**Docstring update** (lines 125–132): note that variants inherit the stem's
frame-size override if present; bare stems yield bare variants.

**`add_deco_variant` inherits for free** (lines 158–161): it calls `add_variant`,
so no separate change. Verify in testing that a `deco_rock` override propagates
to `deco_rock_v2`.

### 1c. Schema + editor UI — no change

- `slots.schema.json` already allows the object form anywhere (lines 32–46).
- The editor's **DetailsPanel Frame W/H spinboxes** (spinbox group, `editor/panels/details.py`)
  already cover every slot variant; divergence after creation is the existing path.
- No data schema change required.

---

## 2. Architecture plan

**Single edit in `editor/registry_ops.py::add_variant`**, replacing line 153.

### Helper to extract or synthesize the slot entry

Add a small helper function before or inline at line 153:

```python
def _slot_entry_from_template(new_key, template):
    """Given a template (bare string or override dict), return the slot entry
    for the new variant: inherit the override if present, else bare string."""
    if isinstance(template, dict):
        return {"key": new_key, "frame_w": template["frame_w"],
                "frame_h": template["frame_h"]}
    else:  # template is a bare string
        return new_key
```

This isolates the inheritance logic and keeps the main append clean. Alternatively,
inline it at line 153 as a ternary or if/else block — either is fine; keep it
close to the append for reviewability.

### Line 153 replacement

```python
    template = child["slots"][0]
    new_entry = _slot_entry_from_template(new_key, template)
    child["slots"].append(new_entry)
```

That is the totality of the production change. The schema validation (line 154) and
return (line 155) are unchanged.

---

## 3. File scope + shared-file contract

A7's coder works on `phase-10L-finish-umbrella`, in the **umbrella umbrella run
alongside B1–B4** (which touch `game/**` and `data/**`). **A7 may touch exactly
these two files:**

| File | What A7 does |
|---|---|
| `editor/registry_ops.py` | replace line 153 with frame-size inheritance logic; update docstring (lines 125–132) |
| `tools/tests/test_registry_ops.py` | extend with four new tests (see §4 below) |

**A7 must NOT touch:**
- `data/schemas/slots.schema.json` (no change needed — object form is legal)
- `data/slots.json` (content file; tests use temp copies)
- `editor/panels/details.py` (frame-size UI already works for any slot)
- `editor/main.py` (selection/dispatch unchanged)
- Any `game/**`, `engine/**`, or other `data/**` file

**Structural claim (for reviewers):** `add_deco_variant` (line 158–161) calls
`add_variant` exactly once and returns its result — no separate logic. The fix
propagates via the call; `add_deco_variant` needs no change and no test of its
own (deco variants are exercised by the inheritance test below).

---

## 4. Exit gate + Quick Test

### Commands

```
py tools/smoke.py
py tools/testgate.py check --affected
```

**Gate = ZERO failures.** No "no new failures vs baseline" language — that policy
is dead (root `CLAUDE.md` §Step 2). Every test must pass; measure any change to
failure count as a real regression.

### New tests in `tools/tests/test_registry_ops.py`

Extend the existing `TestAddVariant(TempDataCase)` class with four tests (reuse
the fixture and helper methods already in the class):

#### Test 1: `test_ui_frame_size_override_propagates_to_variant`

A ui slot with a frame-size override → variant inherits the same size.

```python
def test_ui_frame_size_override_propagates_to_variant(self):
    # ui_bg_main_menu is 480×270 (an override; ui default is 64×64).
    # After A3, the slot is present. Verify + Variant yields a 480×270 variant.
    new_key = registry_ops.add_variant(
        self.data_dir, "ui", ("Backgrounds",), "Main Menu")
    # e.g., ui_bg_main_menu_v2
    
    reg = load_registry(self.data_dir)
    # The variant inherits the stem's 480×270.
    self.assertEqual(reg.frame_size(new_key), (480, 270))
    self.assertEqual(reg.frame_size("ui_bg_main_menu"), (480, 270))
```

**Justification:** this is the R1 requirement — the live use case is 10L-B's
screen editor picking from Backgrounds.

#### Test 2: `test_bare_stem_yields_bare_variant`

A bare-string slot (no override) → variant is bare. Regression pin for enemies
and deco.

```python
def test_bare_stem_yields_bare_variant(self):
    # Walker → Era 2 has enemy_stage_2 (no override; inherits enemies' 64×96).
    # + Variant on era 2 → enemy_stage_2_v2 is BARE, inheriting 64×96.
    self.drop_slot_variants("enemy_stage_2")
    
    new_key = registry_ops.add_variant(
        self.data_dir, "enemies", ("Walker",), "Era 2")
    
    reg = load_registry(self.data_dir)
    # Both inherit the category default (64×96).
    self.assertEqual(reg.frame_size("enemy_stage_2"), (64, 96))
    self.assertEqual(reg.frame_size(new_key), (64, 96))
    # The entry in the registry is bare (not an override dict).
    # (This is an implementation detail, but verifying it pins the
    # regression — bare slots must stay bare.)
    slots_doc = data_io.load_json(self.data_dir / "slots.json")
    enemies = next(c for c in slots_doc["categories"]
                   if c["key"] == "enemies")
    walker = next(g for g in enemies["groups"]
                  if g["label"] == "Walker")
    era2 = next(c for c in walker["children"]
                if c["label"] == "Era 2")
    self.assertIsInstance(era2["slots"][-1], str)  # the appended variant
```

#### Test 3: `test_variant_is_independently_resizable`

After creation with inherited frame size, the variant's size is independently
changeable via `set_slot_frame_size`.

```python
def test_variant_is_independently_resizable(self):
    # Create a ui_bg_main_menu variant at 480×270 (inherited).
    new_key = registry_ops.add_variant(
        self.data_dir, "ui", ("Backgrounds",), "Main Menu")
    
    reg = load_registry(self.data_dir)
    self.assertEqual(reg.frame_size(new_key), (480, 270))
    
    # Now resize the variant to 240×135 via the existing API.
    registry_ops.set_slot_frame_size(self.data_dir, new_key, 240, 135)
    
    # Reload and verify: variant is 240×135, stem is still 480×270.
    reg = load_registry(self.data_dir)
    self.assertEqual(reg.frame_size(new_key), (240, 135))
    self.assertEqual(reg.frame_size("ui_bg_main_menu"), (480, 270))
```

**Justification:** DetailsPanel spinboxes allow divergence after add; this test
ensures the two are separate entries in the registry.

#### Test 4: `test_written_doc_reloads_without_frame_size_agreement_error`

The new override dict validates and loads without `ValueError` from the registry
loader's `uniqueItems` / frame-size agreement check.

```python
def test_written_doc_reloads_without_frame_size_agreement_error(self):
    # ui_bg_main_menu is 480×270; + Variant yields ui_bg_main_menu_v2 also
    # 480×270 (same key form: both dicts with agreed size).
    new_key = registry_ops.add_variant(
        self.data_dir, "ui", ("Backgrounds",), "Main Menu")
    
    # Reload the registry — if there is a frame-size agreement bug,
    # the loader will raise ValueError here.
    reg = load_registry(self.data_dir)
    
    # Both are present and agree.
    self.assertIn("ui_bg_main_menu", reg.group_slots("ui", ("Backgrounds",)))
    self.assertIn(new_key, reg.group_slots("ui", ("Backgrounds",)))
    self.assertEqual(reg.frame_size("ui_bg_main_menu"),
                     reg.frame_size(new_key))
```

**Justification:** the schema does not express frame-size agreement (two entries
with the same key but different sizes); the loader enforces it. This test proves
the inheritance logic produces agreement.

### Quick Test (human, live editor)

`py editor/main.py` → tree → **UI → Backgrounds → Main Menu**:

1. **Verify the stem is 480×270**: select `ui_bg_main_menu`, check DetailsPanel's
   Frame W/H (should show 480 × 270).
2. **"+ Variant"** → a new slot `ui_bg_main_menu_v<k>` is added to the Main Menu
   group.
3. In DetailsPanel, the **new variant's Frame W/H automatically shows 480 × 270**
   (inherited from the stem, not the category default 64×64).
4. **Change it to 240 × 135** via the spinboxes and **Save** → the variant is
   now independently 240×135, the stem stays 480×270.
5. Verify on disk: `py tools/smoke.py` stays green; `data/sprites/asset_manifest.json`
   (if the slot were imported) would carry one entry; `data/slots.json` carries
   two entries with their own frame sizes in the registry.
6. **Repeat with enemies**: UI → Enemies → Walker → Era 2. Select
   `enemy_stage_2`, add a variant. The new `enemy_stage_2_v<k>` shows the
   category default (64 × 96) in DetailsPanel — it is a bare string, not an
   override. (This is the regression pin: no harm, but the form must stay bare.)
