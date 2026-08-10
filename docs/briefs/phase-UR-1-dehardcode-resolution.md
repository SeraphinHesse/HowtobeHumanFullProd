# Phase UR-1 — De-hardcode the resolution

Source plan: `planning/UiResolutionPLAN.md` §"Phase UR-1" (lines 104–124).

**Standing constraints for this phase (all three are hard):**
1. **No visual change.** `display.json` still says 1280×720, so every pixel the
   game and the editor draw must be identical before and after.
2. **`data/display.json` is NOT flipped here.** That is UR-2. Touching it in
   this phase makes the "pixel-identical" gate unverifiable.
3. **Bare-minimum tests.** Adapt the existing references in
   `tools/tests/test_editor_viewport.py` to assert against the loaded value.
   Add no new test classes, no new coverage.

---

## 1. Behavioral spec (with citations)

### 1a. The one true source

`data/display.json` holds `window_w: 1280`, `window_h: 720` (verified,
`data/display.json:5-6`). The game reads it through the schema-validating
loader and never hardcodes it:

- `game/main.py:222-225` —
  `display = data_io.load_validated(data_dir / "display.json", data_dir / "schemas" / "display.schema.json")`
  then `view_w, view_h = display["window_w"], display["window_h"]`. **Verified.**
- `game/main.py:144` — `pygame.display.set_mode((view_w, view_h), flags)`.
  **Verified.** The game half needs no code change.

### 1b. Every literal `1280`/`720` that means "the screen"

Swept across `editor/**`, `game/**`, `tools/**` (grep for `1280` and `\b720\b`;
**measured**). Full classification — a claim of "clean" is as load-bearing here
as a claim of "must change":

| `file:line` | Literal | Means "the screen"? | UR-1 action |
|---|---|---|---|
| `editor/panels/viewport.py:110` | `SCREEN_W, SCREEN_H = 1280, 720   # data/display.json's canonical resolution` | **YES — the only functional hardcode in the repo** | **Derive from `display.json`** (§2) |
| `editor/panels/viewport.py:11` | module docstring, "a fixed 1280x720 logical canvas" | prose | Reword to name `display.json`, not a size |
| `editor/panels/viewport.py:25` | docstring, ">=60fps at 1280x720" | prose — a **historical measurement** | **Leave.** It records a measurement taken at that size; rewriting it falsifies the record |
| `editor/panels/viewport.py:109` | section comment, "fixed 1280x720 logical canvas" | prose | Reword |
| `editor/panels/viewport.py:115` | `NUDGE_STEP = 1  # arrow-key nudge, in LOGICAL (1280x720) pixels` | prose (the value `1` is resolution-independent) | Reword comment to "LOGICAL (`display.json`) pixels". **The value stays `1`** — UR-3 owns revisiting it |
| `editor/panels/viewport.py:237` | comment, "all rect math in LOGICAL (1280x720)" | prose | Reword |
| `editor/panels/viewport.py:437` | `set_screen_mode` docstring, "1280x720 logical canvas" | prose | Reword |
| `editor/panels/viewport.py:538` | `_screen_scale_offset` docstring, "fitting the 1280x720 logical canvas" | prose | Reword |
| `editor/main.py:88` | `self.resize(1280, 720)` | **NO** — the Qt main-window size in desktop pixels | **Leave untouched** |
| `editor/panels/sheet_picker.py:40` | `self.resize(720, 520)` | **NO** — a Qt dialog size | **Leave untouched** |
| `game/debug/report.py:235` | `_W, _H = 720, 260` | **NO** — a debug-report image canvas | **Leave untouched** |
| `game/ui/main_menu.py:72` | comment: "…in the shipped 1280x720 logical surface (data/display.json)" | prose, and a **historical bug narrative** (why `_GAP` is 8) | **Leave.** Rewriting it destroys the reasoning. UR-2 owns `main_menu.py`'s constants |
| `tools/export_ui_layouts.py:202` | docstring: `never hardcoded (brief §1: "never hardcode 1280x720")` | prose, self-describing | Leave |
| `tools/export_ui_layouts.py:487` | `screen.open(1, "win")  # R3 contract: open(1, "win") + layout(1280, 720)` | prose, and **stale** — the real call is `layout(view_w, view_h)` | Optional one-word reword to `layout(view_w, view_h)`. No behavior |
| `tools/render_demo.py:45` | `VIEW_W, VIEW_H = 1280, 720` | **borderline** — a standalone dev PNG-dump tool (`tools/render_demo.py:1-14`), not the game surface, no `data/` read anywhere in the file | **Leave untouched, and say so in the report.** It renders an offscreen demo image whose size is arbitrary; wiring it to `display.json` would shrink the demo PNG in UR-2 for no benefit. If the reviewer disagrees, it is a one-line follow-up |

