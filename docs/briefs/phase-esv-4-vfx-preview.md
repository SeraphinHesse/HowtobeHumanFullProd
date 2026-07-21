# Phase ESV-4 — Procedural preview + control levers (Track B · editor)

Source plan: `planning/EntitySceneVfxPLAN.md` §ESV-4 (`:220-235`, **verified**).
Engine layer: **ESV-3a has landed and merged** (`fd55cf3` / `6640cf1`) — this
phase consumes `engine/vfx/` as-is and adds **nothing** to it.

**Open with the `/add-editor-feature` skill** — this is a new panel plus its
`main.py` wiring, exactly the pattern that skill encodes. Do not hand-roll it.

**Landing condition:** the game is untouched. `data/balancing/vfx.json` is
written only by a designer clicking Save, through the existing balancing writer.
A run of `py game/main.py` with no lever moved must look identical.

---

## 1. Behavioral spec

### 1.1 What already exists (do not rebuild it)

- `engine/vfx/` is the emitter layer: `emitters.py`'s pure
  `emit_burst`/`emit_shards`/`emit_muzzle`/`emit_slash`/`emit_gold` all take an
  **injected `rng` as their first argument** (`engine/vfx/emitters.py:20`,
  `:33`, docstring rule at `:1-16`, **verified**), and `VfxSystem(params, *,
  rng)` owns the lists, `update(dt)`, `submit_hud(renderer, cs)`,
  `submit_splatters(renderer, cs)`, `submit_gold_highlights(renderer)`
  (`engine/vfx/system.py:29-138`, **verified**). This injectability is *why* D5
  required engine-side params — the editor can drive the real emitter without
  importing `game/`.
- The params are frozen dataclasses with **no defaults**: `BurstParams`,
  `ShardBurstParams`, `MuzzleParams`, `SlashParams`, `GoldParams`,
  `SplatterParams`, bundled by `VfxParams` (`engine/vfx/params.py:18-136`,
  **verified**). `VfxParams` deliberately excludes spark, because spark preset
  keys (`place`/`level1`/`level2`/`tier`) are game vocabulary — the caller
  resolves a preset key to a `BurstParams` and passes it to `emit_burst`
  explicitly (`engine/vfx/params.py:126-131`, `system.py:39-44`, **verified**).
- `data/balancing/vfx.json` ships `{"procedural": {death_burst, floaters,
  gold_highlight, muzzle, slash, spark, splatter}}` (**verified** by dumping the
  file). `vfx` is a real balancing domain now, so **the `vfx` node in the
  selector already opens the generic recursive balancing form with every one of
  those keys as a widget, for free** (`editor/domains.py` derives domains as
  slots categories ∩ categories with a balancing file — `editor/panels/CLAUDE.md`
  "The domain list is DERIVED, never hardcoded").

### 1.2 The relationship to the generic balancing form — read this before designing

**The obvious wrong turn is to rebuild the generic form.** Do not. Every numeric
key under `procedural` is already editable, already schema-ranged (ED-30),
already staged with a dirty dot, already saved by the ONE
`write_validated` call in `BalancingPanel.save_changes`
(`editor/panels/balancing.py:543-553`, **verified**).

ESV-4 adds a **live-preview layer on top of that domain**, carrying only what
the generic form structurally cannot do:

1. **A picture.** The generic form shows numbers; a designer tuning a muzzle
   spray needs to *see* it.
2. **Colour pickers for the named-stop ramps.** `spark.ramp`, `muzzle.ramp`,
   `slash.colors`, `death_burst.colors` are `{stop_0, stop_1, stop_2}` objects,
   each a 3-integer array. The generic form renders each stop as a
   `CollapsibleSection` containing **three separate spinboxes** (arrays of
   scalars → one row per index, `editor/panels/balancing.py:328-353` +
   `editor/panels/CLAUDE.md` Phase-4 section, **verified**) — correct, but
   unreadable as colour. A `QColorDialog` swatch button is the genuine value-add.
3. **A curated lever strip for the effect currently being previewed** — the two
   or three numbers a designer reaches for while watching (`count`, `life`,
   `gravity`) — so tuning does not mean scrolling a 7-section tree while the
   preview plays.

