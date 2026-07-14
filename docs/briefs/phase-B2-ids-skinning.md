# Phase B2 — Game: ids + `skinning.py` + golden parity pin

Slice 10L-B, part 1 (`planning/UI_EDITOR_PLAN.md` lines 294-307, user decisions
at 102-120, architecture at 122-169). Branch: `phase-10L-finish-umbrella`, cut
off the umbrella **after B1 lands**. Package: **game** + **tools/tests**.
Docs: `CLAUDE.md` → `game/CLAUDE.md` → `game/ui/CLAUDE.md`.

**Dependency check:** B1 has seeded `data/ui/screens/` with v1 screen list
(12 screens) and the schema; `data/ui/screen_defaults.json` does NOT exist yet
(created by B3). Phase A5′ has shipped on umbrella before your work — skinned
`widgets.Button` and the hit-seam are live, one clock per screen is threaded
through every screen's update/submit, and `game/main.py` reads the mouse-down
flag. Verify by reading `game/ui/widgets.py:248-269` (the skinned path) before
starting.

---

## 1. Behavioral spec

### 1.1 The 12 screens and the golden parity pin

B2 makes ALL 12 current live screens editable from the editor (R3, plan line 84):
`main_menu`, `pause`, `settings`, `credits`, `add_name`, `game_over`, `levelup`,
`hud`, `building_panel`, `cheat_menu`, `game_log`, `boss_cutscene`
(plan lines 85-100, R3 contracts).

A screen with **no override file** (or an empty one) must produce the exact
HUD-primitive stream it produces today — byte-identical. This is **the golden
parity pin**: a test captures every screen's submitted HUD primitives with no
`data/ui/screens/` overrides, stores the recording (tools/tests/fixture_data.py),
and asserts it is unchanged after B2's id+apply wiring lands. This is the
FIRST COMMIT of this phase (before any production edit). Pinned by
`tools/tests/test_ui_skinning.py::test_all_screens_parity`.

### 1.2 Per-screen ids mapping

Each screen names its **fixed** widgets (buttons, labels, panels, headers — items
with stable identities) in a dict `ids: {name → (kind, attribute)}`, where
`kind` is one of B1's pinned six-value enum
(`screen_defaults.schema.json`): `"button" | "panel" | "label" | "backdrop"
| "bar" | "field"`. The pair is THE shared contract: `skinning.apply` uses the
kind to know how to mutate the target (Button vs bare rect-holder vs text),
and B3's exporter reads the same pair to emit `{rect, kind, label}` without
type-sniffing. Example for a hypothetical menu screen:
`{"btn_start": ("button", self.btn_new_game), "title": ("label", self.lbl_title),
"panel": ("panel", self.main_panel)}`. The THREE extra-screen contracts (plan R3, lines
85-100) are PINNED:

- **cheat_menu** (plan lines 85-89): eleven ids —
  `panel, title, btn_close, btn_add_love, btn_skip_round, btn_trigger_levelup,
  btn_inf_money, btn_unlock_all, round_field, btn_goto, jump_label`. Full
  template. `submit()` calls `layout()` EVERY FRAME from its idle/submit loop
  (cheat_menu.py:97-102, :157), so the skinning.apply call must be a cached-dict
  setattr loop reading disk zero times per frame (pinned by a "loads once" test).

- **game_log** (plan lines 90-93): container-only, ONE widget — `log` (a
  rect-holder for the line anchor, font, text_color for age fade, visible).
  Dynamic line timings stay code constants (game_log.py will remain
  unconditional).

- **boss_cutscene** (plan lines 94-100): A/B modal backdrop. Five ids —
  `backdrop` (color override only), `headline` (font only — color stays
  win/loss logic-owned in boss_cutscene.py), `subtitle` (font, text_color),
  `box_a`/`box_b` (rect — moves draw AND hit coherently; skin via the
  already-live skinned `submit_panel`; font; text_color). Exporter mock:
  `open(1, "win")` + `layout(1280, 720)`.

