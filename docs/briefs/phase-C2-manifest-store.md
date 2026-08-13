# Phase C2 — Manifest parse + the frame cut

Plan: `planning/MasterSheetColumnsPLAN.md`, Section **S1 — Column core**, phase
**C2** (the `#### Phase C2` block). Read that block, §2 "Decisions" (D1, D2, D3,
D7, D12), §2 "The one thing forced by layering", and §2 "The core mechanism"
before you start. Read `engine/assets/CLAUDE.md` — it is the normative spec for
this package and it wins over the code graph.

**C2 depends on C1**, which lands FIRST and sequentially. C1 adds the three
optional keys `column`, `column_mode`, `column_width` to
`data/schemas/asset_manifest.schema.json`. You are the engine half: you make the
loader parse them and the store cut with them. If the schema keys are not in
`data/schemas/asset_manifest.schema.json` when you start, STOP and report — C1
has not landed and you would be building against a schema that does not exist.

---

## 1. Goal + file scope

**Goal.** The engine can cut a horizontal COLUMN block out of a master
spritesheet — parsed off the manifest entry, resolved once, applied in exactly
one place — and it caches the result correctly. Nothing designer-facing and
nothing game-facing changes; every existing manifest entry must resolve to the
exact same pixels it does today.

**Files — MODIFIED, and nothing else:**

| File | Why |
|---|---|
| `engine/assets/manifest.py` | `ManifestEntry` gains three fields; `entry_from_dict` parses them |
| `engine/assets/store.py` | the block resolution + clamp, the rect, the two cache keys, two signatures |
| `engine/assets/CLAUDE.md` | ONE new bullet — see §3, this file is shared with C3 |
| `tools/tests/test_assets_manifest.py` | parse tests |
| `tools/tests/test_asset_store.py` | cut / clamp / cache-key tests |

Do NOT create `engine/assets/master_registry.py` (that is C3), do not touch
`engine/render/*` (C3), do not touch `data/**` or any schema (C1), do not touch
`conftest.py` (no new test module is created here).

---

## 2. Design

### 2a. `engine/assets/manifest.py` — parse

Add a module constant beside `ANCHOR_NAMES` (`engine/assets/manifest.py:28-31`),
same shape and same reason (a fixed, declared tuple, not a set literal inline):

```python
# D12: the engine distinguishes "manual" from not-manual and nothing more.
# What a season or a building colour MEANS lives in game/ and editor/.
COLUMN_MODES = ("manual", "season", "building_color")
```

`ManifestEntry` (`manifest.py:83-114`) gains three fields **appended after
`row_start`** (`:104`), each with a default so every existing construction site
is unaffected:

```python
column: int = 0           # 0-based master column this entry cuts from
column_mode: str = "manual"
column_width: int = 0     # frames per master column; 0 => no columns
```

Carry a short comment in the same voice as the `row_start` comment
(`manifest.py:99-103`): this is a **slicing** concern only, `Track.row` /
`playback_order` / `current_frame` keep meaning "row *i* / frame *j* of THIS
entry's own `rows[]`", and `AssetStore._frame_surface` is the single place the
window is applied.

`entry_from_dict` gains three parse blocks immediately after the `row_start`
block (`manifest.py:209-217`), in the **exact defensive shape `row_start` uses**
— that block is your template, copy its structure and its comment's reasoning:

- **No `int()` coercion.** `isinstance(x, bool) or not isinstance(x, int)`
  raises. So `True`, `3.7`, `"3"`, `None`, `[3]` all RAISE. `bool` is checked
  first because it is an `int` subclass.
- `column` — absent ⇒ `0`; present must be a non-bool int and `>= 0`.
- `column_mode` — absent ⇒ `"manual"`; present must be a `str` in
  `COLUMN_MODES`, else raise naming the bad value.
- `column_width` — absent ⇒ `0`; **present must be a non-bool int and `>= 1`.**
  Use a sentinel (or `"column_width" in raw`) to tell absent from present:
  absent means "no columns" (0), while an explicitly authored `0` is invalid.
  This is not an invention — it makes the parser agree exactly with C1's schema,
  which declares `minimum: 1` and treats omission as the no-columns case.

`load_manifest` is unchanged: it is already the E-37 layer that turns any of
these raises into warn-and-skip-**this-entry** (`manifest.py:322-328`). Do not
add tolerance inside `entry_from_dict`, and do not touch `load_registry`
(`engine/assets/registry.py`) — it stays fail-loud.