**Everything else stays in the generic form and is not duplicated.** A lever in
the preview panel and its twin row in the generic form must show the same value
at all times — §2.3 makes that structural rather than a promise.

### 1.3 Effect families the preview offers

One combo box, one entry per family, driven by the **keys present under
`procedural` in the loaded doc** — not a hardcoded literal list. ESV-3b is
adding siblings (`beam`, `crater`, `lightning`, `announce`) inside `procedural`
right now; a data-driven list means those appear with no ESV-4 edit, and a
family with no emitter binding shows a "no preview for this effect yet" message
rather than crashing (the E-37 graceful-degrade convention). Bindings this phase
ships:

| Family | Preview action (per emit) | Levers |
|---|---|---|
| `spark` | `emit_burst(preset_params, wx, wy)` for the preset chosen in a second combo (`place`/`level1`/`level2`/`tier`, read from `spark.presets` keys) | preset `count`, preset `life`, `gravity`, ramp ×3 colours |
| `death_burst` | `VfxSystem.emit_shards(wx, wy)` | `count`, `life`, `gravity`, colours ×3 |
| `muzzle` | `VfxSystem.emit_muzzle(wx, wy, strong=<checkbox>)` | `count`/`count_strong`, `life`/`life_strong`, `smoke_chance`, ramp ×3 |
| `slash` | `VfxSystem.emit_slash(wx, wy, large=<checkbox>)` | `life`, `lines_min`/`lines_max`, colours ×3 |
| `gold_highlight` | `VfxSystem.emit_gold(col, row)` | `life`, `fade_in`, `hold`, fill + border colour |
| `splatter` | `VfxSystem.add_splatters([(wx, wy)] * n)` | `alpha`, `radius_px`, `jitter`, colour |
| `floaters` | **no preview** — colour/lifetime pairs read straight off the dict at their `game/ui/effects.py` call sites, no engine emitter exists (`engine/vfx/params.py:8-13`, **verified**). Show the degrade message. |