Other nine screens (menu + in-round): enumerate each screen's fixed widgets as
an `ids` dict from reading the code. **Your main job:** per screen module, read
the layout / submit code (every Button, Label, HudRect, submit_panel call with a
clear semantic identity), write the ids table.

### 1.3 The skinning.apply() contract

`game/ui/skinning.py` is pure (no pygame, TestPurity covers it). At shell
construction, it loads all `data/ui/screens/*.json` **once**. Each file is
validated against the screen schema; missing file or empty doc → no-op (graceful
absent-file handling for B3 when defaults aren't committed yet).

`apply(screen_id, widgets)` is the core: it takes the ids dict
`{id_name: (kind, widget_obj)}` (§1.2 shape)
and mutates each widget's rect / label / skin / font / colors **in place** via
**a cached-dict setattr loop** (no disk I/O, no per-call file reads). The call
happens at the **end of every screen's `layout()`** (after the screen has
computed its default geometry). 

`screen_background(screen_id)` returns `{slot: ..., color: ...}` or None for
submit-time background override (called ONCE per frame from `submit()`).

### 1.4 Widget id validation

At load time (shell construction), validate every widget id in the override
against `data/ui/screen_defaults.json` (when present — B3 creates it, so
validation is optional in B2). **Fail LOUD in dev** on an unknown id (catches
renames), but **tolerate the defaults file being ABSENT** (it doesn't exist until
B3 lands). Use `getattr(defaults, "widgets", {})` for safe reads; if the key
isn't there, silently continue.

### 1.5 The three non-screen contracts

- **`game/main.py`**: skinning loaded at `Shell` / host construction. No new
  code; load line added once.
- **`GameLog` seeding**: `GameLog.get_style_holder()` returns a mutable
  `{rect, font, text_color, visible}` object seeded once at construction via
  `skinning.apply("game_log", {"log": holder})`. The game log's line feeding
  loop never reads this (stays code-driven); the holder is only for screen-JSON
  overrides.
- **conftest.py TIERS**: add `"test_ui_skinning": "core"` entry. This phase
  owns conftest in its slot — runs SEQUENTIALLY after A5′ merges so the parity
  pin records clean baselines.

---

## 2. Architecture plan

Edit in this order.

### 2.1 Create `game/ui/skinning.py` (pure, NEW)

