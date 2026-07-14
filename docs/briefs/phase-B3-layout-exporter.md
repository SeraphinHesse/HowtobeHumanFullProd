# Phase B3 — Tools: layout exporter + committed `screen_defaults.json`

Slice 10L-B (`planning/UI_EDITOR_PLAN.md` lines 309–316). Package: **tools only**
(may import game). Docs: `data/CLAUDE.md`, `tools/CLAUDE.md` (if it exists; else the
root CLAUDE.md's Step 2 exit gate). Depends on B1 (schema) and B2 (ids + skinning);
unblocks B4i (editor integration against real defaults).

---

## 1. Behavioral spec

After B3, a committed `data/ui/screen_defaults.json` exists, byte-identical when
regenerated, containing every named widget's rect and kind across all 12 live screens.

**What must be true**

1. **File existence and schema.** A file `data/ui/screen_defaults.json` exists and
   validates against `data/schemas/screen_defaults.schema.json` (landed by B1).
   Schema shape (per plan line 291): `{<screen_id>: {widgets: {<widget_id>: {rect,
   kind, label}}, mock_note: string}}` for all 12 screens: `main_menu, pause,
   settings, credits, add_name, game_over, levelup, hud, building_panel,
   cheat_menu, game_log, boss_cutscene` (plan line 281–282, R3).

2. **Content precision.** For each screen: every **named widget** (i.e. every widget
   stored in the screen's `ids` dict per B2, `game/ui/skinning.py` line ~296) emits
   one entry with:
   - **`rect`**: `[x, y, w, h]` in logical pixels (1280×720 resolution, per
     `data/display.json` `window_w`/`window_h`, plan line 95)
   - **`kind`**: taken from the screen's `ids` mapping pair `(kind, widget)`
     (B2's contract) — always one of the six enum values pinned by
     `data/schemas/screen_defaults.schema.json`: `"button" | "panel" |
     "label" | "backdrop" | "bar" | "field"`. NEVER `type(widget).__name__`
     (class names would fail schema validation on the first export).
   - **`label`**: the widget's text content (empty string if no label; plan line 291)
   - Widgets WITHOUT ids are NOT listed (dynamic list items, floaters, etc. are
     not overridable per plan decision 3, line 142–144).

3. **Mock state (production run).** The exporter constructs each screen with canned
   state (plan lines 95–100):
   - **Common (all screens)**: `love=123, round=7`
   - **`hud`, `building_panel`**: mid-game selection — building chosen, upgrade panel
     visible (no crash on dynamic items)
   - **`boss_cutscene`** (per R3 contract, lines 94–100): `open(1, "win")` + `layout(1280, 720)` call
   - Other screens (menu, pause, etc.) construct with no world state (idle defaults)

4. **Headless execution.** The exporter runs completely headless: SDL dummy drivers
   set in-code **before** pygame import (plan line 95, same pattern as
   `tools/tests/test_game_boot.py:14`), no window, no frame delivery. Never crashes
   on missing art (E-37 grey-X fallback applies); never logs an error on valid
   asset absence.

5. **Deterministic + idempotent output.** Running the exporter twice (with no data
   changes) yields byte-identical `screen_defaults.json`: sorted keys, 2-space
   indent, trailing newline (D-3 canonical form). Committed output is pinned by
   diffs; merge conflicts resolved ONLY by re-running the exporter, never by
   hand-editing.

6. **Injectable paths.** The exporter accepts optional `data_root=None` and
   `output_dir=None` parameters (the repo-wide convention from `test_game_boot.py`)
   so tests regenerate into temp directories without touching the repo's live
   `data/`. Defaults to the repo root's `data/` and `data/ui/` respectively.

7. **Single-run semantics.** The exporter is a standalone script — `py
   tools/export_ui_layouts.py [--data-root PATH] [--output-dir PATH]` — with no
   interactive state, no caching across invocations. Each run reads fresh screen
   code and mock state.

Out of scope for B3: no game/** edits (if a screen can't construct headless, that
is a finding to report, not a fix here), no editor/**, no engine/**, no new schema
keys (B1 owns them).

---

## 2. Architecture plan

### Edit 1 — `tools/export_ui_layouts.py` (NEW file)

A pure Python script (no pygame until the SDL dummy setup). Entry point:
`main(data_root=None, output_dir=None)` or equivalent, called from `if __name__ ==
"__main__": sys.exit(main())`.

**Structure** (order matters):

1. **SDL dummy setup (before pygame)** — same as `tools/tests/test_game_boot.py:14`:
   ```python
   import os
   os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
   os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
   ```
   Place this BEFORE any `import pygame` or game/engine imports that might pull
   pygame transitively. This prevents window creation and audio device access.

2. **Imports & paths** — resolve `data_root` and repo root exactly as
   `test_game_boot.py:22–30` does (tempfile copy pattern, but here the paths are
   just parameters).

3. **Loop over 12 screen ids** (plan line 282) in a stable order (e.g.
   alphabetical or the order listed in the plan):
   ```python
   for screen_id in SCREEN_IDS:  # main_menu, pause, ... boss_cutscene
       defaults = build_screen_defaults(screen_id, data_root)
       output[screen_id] = defaults
   ```

4. **Per-screen `build_screen_defaults(screen_id, data_root)` function**:
   - **Construct the screen object** with canned mock state. Each screen class
     lives in `game/ui/` (e.g. `game/ui/main_menu.MainMenu()` for the main menu
     screen). Mock state:
     - **`core_state` mock** (the minimal state object screens expect):
       ```python
       class CoreState:
           love = 123
           round = 7
           level = 1  # or other defaults
       ```
     - **`session_state` mock** (if needed for building_panel/hud): round,
       phase, etc. as needed to avoid crashes
     - **`world` mock** (if `building_panel` needs it): a minimal scene with one
       placed building in mid-game state
     - **Exact mock construction:** keep mock complexity minimal — only enough to
       avoid crashes. `ValueError` on insufficient mock state is a FINDING to
       report; do not add ad-hoc skips.
   - **Call `layout(1280, 720)`** on the screen object (the logical resolution from
     `data/display.json` — do NOT hardcode, do NOT invent a separate logical key;
     use the values from the JSON).
   - **Extract the `ids` mapping** from the screen object's `ids` dict (landed
     by B2): each entry is `widget_id -> (kind, widget)`. For each entry:
     - Rect: the widget's rect — `widgets.Button.rect` is an `(x, y, w, h)`
       tuple; bare rect-holders expose the same shape (B2 guarantees every
       ids target has a readable rect) → `[x, y, w, h]`
     - Kind: the pair's `kind` string (already schema-legal, see above)
     - Label: the widget's `label` attribute if present, else `""`
     - Append entry to the screen's widgets dict
   - **Append a `mock_note` string** documenting the canned state (for human
     review, not validation): `"love=123, round=7, …"` or `"open(1, 'win')"` for
     boss_cutscene

5. **Write output** via `engine.data_io.write_validated`:
   ```python
   from engine import data_io
   output_path = output_dir / "ui" / "screen_defaults.json"
   schema_path = data_root / "schemas" / "screen_defaults.schema.json"
   data_io.write_validated(output, output_path, schema_path)
   ```
   This enforces D-3 canonical form (sorted keys, 2-space indent) and fails loud
   on schema violation.

6. **Error handling** — any screen construction failure raises with context; the
   script exits non-zero. No silent skips.

### Edit 2 — `tools/tests/test_ui_layout_export.py` (NEW test file)

Staleness gate: regenerates the defaults into a temp dir and asserts byte-identity.

**Structure**:

```python
import tempfile
import unittest
from pathlib import Path
from tools.export_ui_layouts import main as export_main  # call the exporter
from engine import data_io

class TestUILayoutExportStaleness(unittest.TestCase):
    def test_committed_defaults_are_fresh(self):
        """Regenerate screen_defaults.json in a tempdir and assert it matches
        the committed version byte-for-byte."""
        repo = Path(__file__).resolve().parents[2]
        live_path = repo / "data" / "ui" / "screen_defaults.json"
        live_bytes = live_path.read_bytes()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            # Exporter writes to output_dir / "ui" / "screen_defaults.json"
            export_main(data_root=repo / "data", output_dir=tmpdir)
            temp_path = tmpdir / "ui" / "screen_defaults.json"
            temp_bytes = temp_path.read_bytes()
        
        self.assertEqual(temp_bytes, live_bytes,
            "committed screen_defaults.json is stale; run `py tools/export_ui_layouts.py`")
```

- Test does NOT depend on live-data values beyond the committed `screen_defaults.json` it diffs
- Test reads `FIXTURE_DATA` conventions only if absolutely necessary (per plan spec —
  avoid unpinned values)
- Test runs quickly (temp file I/O only, no pygame render)
- A stale committed file (developer forgot to re-export after a screen layout
  change) fails the suite

### Edit 3 — `conftest.py` (one line in TIERS dict)

Add the line (plan line 316 says "conftest.py: add one TIERS line"):
```python
    "test_ui_layout_export": "core",
```

This tier marker ensures the test runs as part of `py tools/testgate.py check
--affected` and `py -m pytest -m core`. Tier choice: `"core"` (not editor, not
meta) — it tests game logic in a pure Python setting, no Qt. See `conftest.py:36–116`
(the TIERS table) for context.

---

## 3. File scope + shared-file contract

**The B3 coder may touch exactly these files. Nothing else.**

| File | What B3 does | Reads only / Writes |
|---|---|---|
| `tools/export_ui_layouts.py` | NEW — the headless exporter script | N/A (writes) |
| `data/ui/screen_defaults.json` | NEW — generated output (committed) | write_validated |
| `tools/tests/test_ui_layout_export.py` | NEW — staleness gate test | N/A (writes) |
| `conftest.py` | add one `TIERS` line at line ~99 | write (1 line) |
| `data/display.json` | read only — logical resolution | read |
| `data/schemas/screen_defaults.schema.json` | read only — validation schema | read |

**Do NOT touch:**
- `game/**` (screens must already construct headless with mock state; if they
  don't, that is a finding to REPORT, not fix here)
- `editor/**`
- `engine/**`
- `data/schemas/*` (B1 owns schema definitions — conform or report)
- Any balancing file or other data/ content

**Shared-file contract — `conftest.py`:**

The TIERS dict at lines 36–116 maps test module stems to tier markers. B3 adds
exactly one line, **alphabetically in the `core` section** (line ~96, after
`"test_tiers"`, before `"test_ui_layout_export"`... actually,
`"test_ui_layout_export"` goes in alphabetical order in the `core` block). Keep
the format consistent (quoted key, quoted value, trailing comma if not last in
the block).

---

## 4. Exit gate + Quick Test

### Commands

```bash
py tools/smoke.py                    # schema validation (includes screen_defaults.json)
py tools/testgate.py check --affected  # run tests marked core and meta
```

**Gate = ZERO failures** (`GATE PASS`), including
`test_ui_layout_export.py::TestUILayoutExportStaleness`. No baseline, no
tolerated failures — the old "16 known failures" lore is dead.

### Quick Test (developer, local)

1. **Idempotence test**:
   ```bash
   py tools/export_ui_layouts.py
   cp data/ui/screen_defaults.json data/ui/screen_defaults.json.backup
   py tools/export_ui_layouts.py
   diff data/ui/screen_defaults.json data/ui/screen_defaults.json.backup
   ```
   Expected: diff reports no difference (byte-identical).

2. **Spot-check the output** — open `data/ui/screen_defaults.json` in an editor:
   - Verify the 12 screen ids exist as top-level keys
   - For `main_menu`: spot-check that the five buttons (or however many are named
     in the ids dict) have sane rects, e.g.:
     - `"btn_new_game"` has a rect with w>0, h>0, within 1280×720
     - `"title"` has a y coordinate near the top (y<100)
   - For `hud`: verify love_panel / income_panel / lives_panel exist and have rects
   - For `boss_cutscene`: verify it exists and has the modal boxes

3. **Run the suite**:
   ```bash
   py tools/testgate.py check --affected
   ```
   Expected: GATE PASS (zero NEW failures).