The lever set per family is **derived from the family's own schema subtree**
(the keys the executor picks are listed above as intent), never hardcoded types:
a numeric key → the same `_NoWheel*` spin widget class the balancing panel uses
(imported from `editor.panels.balancing` — their home, "never copied, never
moved", `editor/CLAUDE.md` agent-dispatch section, **verified**); a `$defs/color`
key → the colour button of §2.4.

### 1.4 Preview trigger + loop

- **Loop by default.** A `Loop` checkbox (on) re-emits the selected family every
  `N` seconds — one repeat interval spin, default ~1.0 s — so a designer can
  watch a change take without clicking. Off ⇒ the preview only emits on demand.
- **An explicit `Emit` button** fires one burst immediately, regardless of loop
  state. This is the button the tests drive; a test must never depend on a timer
  firing.
- **Any lever edit re-emits immediately** and clears the currently-live
  particles first, so what is on screen is always the current params — a
  half-old, half-new particle cloud is exactly the confusion the panel exists to
  remove.
- The anchor point is the **centre tile** of the preview's own small grid, the
  same convention as the entity preview
  (`editor/panels/viewport.py:772-777`, `:804-814`, **verified**).
- Frames advance on the editor's existing 16 ms `QTimer`
  (`editor/main.py:306-308`, `_tick` at `:794-816`, **verified**) — never a busy
  loop, never a second timer if the shared one can be used.

### 1.5 Saving

The preview panel has **no Save button of its own**. Staged edits land in the
`BalancingPanel`'s doc and are written by its existing "Save Balancing Changes"
button — one staging store, one dirty-dot set, one `write_validated`, one
version-history session. §2.3 is the mechanism.

---

## 2. Architecture plan

### 2.1 A dedicated panel with its own engine `Renderer` — and why that is ED-22-clean

**This is the most likely violation in this phase, so it is stated first: the
preview renders through the engine `Renderer` into an offscreen `pygame.Surface`
which is converted once by `surface_to_qimage` and blitted in `paintEvent`.
QPainter blits the converted frame and draws nothing else. QPainter never draws
a particle, a line, a swatch of game content, or a fake "close enough" circle.**

`editor/panels/vfx_preview.py` constructs its own
`load_coordinate_system(...)` + `AssetStore` + `Renderer` and its own offscreen
surface, structurally copying `ViewportPanel.__init__`/`_build_store`/
`render_frame` (`editor/panels/viewport.py:93-99`, `:170-177`, `:792-818`,
**verified**). A second *`Renderer` instance* is not a second *render path*: the
ED-22 rule bans a second Qt-side renderer of game content
(`editor/panels/CLAUDE.md` states this explicitly when sanctioning
`panels/sheet_preview.py`, **verified**). Everything drawn here goes out as
`HudRect`/`HudLines`/`submit_overlay_polys`/`submit_overlay_lines` **emitted by
`VfxSystem` itself** (`engine/vfx/system.py:95-138`, **verified**) — the same
primitives the game submits, from the same code.

**Why a new panel rather than a fourth mode on `ViewportPanel`:** ESV-2 is
editing `editor/panels/viewport.py` right now (anchor handles + hit-test +
drag, plan `:184-195`). A `set_vfx_mode` branch in `render_frame` and a fourth
`in_*_mode()` would collide with that diff for no architectural gain. **Do not
touch `editor/panels/viewport.py` in this phase.**

`VfxSystem.submit_hud` and `submit_splatters` take a coordinate system and read
`cs.camera.zoom` / `cs.geometry.tile_w` (`system.py:98`, `:118`, **verified**),
so the panel's `CoordinateSystem` must be a real one, parked and clamped like
the entity preview's — not a stub.

### 2.2 Preview state

All of it lives on the panel instance, none of it in `data/`
(pillar 1: "no editor-only hidden state" means nothing persisted; transient
widget state is fine):

- `self._family` / `self._preset` / `self._strong` / `self._large` — the combos'
  current selection.
- `self._rng` — a `random.Random(seed)` with a **fixed default seed**, reseeded
  on every emit-batch. This is what makes the preview reproducible and the tests
  deterministic; the game passes the stdlib `random` module instead
  (`engine/vfx/system.py:22-27`, **verified**). The seed is injectable on the
  constructor for tests.
- `self._system` — the live `VfxSystem`, **rebuilt whenever params change**
  (params are frozen dataclasses; there is no in-place mutation path).
- `self._clock` — wall-clock accumulator for `update(dt)` and the loop interval.

### 2.3 Read/write path — one staging store, no second writer

The preview panel **does not load, stage or write `vfx.json` itself.** It holds
a reference to the live `BalancingPanel` and goes through two small public
methods added to it:

- `staged_value(path)` — the current staged value at a `/`-joined path (the
  existing private `_value_at` at `editor/panels/balancing.py:477-482` is
  already exactly this, **verified**).
- `stage_value(path, value)` — stage into `self._doc`, refresh the dirty dot,
  **and push the new value into the generic form's own widget** via the existing
  `_set_widget_value` (`:512-522`, **verified**), so the lever and the generic
  row can never disagree. `_commit` (`:483-491`) + `_refresh_dirty` (`:492-511`)
  already do the first two halves; the new method composes them.
- Plus one signal for the other direction: the balancing panel emits when a
  value is staged from the generic form, so the preview re-reads its levers and
  re-emits. Reuse whatever the executor finds cheapest — a Qt signal on
  `BalancingPanel`, connected in `main.py`, is the house pattern.

Consequences, all deliberate: Save is the balancing panel's existing button; the
write is its existing `write_validated` call (`:543-553`); version history
records preview-made edits like any other; and there is exactly one dirty state
in the app.

**Do not change `BalancingPanel.__init__`'s signature.** Adding methods and a
signal is additive; a constructor change would hit the integration trap in §3.

### 2.4 Named-stop colours ↔ colour picker

**The named-stop shape is load-bearing and must not be undone.** Ramps ship as
`{"stop_0": [r,g,b], "stop_1": …, "stop_2": …}` rather than an array of arrays
because `balancing.py::_build_array`'s non-object branch reaches `_make_widget`
(`editor/panels/balancing.py:328-353`, `:428-466`, **verified**), whose `else`
raises `ValueError(... no widget for schema ...)` for a nested array — which
would crash the balancing form for the **entire `vfx` domain**. `game/ui/
effects.py::_ramp` (`:101-108`, **verified**) is the reference converter and
documents this reason in its own docstring.

The mapping:

- **Read** `procedural.<family>.ramp` (or `.colors`) → three
  `QColorDialog`-backed swatch buttons, one per `stop_<i>`, in stop order.
- **Write** a picked `QColor` back as `[r, g, b]` at the path
  `<family>/ramp/stop_<i>` through `stage_value` — the stop object is never
  replaced wholesale, never reordered, never converted to a list.
- **Engine conversion** — `(tuple(stop_0), tuple(stop_1), tuple(stop_2))` — is
  the editor's own local mirror of `_ramp`, in the pure helper of §2.5.

Flat single colours (`splatter.color`, `gold_highlight.fill_color`/
`border_color`, `muzzle.smoke_color`, the `floaters.*_color` keys) are already
bare 3-int arrays; the same swatch button handles them with no stop indirection.

### 2.5 The params adapter, and the layering boundary question it raises

`engine/vfx` dataclasses need building from the staged dict. `game/ui/
effects.py::_params_from_balance` (`:111-176`, **verified**) does exactly this —
and **the editor may not import it** (`editor/` never imports `game/`,
`editor/CLAUDE.md` "File scope you may edit"). So this phase adds a pure,
Qt-free `editor/vfx_params.py` holding the editor's own `_color`/`_ramp`/
`params_from_balance` mirror.

**This is a deliberate, sanctioned drift, and it has precedent**:
`editor/panels/_screen_primitives.py` re-implements `game/ui`'s unskinned widget
look for the same layering reason, "an accepted drift kept aligned by eye + the
B2 parity pin, not by sharing code" (`editor/CLAUDE.md` screen-mode section,
**verified**).