### 2b. `engine/assets/store.py` — resolve, clamp, cut

Per §2 "The core mechanism" of the plan, made concrete against the real code
(`store.py:199-223`).

**One new private helper — the ONE place a block is resolved:**

```python
def _column_block(self, entry, sheet, column):
    """The resolved master COLUMN this cut comes from (D3/D7).

    `column` is the caller's live column (a season index or a building's
    colour) or None. A stored `column_mode` of "manual" — or the absence of
    a caller value — means the entry's own stored column wins."""
    if entry.column_mode == "manual" or column is None:
        block = entry.column
    else:
        block = column
    if sheet is _LOAD_FAILED or entry.column_width <= 0:
        sheet_cols = 1
    else:
        sheet_cols = sheet.get_width() // (entry.column_width * entry.frame_w)
    return min(block, max(0, sheet_cols - 1))     # D7: clamp, never wrap
```

- **`column is None`, never `if column:`.** A caller passing `column=0` for
  season 0 or colour 0 is a real, live value; falsy-testing it would silently
  fall back to the stored column. This is a one-character bug with no crash.
- `column_width == 0` ⇒ `sheet_cols = 1` ⇒ block clamps to `0`, and
  `0 * 0 + col == col`. See the compatibility pin below.

**`_frame_surface` gains a `column=None` argument** and becomes:

```python
def _frame_surface(self, entry, ref, column=None):
    row, col = ref
    sheet = self._sheet(entry)
    block = self._column_block(entry, sheet, column)
    # The resolved BLOCK is part of the cache key on purpose — see below.
    key = (entry.slot_key, row, col, block)
    if key in self._frames:
        return self._frames[key]
    ...
        sheet_row = row + entry.row_start
        rect = pygame.Rect((block * entry.column_width + col) * entry.frame_w,
                           sheet_row * entry.frame_h,
                           entry.frame_w, entry.frame_h)
```

- **The `self._sheet(entry)` call moves ABOVE the cache check.** It has to: the
  clamp needs the sheet's real width. This is not a performance regression —
  `_sheet` is a dict lookup keyed by path after the first call
  (`store.py:175-197`), the load-failure marker is cached, and the
  could-not-load warning is already emitted exactly once. Say in your report
  that you moved it and why.
- The rect construction stays **the ONE place the column window is applied**,
  exactly as it is the one place the row window is applied
  (`store.py:208-213`). Do not resolve or apply a block anywhere else.
- The off-sheet warning message (`store.py:217-220`) must name the **resolved
  block** alongside the sheet row, so a designer reading the log can tell a bad
  column from a bad row. A rect that still lands off the sheet after the clamp
  degrades to the grey-X placeholder with that warning — never raises (E-37),
  the same path the off-sheet row already takes.

**`hit_opaque`'s mask key must use the SAME block.** `_hit_masks` is built at
`store.py:154` as `(entry.slot_key, row, col)`; it becomes
`(entry.slot_key, row, col, block)`, where `block` comes from the same
`_column_block` helper (call `self._sheet(entry)` for it — cached). A mask keyed
without the block would hit-test column 2 against column 0's alpha.

**The two public signatures gain `column=None` as their LAST keyword:**

```python
def frame(self, slot_key, animation="idle", anim_time_ms=0,
          extra_hidden=None, column=None):

def hit_opaque(self, slot_key, animation="idle", anim_time_ms=0,
               dest_size=None, rel_xy=(0, 0), column=None):
```

Both pass it straight down to `_frame_surface` / `_column_block`. Every existing
call site passes nothing and is unaffected. Document `column` in both
docstrings in the voice `extra_hidden` already uses (`store.py:100-105`).

**Update the `__init__` comment at `store.py:44-60`.** It currently declares
`_frames`/`_hit_masks` as `(slot_key, row, col)` and states that folding
`frame_w`/`frame_h`/`row_start` into the key is a deliberately-not-done
follow-up. That paragraph is now half wrong. Rewrite the `_frames`/`_hit_masks`
lines to the 4-tuple, and add the WHY (see the pin below). Keep the D10 argument
about slot-keying intact — it still holds, and `row_start` is still deliberately
not in the key.

### 2c. THE TWO PINS — read these twice