**Conclusion: exactly one functional hardcode exists** —
`editor/panels/viewport.py:110`. Everything else in the sweep is prose or a
non-screen size. **Measured.**

### 1c. Which loader `viewport.py` must use — do NOT add a second read path

Use the loader already imported at the top of the file:

- `editor/panels/viewport.py:39` — `from engine import data_io, tilemap`
  (**verified**; `data_io` is already in scope, no new import needed).
- The exact call shape to copy is `tools/export_ui_layouts.py:200-205`
  (`_logical_resolution(data_root)`):
  `data_io.load_validated(data_root / "display.json", data_root / "schemas" / "display.schema.json")`
  → `return display["window_w"], display["window_h"]`. **Verified.**
- `game/main.py:222-225` is the identical shape. Both go through
  `engine.data_io.load_validated`. There is no third path and none may be
  created. In particular: **do not** `import json` and read the file directly,
  and **do not** import `tools.export_ui_layouts` from `editor/` (a tool is not
  a library for the editor).
- The repo-root anchor already exists: `editor/panels/viewport.py:59` —
  `REPO = Path(__file__).resolve().parents[2]`; the panel's own data root is
  `REPO / "data"` (`editor/panels/viewport.py:148`). **Verified.**

### 1d. Is `tools/export_ui_layouts.py` already clean? — CONFIRMED

**Confirmed, with citation.** `tools/export_ui_layouts.py:200-205` defines
`_logical_resolution(data_root)` which reads `display.json` through
`data_io.load_validated`; the resulting `view_w, view_h` are threaded into
every `_build_*` screen constructor (e.g. `_build_boss_cutscene(view_w, view_h,
data_root)` at `tools/export_ui_layouts.py:481-489`, which constructs
`BossCutscene(view_w, view_h, ...)`). The file's only `1280`/`720` occurrences
are the two prose strings at lines 202 and 487. **Do not change its behavior.**
Its output `data/ui/screen_defaults.json` regenerates for free in UR-2.

### 1e. The existing test's references

`tools/tests/test_editor_viewport.py` imports the constants and uses them:

- `tools/tests/test_editor_viewport.py:32` —
  `from editor.panels.viewport import SCREEN_H, SCREEN_W, ViewportPanel, surface_to_qimage`
- `:570`, `:694`, `:836` — `panel.resize(SCREEN_W, SCREEN_H)` inside three
  `make_viewport()` helpers, with the comment "scale 1.0, offset 0 — trivial
  math". These **already** go through the constant and stay correct
  automatically. **Verified.**
- `:552` — class docstring, "fixed 1280x720 canvas". Prose; reword.
- `:1256` — `window.resize(1280, 720)` — a **Qt** `MainWindow` resize in a
  panel-stack-index test, not the logical canvas. **Leave untouched.**
- The `[0, 0, 1280, 720]` backdrop rects in `FIXTURE_DEFAULTS_VIEWS`
  (`:92`, `:102`, `:112`, `:120`, `:130`) are **hand-authored fixture data**
  standing in for `screen_defaults.json` (see the fixture's own note at
  `:40-44`). They are inputs, not assertions about the screen size, and the
  tests around them assert rect arithmetic, not framing. **Leave them.** Do not
  rewrite them to `[0, 0, SCREEN_W, SCREEN_H]` — pinning the fixture is the
  documented rule (`editor/CLAUDE.md:294-305`).
- `:49-53`, `:67-72` use `640`/`360` as **widget rect coordinates** in the same
  fixture (`btn_new_game` at `[640, 360, 120, 40]`). They are a coincidence of
  numbers, **not** a resolution. **Leave them.** Likewise `:647` / `:658`
  (`[670, ...]`, `[639, ...]`) are drag-arithmetic expectations.

**Required test work is therefore small:** add one assertion that
`(SCREEN_W, SCREEN_H)` equals what `data/display.json` says (so the derivation
is actually covered), and reword the `:552` docstring. Nothing else must move
for the suite to stay green.

---

## 2. Architecture plan

### The shape

Keep the module-level names `SCREEN_W` / `SCREEN_H` exactly as they are — they
are imported by name (`test_editor_viewport.py:32`) and used at five call sites
inside the module. Replace only the right-hand side.

Add one small helper next to them in `editor/panels/viewport.py`, then bind the
constants from it at import time:

```
def logical_screen_size(data_dir=None):
    """The logical UI resolution from data/display.json (the ONE source)."""
    root = Path(data_dir) if data_dir is not None else REPO / "data"
    display = data_io.load_validated(
        root / "display.json", root / "schemas" / "display.schema.json")
    return display["window_w"], display["window_h"]


SCREEN_W, SCREEN_H = logical_screen_size()
```