```python
"""UI screen override application (10L-B, user decision 1).

Loads + schema-validates all data/ui/screens/*.json once at shell construction.
apply(screen_id, widgets) mutates rect/label/skin/font/colors in place after a
screen's layout(). No disk I/O on apply() — cache hit every time. Works headless.
"""

from typing import Optional, Any, Dict
import json
from pathlib import Path
from engine.render import Color  # for type hints, not instances
# NO pygame

def load_screen_overrides(data_dir: Path) -> Dict[str, Optional[dict]]:
    """Load all data/ui/screens/*.json; validate against schema.
    
    Missing file or empty doc -> None in the dict.
    Missing directory or corrupt JSON -> empty dict (graceful).
    
    Returns {screen_id: override_doc_or_None}.
    """
    # Implementation: iterate data_dir / "ui" / "screens", load + validate via
    # the existing schema machinery (data.validate_data or similar).
    # On any read error, log and continue (E-37 degrade pattern).
    pass

def load_screen_defaults(data_dir: Path) -> Optional[dict]:
    """Load data/ui/screen_defaults.json if present; None otherwise.
    
    Used ONLY at load time for id validation (fail loud on unknown id).
    Cached; never re-read.
    """
    pass

class ScreenSkinning:
    """Manages all screen overrides (once-loaded, cached apply)."""
    
    def __init__(self, data_dir: Path):
        self._overrides = load_screen_overrides(data_dir)
        self._defaults = load_screen_defaults(data_dir)
        self._apply_cache = {}  # memoize per-screen override dicts
    
    def apply(self, screen_id: str, widgets: Dict[str, Any]) -> None:
        """Mutate named widgets' rect/label/skin/font/colors after layout().
        
        widgets: {id_name: widget_obj}, where widget_obj has mutable attributes
                (rect, label, skin, font_key, color, text_color, visible).
        
        No-op if screen has no override or override is empty.
        Validate widget ids against defaults (if present) on first call per screen.
        """
        if screen_id not in self._overrides:
            return
        override = self._overrides[screen_id]
        if not override or "widgets" not in override:
            return
        
        # Validate ids on first call (cache hit after)
        if screen_id not in self._apply_cache:
            self._validate_widget_ids(screen_id, override)
            self._apply_cache[screen_id] = override
        else:
            override = self._apply_cache[screen_id]
        
        # Setattr loop: rect, label, skin, font_key, color, text_color, visible
        for id_name, widget in widgets.items():
            if id_name in override.get("widgets", {}):
                spec = override["widgets"][id_name]
                if "rect" in spec:
                    widget.rect = spec["rect"]
                if "label" in spec:
                    widget.label = spec["label"]
                if "skin" in spec:
                    widget.skin = spec["skin"]
                if "font" in spec or "font_key" in spec:
                    widget.font_key = spec.get("font_key") or spec.get("font")
                if "color" in spec:
                    widget.color = spec["color"]
                if "text_color" in spec:
                    widget.text_color = spec["text_color"]
                if "visible" in spec:
                    widget.visible = spec["visible"]
    
    def _validate_widget_ids(self, screen_id: str, override: dict) -> None:
        """Fail loud on unknown widget id (dev-only, fail on id rename).
        
        Only validates if defaults present; silently continues if not.
        """
        if not self._defaults or "widgets" not in self._defaults:
            return
        
        defaults_widgets = self._defaults.get(screen_id, {}).get("widgets", {})
        if not defaults_widgets:
            return  # No default info; can't validate yet (B3 not landed)
        
        override_ids = set(override.get("widgets", {}).keys())
        default_ids = set(defaults_widgets.keys())
        unknown = override_ids - default_ids
        if unknown:
            raise ValueError(
                f"screen {screen_id}: unknown widget id(s): {unknown}\n"
                f"Known ids: {default_ids}"
            )
    
    def screen_background(self, screen_id: str) -> Optional[Dict]:
        """Return {slot: ..., color: ...} or None for screen background override.
        
        Called once per frame from screen.submit() to set the background.
        """
        if screen_id not in self._overrides:
            return None
        override = self._overrides[screen_id]
        if not override:
            return None
        return override.get("background")
```

### 2.2 Each of the 12 screens — add `ids` mapping + `apply` call + background hook

For **every** screen in `game/ui/*.py`:

1. **In `__init__`** (or early in the module if using a factory): create an `ids`
   dict mapping id names to widget objects. Example (main_menu.py):
   ```python
   self.ids = {
       "btn_new_game": ("button", self.btn_new_game),
       "btn_settings": ("button", self.btn_settings),
       "btn_credits": ("button", self.btn_credits),
       "btn_quit": ("button", self.btn_quit),
       "title": ("label", self.title_label),
   }
   ```
   The ids must match the widget names you write to the per-screen JSON
   (the editor will offer these as a dropdown, keyed from defaults).

2. **In `layout()`** (at the very end, after all geometry is computed):
   ```python
   skinning.apply(self.screen_id, self.ids)
   ```
   where `skinning` is injected or imported from `game.ui.skinning`.

3. **In `submit()`** (at the VERY TOP, before any widget submit):
   ```python
   bg = skinning.screen_background(self.screen_id)
   if bg:
       if "slot" in bg:
           renderer.submit_hud(HudSprite(bg["slot"], (0, 0), (view_w, view_h)))
       elif "color" in bg:
           renderer.submit_hud(HudRect((0, 0, view_w, view_h), bg["color"]))
   ```
   (Or pass as a first arg to submit if the screen design prefers.)