**PIN 1 — byte-identical compatibility.** An entry with no `column_width`
resolves to `block * 0 + col == col`, i.e. **exactly the pixels it resolves to
today**. This is the compatibility argument for the entire feature — every
committed manifest entry in the repo has no `column_width`, so if this pin
breaks, every sprite in the game moves. Pin it with a byte comparison against a
raw `pygame.image.load(...).subsurface(...)`, not with a colour probe; copy
`test_no_row_start_cuts_exactly_where_it_always_did`
(`tools/tests/test_asset_store.py:406-417`), which already does exactly this via
the `surface_bytes` helper (`:77-80`).

**PIN 2 — the cache key.** `_frames` and `_hit_masks` MUST gain the resolved
block. Two different columns of ONE slot must return two DIFFERENT surfaces.
Forgetting this does not crash — it silently hands column 2 the pixels of column
0, forever, for that slot. It is the sharpest edge in this section (the plan's
§5 Risks names it as such). **Leave a comment in the code saying WHY the block
is in the key**, in the same voice as the existing D10 comment at
`store.py:48-58`, or the next reader will "simplify" it back out — that comment
exists precisely because someone already tried to simplify the sheet/frame key
split.

### 2d. Tests — MINIMUM, not maximum

The plan's Tests list is a **CEILING, not a floor**. Write the bare minimum that
pins the behaviour. The two pins above are non-negotiable; beyond the plan's
list, invent nothing. No exhaustive matrices, no parametrised sweeps over every
mode × every width.

**`tools/tests/test_assets_manifest.py`** — extend the existing
`TestEntryFromDict` class (`:107`) beside the `row_start` tests (`:201-219`):
- the three keys absent ⇒ `0` / `"manual"` / `0` (one test, three asserts);
- the three keys present are parsed onto the entry, and `animations["idle"].row`
  is still `0` (slicing, not playback — mirror `test_row_start_parsed`, `:204`);
- a `subTest` loop of bad values that must raise — copy
  `test_bad_row_start_raises` (`:212-219`) exactly: `(True, 3.7, "3", -1, None,
  [3])` for `column`, the same list plus `0` for `column_width`, and
  `("seasonal", 1, None)` for `column_mode`;
- ONE `load_manifest` tolerance test: an entry with a corrupt `column_mode`
  warns and is skipped while a good sibling entry survives — mirror
  `test_corrupt_row_start_warns_and_skips_that_entry` (`:376`).

Helpers already exist: `row()` (`:27`) and `entry_dict()` (`:39`).

**`tools/tests/test_asset_store.py`** — one new class next to
`TestRowStartWindow` (`:390`), same docstring style:
- extend the module's `entry()` helper (`:87-105`) with `column=None`,
  `column_mode=None`, `column_width=None` kwargs using the same
  `if X is not None: raw[...] = X` shape as `row_start` (`:103-104`);
- `make_grid_sheet` (`:64`) already takes `cols` and `grid_colour(row, col)`
  (`:83`) already encodes the column — build a `cols=12` sheet and use
  `column_width=4` for a 3-column sheet. No new helper needed;
- `column_width=4, column=2` resolves frames from frame-column `2*4 + col`;
- **PIN 1**: no `column_width` ⇒ byte-identical to a raw subsurface;
- a caller-supplied `column` overrides the stored one when
  `column_mode="season"`, and is IGNORED when `column_mode="manual"`;
- a block past the sheet's real column count clamps to the last column (D7);
- **PIN 2**: `store.frame(..., column=0)` and `store.frame(..., column=2)` on
  one slot return two surfaces with different bytes.

---

## 3. Shared files / coordination — READ THIS, IT IS A CONTRACT

**`engine/assets/CLAUDE.md` is edited by BOTH C2 and C3, which run
CONCURRENTLY in separate worktrees.** The file is split into two disjoint
insertion blocks. Touching the other agent's block produces a merge conflict in
a doc, which is the cheapest possible failure and also the most annoying — do
not.

### What C2 (you) own: EXACTLY ONE new bullet

One new bullet in the **"Phase 5 conventions"** list, documenting the optional
`column` / `column_mode` / `column_width` keys. It is the FIFTH-through-SEVENTH
optional per-entry key after `slice`, `anchors`, `tint_overlay`, `row_start` —
write it in that same voice.

**Exact anchor.** Insert it as the sibling immediately AFTER the existing bullet
whose heading is:

```
- **Optional `row_start` (M2, GpuAndMasterSheetsPLAN)**:
```