(Exact naming/wording is the implementer's; the *shape* — one helper taking an
optional `data_dir`, plus module constants bound from it — is the contract, and
UR-3 depends on the helper existing.)

### Why module-level and not per-instance

`ViewportPanel` already takes an injectable `data_dir`
(`editor/panels/viewport.py:143-148`), so a per-instance
`self._screen_w/_screen_h` is the theoretically purer move. **UR-1 deliberately
does not do it**, because:
- it would change the public import surface the test uses (`:32`) and force
  edits at all five consumer sites, growing a "no visual change" phase into a
  refactor;
- the consumers at `:1730`, `:1755` and `_screen_scale_offset` are UR-3's
  working area, and UR-3 is where per-instance resolution (if wanted) belongs.

The `data_dir=` parameter on the helper is added **now** precisely so UR-3 can
switch to per-instance without re-touching the loader.

### Import-time I/O — the one real risk, decide it explicitly

Binding at import means `editor/panels/viewport.py` performs a validated JSON
read when it is first imported. Consequences to accept knowingly:

- **No numeric fallback.** Do **not** write `except: SCREEN_W, SCREEN_H = 1280, 720`
  — that is precisely the second source of truth this phase deletes. A missing
  or invalid `display.json` should raise, matching `game/main.py:222` which also
  has no fallback. **This is a new failure mode** (previously the editor could
  import with a broken `display.json`); it is reported, not hidden.
- **Tests using `TempDataCase` still see the repo value**, because the constants
  bind from `REPO / "data"` at import. In UR-1 that is a distinction without a
  difference (the temp copy is byte-identical). Flagged as an open question for
  UR-3.
- `viewport.py` is imported by `editor/main.py`'s panel wiring and by
  `TestPurity`'s import list — both already require a working `data/`.

### Every consumer of `SCREEN_W` / `SCREEN_H` (complete; **measured**, repo-wide grep)

| `file:line` | Use | Changes in UR-1? |
|---|---|---|
| `editor/panels/viewport.py:110` | the definition | **yes — the whole change** |
| `editor/panels/viewport.py:541` | `scale = min(w / SCREEN_W, h / SCREEN_H)` | no (reads the name) |
| `editor/panels/viewport.py:542` | `scaled_w, scaled_h = SCREEN_W * scale, SCREEN_H * scale` | no |
| `editor/panels/viewport.py:1730-1731` | E-37 placeholder text centring | no |
| `editor/panels/viewport.py:1755` | `_to_screen_rect((0, 0, SCREEN_W, SCREEN_H), ...)` — screen-mode background dest | no |
| `tools/tests/test_editor_viewport.py:32` | import | no |
| `tools/tests/test_editor_viewport.py:570, 694, 836` | `panel.resize(SCREEN_W, SCREEN_H)` | no |

There are **no other consumers anywhere in the repo** — nothing in `game/**`,
nothing in `engine/**`, no other editor panel. Because all five in-module uses
already read the names rather than literals, rebinding the names is sufficient
and the render output is unchanged by construction. **Inferred from the call
sites; the gate in §4 is what verifies it.**

### `NUDGE_STEP`

`editor/panels/viewport.py:115`, value `1`, is already resolution-independent
(one logical pixel). **The value does not change in UR-1** — only its comment,
to stop naming a literal size. UR-3 explicitly owns reconsidering it
(`planning/UiResolutionPLAN.md:173-174`).

---

## 3. File scope + shared-file contract

### In scope

| File | Scope |
|---|---|
| `editor/panels/viewport.py` | **Only** line 110's binding (+ the new helper immediately above it), and the prose at lines 11, 109, 115, 237, 437, 538. Nothing else. |
| `editor/panels/CLAUDE.md` | The screen-mode bullet at line ~777 only (see below). |
| `tools/tests/test_editor_viewport.py` | The `:552` docstring, plus one new assertion tying `(SCREEN_W, SCREEN_H)` to `data/display.json`. |
| `tools/export_ui_layouts.py` | **Audit only.** At most the stale prose at `:487`. Zero behavior change. |

### Explicitly out of scope

`data/display.json` (UR-2) · `data/ui/screens/*.json` (UR-2) ·
`data/ui/screen_defaults.json` (generated; UR-2) · any `game/ui/*.py` constant
(UR-2) · `editor/main.py:88` · `tools/render_demo.py` ·
`game/ui/main_menu.py:72` · the `[0,0,1280,720]` fixture rects.

### Shared-file contract — `editor/panels/viewport.py` (also UR-3's file)

UR-3 will edit **the scale-to-fit and letterbox math** — `_screen_scale_offset`
(`:537-543`), the E-37 centring (`:1728-1733`), and possibly `NUDGE_STEP`'s
*value* (`:115`).