**Boundary question for the orchestrator, flagged not decided:** the natural
"fix" is to move the adapter into `engine/vfx/` so both packages share it. **Do
not do this in ESV-4.** It would give `engine/vfx/` knowledge of JSON key names,
which ESV-3a explicitly forbids (D5; `engine/vfx/params.py:1-14` and
`engine/CLAUDE.md`'s vfx section both name a convenience loader as *the* top
risk, and ESV-3a's test 3 is a source-text scan that would go red). If the
duplication proves painful later, that is a plan-level decision, not an executor
one. **Report the duplication in your final report.**

Note the panel only needs the families it previews — build the dataclasses
lazily per family rather than a whole `VfxParams` bundle when only one field
changed, if that reads cleaner.

### 2.6 Determinism and what the tests assert

Tests assert **the params handed to the emitter, never pixels.** The panel must
therefore expose the emit call in an inspectable way — the executor's choice of
seam, but the simplest is that the panel builds the dataclass and calls a single
private `_emit()`, so a test can monkeypatch `engine.vfx.system.VfxSystem` (or
the panel's `_system`) with a spy and read the recorded arguments. Pixel
assertions are forbidden: they would pin the renderer, not this phase.

---

## 3. File scope + shared-file contract

### May create

| Path | Contents |
|---|---|
| `editor/panels/vfx_preview.py` | `VfxPreviewPanel` — the engine-`Renderer` preview surface, family/preset combos, lever strip, colour buttons, Emit/Loop controls |
| `editor/vfx_params.py` | pure (stdlib only + `engine.vfx`): `_color` / `_ramp` / `params_from_balance` — Qt-free, pygame-free |
| `tools/tests/test_vfx_preview.py` | §4's tests (name at executor's discretion) |

### May modify — exact insertion points

`editor/main.py` (**shared with ESV-2 — take these named anchors and do not
reformat surrounding code**):

| Anchor | Edit |
|---|---|
| after `self.screen_session = UIScreenSession(...)` — currently `:101`, immediately before `self._screen_defaults = {}` at `:102` | one line: `self.vfx_preview = VfxPreviewPanel(data_dir=data_dir)` |
| after `self.viewport.widget_selected.connect(self.screen_details.select_widget)` — currently `:156`, before the `# ED-24: THE global undo stack` comment at `:158` | a NEW comment-fenced block `# ESV-4: vfx preview <-> balancing staging wiring` — the preview↔balancing signal hookups and nothing else |
| after `self.right_stack.addWidget(self.screen_details)  # index 2` — currently `:283` | one line: `self.right_stack.addWidget(self.vfx_preview)  # index 3: vfx preview (ESV-4)` |
| inside `_on_node_selected` — currently `:312-317` | ONE added branch: `category_key == "vfx"` → `_enter_vfx_mode()`, else `_leave_vfx_mode()`. Keep the existing `_leave_map_mode()`/`_leave_screen_mode()` calls exactly as they are |
| a NEW section appended after `_load_screen_defaults` (ends ~`:400`), before the composite-selection helpers that follow | `_enter_vfx_mode` / `_leave_vfx_mode`, structurally mirroring `_enter_screen_mode`/`_leave_screen_mode` (`:373-392`) |
| `_tick` — currently `:794-816` | at most ONE added line driving `self.vfx_preview.render_frame()` when in vfx mode. Do not touch the fps block |

**All line numbers are as of `b960d12` — re-locate before editing; ESV-2 may
have shifted them.** Anchor on the quoted code, not on the number.

`editor/panels/balancing.py` — additive only: the `staged_value` /
`stage_value` public methods of §2.3 and one signal. **No change to
`BalancingPanel.__init__`'s signature, no change to any existing method's
signature, no reformatting of `_build_object`/`_build_array`/`_make_widget`.**

`tools/tests/test_editor_viewport.py` — the `TestPurity` import tuple (currently
`:731-749`, **verified**): add `editor.vfx_params` and
`editor.panels.vfx_preview`. **ESV-2 adds entries to this same tuple.** Add them
in alphabetical position within their existing group (`editor.*` names with the
other top-level modules; `editor.panels.vfx_preview` with the other
`editor.panels.*` names), one name per addition, nothing else on those lines, so
the merge conflict is a trivial two-line union.

`conftest.py` (repo root, not `tools/tests/`) — one `TIERS` entry
`"test_vfx_preview": "editor",` in the `# --- editor:` block (currently
`:50-59`, **verified**), **alphabetically ordered** among its neighbours. Same
minimal-diff rule: ESV-2 adds an entry to this same block.

`editor/panels/CLAUDE.md` and/or `editor/CLAUDE.md` — a section describing the
new panel, per root CLAUDE.md step 2.3. Panel architecture → the panels doc;
anything cross-cutting (the second `Renderer` and its ED-22 argument) → the
router. **Both files are ESV-2's likely doc target too — append a new section at
the end of the relevant Phase list; do not edit existing sections.**

### Must NOT touch

- **`editor/panels/viewport.py` — ESV-2 owns it right now.** Not one line.
- **`data/balancing/vfx.json` and `data/schemas/vfx.schema.json` — ESV-3b is
  editing both concurrently.** You **write values** through the balancing
  writer at runtime; you do not restructure either file, do not add or rename a
  key, do not touch the schema. **If your panel appears to need a schema change,
  STOP and report it to the orchestrator — do not race ESV-3b.** In particular:
  do not "improve" the named-stop ramps into arrays (§2.4 — it crashes the whole
  domain's form).
- Anything under `game/` or `engine/`. The engine layer is finished and merged.
- `planning/EntitySceneVfxPLAN.md` and root `PLAN.md` — the coordinator updates
  the build-order table once at the end of the run; `PLAN.md` is a generated
  mirror.
- Live `data/` at test time. `TempDataCase`; never assert against shipped
  content (`editor/CLAUDE.md` "Testing the editor — two rules").

### The integration trap

Stage 1 lost a phase to this: a constructor signature changed, every visible
call site was updated, and a *concurrent* phase's new test module constructed
the same class and broke. **If you change any constructor signature or public
attribute path — `BalancingPanel`, `MainWindow`, anything — grep ALL of
`tools/tests/` for construction sites before you finish, and state the change
loudly in your final report.** The design above is deliberately additive
specifically so this does not arise.

### Open question for the orchestrator (do not decide alone)

`right_stack` index 0 is `DetailsPanel`, the asset importer. Routing a `vfx`
node to index 3 means a vfx slot's asset import is not reachable while the
preview is up — harmless today (no vfx sheets exist), but **ESV-5 imports
`vfx_*` spritesheets** and will want both. Ship the index-3 mode now and
**report this collision**; a tab or a split is a plan-level call.

---

## 4. Exit gate + Quick Test

### Gate

```bash
py tools/smoke.py                        # data validation + 5-frame headless boot
py tools/testgate.py check --affected    # blast radius ∪ core tier
```

**NOT the full suite** — `--affected` is this phase's gate. `GATE PASS` or you
are not done. A red test clearly outside this diff's blast radius: note it in
the report and stop; do not investigate.

### Required tests

All Qt tests: `QT_QPA_PLATFORM=offscreen`, subclass `QtCase` and
`self.track(...)` every widget (`close()` is not cleanup —
`editor/CLAUDE.md`), `TempDataCase` for the data dir, never a write into real
`data/`.

1. **A lever edit stages, and Save writes a valid `vfx.json`.** Move a numeric
   lever and pick a ramp colour → the balancing panel is dirty, the matching
   generic-form widget shows the same value, and `save_changes(...)` writes a
   file that `load_validated` accepts against `data/schemas/vfx.schema.json` in
   the temp dir. The `procedural` structure is unchanged apart from the two
   edited leaves (assert the whole doc equals the baseline with exactly those
   two substitutions — that is the "we didn't restructure ESV-3b's file" pin).
2. **The preview requests the engine emitter with the EDITED params.** With a
   spy over the `VfxSystem` seam, edit `muzzle.count` and `muzzle.life`, hit
   Emit, and assert the `MuzzleParams` the panel constructed carries the edited
   numbers. **Assert the params passed, not pixels.** Cover a second family
   (`death_burst`) so the family switch is exercised too.
3. **Named-stop ramp round-trip.** `{"stop_0": [255,230,120], …}` → three colour
   buttons showing those RGB values → set `stop_1` to a new colour → the staged
   doc still has the three named stop keys, in a dict, unreordered, with only
   `stop_1` changed; and the dataclass the emitter receives has the engine's
   3-tuple-of-tuples shape (mirror `game/ui/effects.py::_ramp`'s output shape).
4. **Deterministic emit.** Two Emits with the same seed and the same params
   produce identical particle counts and per-particle params. This is the guard
   that makes test 2 stable; it also proves the injected-RNG seam is really
   being used and not the stdlib `random`.
5. **Graceful degrade.** Select a `procedural` family with no emitter binding
   (`floaters` today; ESV-3b's `beam`/`crater`/`lightning`/`announce` tomorrow)
   → a placeholder message, no exception, no emit call. A right-click or a
   selection change must never be able to kill the editor
   (`editor/panels/CLAUDE.md` Phase-5 context-menu note).
6. **`TestPurity` covers the new modules** — `editor.vfx_params` and
   `editor.panels.vfx_preview` in the import tuple, and the subprocess still
   asserts no `game` module was imported. This is the layering pin for §2.5's
   duplicated adapter.

### Quick Test (manual, in-editor)

```bash
py editor/main.py
```

1. Select the **vfx** node in the selector. The balancing form below shows the
   `procedural` tree (the generic domain form, unchanged); the right pane shows
   the new preview.
2. Choose **muzzle**, tick **Loop** → an orange spray repeats at the preview's
   centre tile. Tick **strong** → visibly denser and longer-lived.
3. **Retint it**: click `ramp / stop_0`'s swatch, pick a green → the spray turns
   green on the next repeat, and the corresponding three spinboxes in the
   generic balancing form below have changed to the same RGB with a dirty dot.
4. Switch to **death_burst** and **slow it**: raise `life` to ~1.5 → the purple
   shards hang visibly longer.
5. Click **Save Balancing Changes**, give the session a name.
   `data/balancing/vfx.json` on disk validates, keeps sorted keys / 2-space
   indent, and still has the `stop_0/1/2` named-stop objects.
6. **Play** → in-game, a ranged enemy's muzzle spray is green and a defender's
   death shards hang for ~1.5 s. Nothing else about the game looks different.
7. Revert the values (or check out the file) before handing back if the Quick
   Test's edits were exploratory — the repo's shipped `vfx.json` must not carry
   accidental tuning.