(`engine/assets/CLAUDE.md:119`) **and after all of that bullet's sub-bullets** —
the last of which ends `…the same path an off-sheet column already took.`
(`:135`). Your new bullet therefore sits between that line and the line that
begins `- **Store**: \`AssetStore(manifest, registry, …` (`:136`).

Your bullet must cover: the three keys and their defaults; D1 (`column_width` is
in FRAMES); D2 (master-sheet-only); D12 (the engine only distinguishes `manual`
from not-manual — it never learns what a season or a colour is); the same
no-`int()`-coercion defensive parse as `row_start`, with `load_manifest` as the
E-37 warn-and-skip layer; that `_frame_surface`'s rect is the ONE place the
column window is applied; that omitted `column_width` ⇒ 0 ⇒ byte-identical; and
a sub-bullet on the clamp (D7, per-sheet, never wraps) and the off-sheet degrade
to the grey X.

### What C3 owns — DO NOT TOUCH

1. **The `**Store**` bullet's `_frames`/`_hit_masks` cache-key sentence**
   (`engine/assets/CLAUDE.md:136-153`, specifically the "`_frames`/`_hit_masks`
   stay SLOT-keyed on purpose (**D10**)…" passage at `:141-147`). Yes, YOU are
   the phase that changes that key — document the new 4-tuple key and its reason
   **inside your own new bullet** (a sub-bullet), and leave the `**Store**`
   bullet's prose alone. C3 reconciles it. Do not "just fix it while I'm here":
   that is the exact edit that collides.
2. **A new short paragraph on `engine/assets/master_registry.py`, appended at
   the END of the "Phase 5 conventions" list** (after the E-38 bullet,
   `:186-197`).

You still update the in-code comment at `store.py:44-60` — that is code, not the
shared doc, and it is yours.

### `tools/tests/test_assets_manifest.py` — no contract needed

C1 also touches this file, but **C1 lands FIRST and sequentially**. You simply
see C1's version of the file when you start. There is nothing to coordinate and
no insertion-point contract here — just add your tests next to the `row_start`
ones and do not delete or restructure C1's `TestMasterSheetSchemas` additions
(`:389+`).

---

## 4. Verification

### Exit gate (verbatim — this is the whole gate)

```
py -m pytest tools/tests/test_assets_manifest.py tools/tests/test_asset_store.py -x -q
py tools/smoke.py
```

Nothing wider. `GATE PASS` / zero failures, and an unexpected skip is a failure.

### Test budget

> Your gate is `py tools/smoke.py` plus `py -m pytest <the specific test files you edited> -x -q`. Nothing wider. You may NOT run the full suite, a tier sweep (`-m core` / `-m editor` / `-m meta`), `py tools/testgate.py check`, or `--affected` — a `PreToolUse` hook denies all four for subagents.
>
> If `test_guard` denies a test command, do NOT re-issue it, do not vary the flags (the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command fingerprints identically), and do not reach for the guard's escape hatch. Report the deny text and the result it quotes back to your orchestrator and stop testing. Retrying is the loop the guard exists to stop.
>
> Two denies are expected and must not be fought: *"already ran this exact target and NOTHING has changed"* (the guard fingerprints the MAIN checkout's diff; worktrees are gitignored, so your own edits can be invisible to it — accept the quoted earlier result, and if it was a FAIL you believe you have since fixed, say exactly that in your report) and *"another test run is already in flight"* (do not wait-loop, do not delete the lock — report and stop).

### Quick Test (run by the orchestrator or the user, NOT by you)

C2 adds no designer surface and no game-visible behaviour, so the in-game test
is a **no-change** test — which is precisely PIN 1 observed live:

1. `py game/main.py`.
2. Place a building, let a wave spawn, pan the map.
3. Every tile, building, enemy and HUD sprite must look **exactly as it did
   before this phase**. Any sprite that moved, changed frame, or turned into a
   grey X means the column block leaked into an entry that has no
   `column_width`, and PIN 1 is broken.

State in your report whether this was a live run or not — do not claim it if you
did not run it.

### Report

Tag every claim **measured** (command + number) / **verified** (read it or ran
it) / **inferred**. Name explicitly: whether both pins are covered by a test,
that you moved `self._sheet(entry)` above the cache check in `_frame_surface`
and why, and the one bullet you added to `engine/assets/CLAUDE.md` (confirming
you did not touch C3's two blocks).