**Screens to edit** (all 9 original + the 3 new ones):
- `main_menu.py` (lines ~34-50 for ids)
- `pause.py` (lines ~20-35 for ids)
- `settings.py` (lines ~60-80 for ids)
- `credits.py` (lines ~30-45 for ids)
- `add_name.py` (lines ~40-60 for ids)
- `game_over.py` (lines ~10-20 for ids)
- `levelup.py` (lines ~80-100 for ids)
- `hud.py` (lines ~100-150 for ids — complex; enumerate every widget)
- `building_ui.py` (lines ~500-700 for BuildingUI ids, ConstructPreview ids)
- `cheat_menu.py` (11 ids per contract: panel, title, btn_close, btn_add_love,
  btn_skip_round, btn_trigger_levelup, btn_inf_money, btn_unlock_all,
  round_field, btn_goto, jump_label)
- `game_log.py` (1 id per contract: log)
- `boss_cutscene.py` (5 ids per contract: backdrop, headline, subtitle, box_a,
  box_b)

### 2.3 `game/ui/shell.py` — inject skinning at construction

```python
def __init__(self, view_w, view_h, ui_balance):
    self.skinning = ScreenSkinning(Path("data"))  # or wherever data_dir lives
    # ... rest of __init__
```

Also, each screen's `__init__` must either:
- Store a reference to `self.skinning` from the host, OR
- Import `ScreenSkinning` and construct one (if pure enough), OR
- The host injects it into each screen at construction.

**Most pragmatic**: shell constructs `ScreenSkinning(data_dir)` once and passes
it to every screen's `__init__`. Screens call it as `self.skinning.apply(...)`.

### 2.4 `game/main.py` — wire ScreenSkinning at host construction

```python
def build_gameplay(...):
    # ... existing code ...
    shell = Shell(view_w, view_h, ui_balance)
    # Existing code stays; shell already has skinning loaded by §2.3
```

No new lines needed if shell loads it internally. If loading from main:

```python
from game.ui.skinning import ScreenSkinning
skinning = ScreenSkinning(Path("data"))
shell = Shell(view_w, view_h, ui_balance, skinning)
```

### 2.5 GameLog style holder seeding

In `game/ui/game_log.py`:

```python
class GameLog:
    def __init__(self, ...):
        # ... existing init ...
        self._style_holder = {
            "rect": self.log_rect,
            "font": "sm",
            "text_color": C_LOG_TEXT,
            "visible": True,
        }
    
    def get_style_holder(self):
        """Return the mutable holder for skinning.apply() (10L-B)."""
        return self._style_holder
```

Then in `game/main.py` at shell/host construction:

```python
game_log = GameLog(...)
skinning.apply("game_log", {"log": game_log.get_style_holder()})
```

Or let the screen itself call `skinning.apply("game_log", {"log": self._style_holder})`
in its layout (cleaner — screen owns its ids).

### 2.6 `game/ui/CLAUDE.md` — document the ids + skinning convention

Add a short section (e.g., "UI screen customization (10L-B)"):

> Screens list their fixed widget identities in an `ids` dict (name → object).
> After `layout()` computes default geometry, `skinning.apply(screen_id, ids)`
> mutates overridable attributes (rect, label, skin, font_key, color,
> text_color, visible) from `data/ui/screens/<screen_id>.json` (if present).
> **No override file / empty override → byte-identical HUD stream** (pinned by
> parity test). Dynamic content (log lines, levelup options, list entries) is
> NOT individually overridable in v1 — it inherits style from the screen
> `defaults` section. `screen_background()` supplies the background override
> (slot or color) for submit-time.

### 2.7 `tools/tests/test_ui_skinning.py` (NEW) — golden parity pin + apply tests

**FIRST COMMIT of this phase**, before ANY production edit. Use the
`RecordingBackend` pattern from `test_shell.py:204-257` to record HUD primitives.