- **UR-1 owns:** the region from the `# -- screen mode (B4, R3)` section
  comment (`:109`) through the `SCREEN_W, SCREEN_H` binding (`:110`), plus the
  new helper inserted immediately above that section comment (i.e. after
  `LOGO_PATH` at `:107`). Insertion point: **between `editor/panels/viewport.py:107`
  and `:109`.**
- **UR-1 must leave alone:** every line inside `_screen_scale_offset`,
  `_submit_screen_items` and `_submit_screen_background`. It may reword their
  docstrings/comments (`:437`, `:538`) but must not touch a single expression.
  If a UR-1 change appears to require editing that arithmetic, the change is
  wrong — stop and report.
- **UR-1 must not change** `NUDGE_STEP`'s value, only its comment. UR-3 owns the
  value.
- **UR-1 must not change** the module's import block (`:36-58`) — `data_io` is
  already there (`:39`).

### Shared-file contract — `editor/panels/CLAUDE.md` (also UR-3's file)

- **UR-1 owns exactly one sentence:** the `set_screen_mode` bullet at
  `editor/panels/CLAUDE.md:777` — "a FIXED 1280×720 logical canvas
  (`data/display.json`'s canonical resolution)" becomes "a FIXED canvas at
  `data/display.json`'s resolution, read from that file (no literal in
  `viewport.py`)". Nothing else in that bullet or its sub-bullets.
- **UR-1 must leave alone:** the performance notes at `:21` and `:1006`
  ("measured live (1280x720, …)"). Those are dated measurements; changing the
  number in them would be a lie. UR-3 owns anything describing *preview
  behaviour* at the new canvas.

---

## 4. Exit gate + Quick Test

### The gate

The change is a no-op by design, so the gate is "nothing moved":

1. **Targeted test (this is the one to run while working):**
   ```
   py -m pytest tools/tests/test_editor_viewport.py -x -q
   ```
   Not the full suite. Not `--affected`. Per the router's Test Suite Policy this
   file is the phase's blast radius; the full gate is the orchestrator's single
   run after the phase lands.
2. **Data + boot:** `py tools/smoke.py` (validates `data/`, 5-frame headless
   boot). Must pass unchanged.
3. **The derivation is real, not cosmetic:** demonstrate that the constants
   track the file rather than coincidentally equalling 1280×720. Acceptable
   evidence: the new assertion in the test file comparing `(SCREEN_W, SCREEN_H)`
   against a fresh `data_io.load_validated` read of `data/display.json`. Do
   **not** commit a temporarily-edited `display.json`.
4. **Zero literals left:** `grep -rn "1280" editor/panels/viewport.py` returns
   only the two deliberately-preserved historical prose lines (`:25`
   performance note; any line this brief marks "Leave"). Report the exact
   surviving lines.

### Quick Test (in-game / in-editor, pixel-identical)

1. `py editor/main.py`. In the selector tree, open **ui ▸ Screens ▸ main_menu**.
   The screen preview must render the canvas letterboxed exactly as before:
   same aspect, same scale-to-fit margins, same widget positions. Select a
   widget and press an arrow key once — it must move by exactly **1** logical
   pixel (`NUDGE_STEP` unchanged).
2. Resize the editor window. The canvas must keep the same letterbox behaviour
   (the whole canvas visible, centred) — `_screen_scale_offset` was not touched.
3. `py game/main.py`. Main menu renders identically; the window is still
   1280×720. (The game path is untouched by this phase, so this is a
   regression check on `smoke.py`'s territory, not a new behaviour.)
4. **Pass criterion:** a before/after screenshot of the editor's `main_menu`
   preview is pixel-identical. Any difference at all means the derivation
   produced a different number or a consumer was edited — both are failures, not
   improvements.

### Report requirements

State, tagged **measured** / **verified** / **inferred**:
- the exact `file:line` of every literal left behind and why;
- confirmation that `tools/export_ui_layouts.py` was audited and **not**
  behaviorally changed;
- the new import-time failure mode (broken `display.json` → editor import
  raises), so the orchestrator can decide whether it is acceptable.

### Open questions for the orchestrator

1. **`tools/render_demo.py:45`** — leave at a fixed 1280×720 (this brief's
   recommendation) or wire to `display.json` and let the demo PNG shrink in
   UR-2? Not blocking.
2. **Import-time raise with no fallback** — confirmed as intended? The
   alternative (lazy/`lru_cache` resolution on first use) defers the failure to
   panel construction but adds machinery for a file that must exist anyway.
3. **Per-instance resolution** (`data_dir`-aware `SCREEN_W`) is deferred to
   UR-3 — confirm UR-3's brief inherits it rather than it being dropped.