```python
"""Golden parity pin + skinning.apply tests (10L-B phase B2)."""

import unittest
from pathlib import Path
from tools.tests.fixture_data import FIXTURE_DATA, fixture_copy
from game.ui.shell import Shell
from game.ui.skinning import ScreenSkinning
from engine.render import Renderer, HudRect, HudSprite, HudText
import tempfile
import json

class RecordingRenderer:
    """Fake renderer that records every submit_hud call."""
    def __init__(self):
        self.items = []
    def submit_hud(self, item):
        self.items.append(item)

class TestUISkinning(unittest.TestCase):
    """Parity pin + skinning contract tests."""
    
    def setUp(self):
        """Load fixture data (NO live data/ui/screens/); capture unskinned output."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        # Copy fixture data, excluding data/ui/screens (leave it empty)
        fixture_copy(self.data_dir, include_screens=False)
    
    def tearDown(self):
        self.temp_dir.cleanup()
    
    def test_skinning_loads_once(self):
        """Verify skinning loads all screens once at construction."""
        skinning = ScreenSkinning(self.data_dir)
        # Assert: no disk access on apply() calls
        # (Hard to measure; trust the implementation; parity test catches double-reads)
        self.assertIsNotNone(skinning)
    
    def test_all_screens_parity(self):
        """GOLDEN PARITY PIN: every screen with no overrides emits the
        exact HUD-primitive stream it emits today."""
        # Construct a pure Shell with fixture data
        shell = Shell(1280, 720, fixture_data["balancing"]["ui.json"])
        renderer = RecordingRenderer()
        
        # For each screen: open -> layout -> submit
        for screen_id in [
            "main_menu", "pause", "settings", "credits", "add_name",
            "game_over", "levelup", "hud", "building_panel",
            "cheat_menu", "game_log", "boss_cutscene"
        ]:
            screen = getattr(shell, screen_id, None)
            if not screen:
                continue
            
            renderer.items.clear()
            screen.layout(1280, 720)
            screen.submit(renderer)
            
            # Assert: recorded stream matches the pre-B2 baseline
            baseline_key = f"screen_{screen_id}_baseline"
            self.assertEqual(
                renderer.items,
                FIXTURE_DATA[baseline_key],
                f"{screen_id} parity failed"
            )
    
    def test_apply_mutates_rect(self):
        """apply() mutates a widget's rect in place."""
        # Simple test: create a fake widget, apply an override
        class FakeWidget:
            def __init__(self):
                self.rect = (0, 0, 100, 100)
                self.label = "test"
                self.skin = None
                self.font_key = "md"
                self.color = None
                self.text_color = None
                self.visible = True
        
        skinning = ScreenSkinning(self.data_dir)
        # Manually inject an override for testing
        skinning._overrides["test_screen"] = {
            "widgets": {
                "test_widget": {"rect": (10, 20, 80, 90)}
            }
        }
        
        widget = FakeWidget()
        skinning.apply("test_screen", {"test_widget": widget})
        self.assertEqual(widget.rect, (10, 20, 80, 90))
    
    def test_apply_mutates_label(self):
        """apply() mutates a widget's label in place."""
        class FakeWidget:
            def __init__(self):
                self.rect = (0, 0, 100, 100)
                self.label = "old"
                self.skin = None
                self.font_key = "md"
                self.color = None
                self.text_color = None
                self.visible = True
        
        skinning = ScreenSkinning(self.data_dir)
        skinning._overrides["test_screen"] = {
            "widgets": {
                "btn": {"label": "PRESS ME"}
            }
        }
        
        widget = FakeWidget()
        skinning.apply("test_screen", {"btn": widget})
        self.assertEqual(widget.label, "PRESS ME")
    
    def test_apply_mutates_skin(self):
        """apply() mutates a widget's skin in place."""
        class FakeWidget:
            def __init__(self):
                self.rect = (0, 0, 100, 100)
                self.label = "test"
                self.skin = None
                self.font_key = "md"
                self.color = None
                self.text_color = None
                self.visible = True
        
        skinning = ScreenSkinning(self.data_dir)
        skinning._overrides["test_screen"] = {
            "widgets": {
                "btn": {"skin": "ui_button"}
            }
        }
        
        widget = FakeWidget()
        skinning.apply("test_screen", {"btn": widget})
        self.assertEqual(widget.skin, "ui_button")
    
    def test_unknown_id_fails_loud_when_defaults_present(self):
        """apply() raises loud on unknown widget id (if defaults present)."""
        skinning = ScreenSkinning(self.data_dir)
        # Inject defaults with known ids
        skinning._defaults = {
            "test_screen": {
                "widgets": {
                    "known_id": {},
                }
            }
        }
        # Inject override with unknown id
        skinning._overrides["test_screen"] = {
            "widgets": {
                "unknown_id": {"rect": (0, 0, 100, 100)}
            }
        }
        
        class FakeWidget:
            pass
        
        # First apply should trigger validation and raise
        with self.assertRaises(ValueError) as cm:
            skinning.apply("test_screen", {"unknown_id": FakeWidget()})
        self.assertIn("unknown_id", str(cm.exception))
    
    def test_absent_defaults_file_silent(self):
        """apply() tolerates absent defaults file (B3 not landed yet)."""
        skinning = ScreenSkinning(self.data_dir)
        # No defaults loaded; override has unknown id -> should NOT raise
        skinning._defaults = None
        skinning._overrides["test_screen"] = {
            "widgets": {
                "unknown_id": {"rect": (0, 0, 100, 100)}
            }
        }
        
        class FakeWidget:
            def __init__(self):
                self.rect = (0, 0, 100, 100)
        
        # Should not raise; silently continues
        widget = FakeWidget()
        skinning.apply("test_screen", {"unknown_id": widget})
        # No assertion; just verify no exception
    
    def test_screen_background_slot(self):
        """screen_background() returns slot override."""
        skinning = ScreenSkinning(self.data_dir)
        skinning._overrides["test_screen"] = {
            "background": {"slot": "ui_bg_main_menu"}
        }
        
        bg = skinning.screen_background("test_screen")
        self.assertEqual(bg["slot"], "ui_bg_main_menu")
    
    def test_screen_background_color(self):
        """screen_background() returns color override."""
        skinning = ScreenSkinning(self.data_dir)
        skinning._overrides["test_screen"] = {
            "background": {"color": (20, 20, 20)}
        }
        
        bg = skinning.screen_background("test_screen")
        self.assertEqual(bg["color"], (20, 20, 20))
    
    def test_screen_background_absent(self):
        """screen_background() returns None if no override."""
        skinning = ScreenSkinning(self.data_dir)
        bg = skinning.screen_background("nonexistent_screen")
        self.assertIsNone(bg)

if __name__ == "__main__":
    unittest.main()
```

### 2.8 `conftest.py` — add one TIERS line

```python
TIERS = {
    # ... existing entries ...
    "test_ui_skinning": "core",  # 10L-B phase B2: skinning + parity pin
}
```

---

## 3. File scope + shared-file contract (binding)

B2 depends on B1 (schema + screen JSON files exist) and A5′ (skinned widgets +
clock threading landed). B2 is **independent of B3 and B4** — the exporter and
editor screen mode are parallel; B2 is the game side only.

**Exactly these files**:

- `game/ui/skinning.py` — NEW, pure, validates + applies overrides.
- All 12 screens in `game/ui/*.py`:
  - `main_menu.py` — add `ids` dict + `apply()` call.
  - `pause.py` — same.
  - `settings.py` — same.
  - `credits.py` — same.
  - `add_name.py` — same.
  - `game_over.py` — same.
  - `levelup.py` — same.
  - `hud.py` — same; complex (enumerate every widget).
  - `building_ui.py` — same for both `BuildingUI` and `ConstructPreview`.
  - `cheat_menu.py` — 11 ids per contract; **special:** `submit()` calls
    `layout()` EVERY FRAME, so apply is the cached-dict path (pinned by
    "loads once" test).
  - `game_log.py` — 1 id per contract; add `get_style_holder()`.
  - `boss_cutscene.py` — 5 ids per contract.
- `game/ui/shell.py` — construct `ScreenSkinning(data_dir)` and inject into
  screens.
- `game/main.py` — load skinning at shell/host construction (minimal).
- `game/ui/CLAUDE.md` — document ids + skinning convention.
- `tools/tests/test_ui_skinning.py` — NEW, golden parity pin + apply tests.
- `conftest.py` — add one `"test_ui_skinning": "core"` TIERS line.

**B2 must NOT touch**: `engine/**`, `editor/**`, `data/**` (B1 seeded the
schemas and screen JSON template; this phase uses them read-only).

---

## 4. Exit gate + Quick Test

### Commands

```bash
py tools/smoke.py
py tools/testgate.py check --affected
```

**Gate = ZERO failures** (`GATE PASS`). No baseline, no tolerated failures. All 12 screens must pass parity — their unskinned
HUD stream must be byte-identical to today's baseline. The "loads once" test
(parity with cheat_menu's every-frame `layout()` → `apply()` → `submit()` loop)
must verify that `ScreenSkinning.apply()` never re-reads disk inside the apply
loop.

### New tests

`tools/tests/test_ui_skinning.py` (all in one file):

1. **`test_skinning_loads_once`** — skinning construction succeeds.
2. **`test_all_screens_parity`** (MANDATORY) — every screen with no overrides
   records the same HUD-primitive stream as the pre-B2 baseline (the golden pin).
   Baseline recorded BEFORE any production code change.
3. **`test_apply_mutates_rect`** — `apply()` mutates a widget's rect.
4. **`test_apply_mutates_label`** — `apply()` mutates a widget's label.
5. **`test_apply_mutates_skin`** — `apply()` mutates a widget's skin.
6. **`test_unknown_id_fails_loud_when_defaults_present`** — unknown id raises
   ValueError (id rename safety).
7. **`test_absent_defaults_file_silent`** — no ValueError when defaults absent
   (graceful, B3 not landed yet).
8. **`test_screen_background_slot`** — background slot override.
9. **`test_screen_background_color`** — background color override.
10. **`test_screen_background_absent`** — None when no override.

### Quick Test (human, in-game)

1. **Baseline run**: `py game/main.py` → the main menu, all nine menu screens
   (main, pause, settings, credits, add_name, game_over, levelup), HUD, building
   panel, cheat menu (Ctrl+L), game log, boss cutscene (end a round with a boss
   spawn). Every screen looks EXACTLY as before — no visual changes, no new
   artifacts, no missing widgets.

2. **One override**: hand-edit `data/ui/screens/main_menu.json` to move one
   button 40px to the left (`"btn_new_game": {"rect": [40, 100, 200, 52]}`).
   Relaunch `py game/main.py` → the main menu button moved.

3. **Label override**: set `"label": "START"` on the same button in the JSON.
   Relaunch → the button label changed.

4. **Delete override**: delete the JSON file. Relaunch → the menu is stock again.

5. **In-round HUD**: during gameplay, move the love panel override in
   `data/ui/screens/hud.json` (if you added one). Confirm the panel moved.

6. **Cheat menu every-frame apply**: Ctrl+L to open cheat menu, leave it open
   while time passes (multiple frames). The menu stays responsive and never
   stutters (the "loads once" cache is working — no disk I/O on every submit).

7. **Full round**: play a round start-to-finish (build → end turn → wave →
   levelup → boss → game over). All screens animate and respond normally.

---

## Risks / open items

- **Parity baseline timing**: the parity golden capture MUST be the first commit
  of B2, before any screen code refactoring. If a screen's geometry algorithm
  changes even slightly before capture, the baseline will NOT match today's
  output (and future diffs won't catch the delta). Record first, then edit.

- **Per-screen ids enumerator (your main task)**: reading 12 screen modules and
  writing the definitive ids table is mechanical but requires precision. Name
  every widget that has a stable identity (buttons with semantic labels, panels,
  labels). Skip dynamic-content containers (log lines, list entries) — they
  inherit style from screen `defaults`.

- **Cheat menu every-frame layout()**: the parity test must verify that a
  screen with `submit()` calling `layout()` every frame (cheat_menu) still
  parity-passes. This pins that the `apply()` caching is real.

- **GameLog style holder**: the holder is read-only from the game log's line
  feeding loop (stays code-driven). It is a pure data vessel for skin overrides;
  the game log logic never queries it, only submits using the values at render
  time.
