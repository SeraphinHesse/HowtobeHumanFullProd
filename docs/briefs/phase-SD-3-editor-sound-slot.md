# Phase SD-3 — Editor sound slot (editor)

Source plan: `planning/SoundEditorPLAN.md` §"Phase SD-3" (lines 286–333), §2.1
(slot shape), §2 "Load-bearing facts", §5 risks.
Depends on: **SD-1 only** (schemas carrying `x-widget: "sound_slot"` and the
`$defs/sound_slot` block). Independent of SD-2 and of SD-4–SD-7.

**Read before editing**: root `CLAUDE.md` → `editor/CLAUDE.md` →
`editor/panels/CLAUDE.md`. Do not read the game or engine docs; nothing in this
phase touches `game/` or `engine/audio`.

---

## 1. Behavioral spec

**Goal (plan:288-289)**: a designer imports a clip, sets volume/trim/loop, adds
variations, and hears it — without leaving the balancing form.

### 1.1 What renders, and where

The balancing panel is a generic schema-walking form generator; it already
supports composite rendering steered by schema extensions, which is why this
phase costs almost no editor code:

- `editor/panels/balancing.py:361` `_build_object` — one object level; scalar
  leaves collect into `QFormLayout`s, nested objects/arrays become
  `CollapsibleSection`s (`:122`), in sorted key order.
- `editor/panels/balancing.py:370` — `prop = self._deref(prop)` resolves the
  local `#/$defs/` ref. `_deref` (`:335`) accepts **only** `#/$defs/` refs and
  raises on anything else, so SD-1's per-domain duplicated `$defs/sound_slot`
  resolves here for free.
- `editor/panels/balancing.py:371-372` — the `x-paired` precedent: a schema
  annotation makes `_build_object` **skip** its default handling of a key.
- `editor/panels/balancing.py:638` `_build_toggle_checkbox` — the `x-toggle`
  precedent: a schema annotation injects an extra widget into a leaf row.
- `editor/panels/balancing.py:419` — the `x-array-editable` precedent: a schema
  annotation turns an array into a `+ Row` / `− Row` editable list.
- `editor/panels/balancing.py:670` `_make_widget` — **the ONE widget switch**
  ("widget per schema type: invalid input unrepresentable (ED-30)"), ending in
  `raise ValueError(f"{self.domain}.{key}: no widget for schema {prop!r}")`
  (`:706`).

A schema node marked `x-widget: "sound_slot"` (an object, per §2.1) must render
as **one `SoundSlotWidget`** in place of the `CollapsibleSection` +
recursive-object rendering it would otherwise get.

### 1.2 The widget's behaviour

Reading the slot object (plan §2.1, lines 137-156):

| Control | Backing key | Behaviour |
|---|---|---|
| Clip list | `clips[]` | one row per clip; several clips = random variation |
| *Import…* | appends to `clips[]` | file dialog → copy into `data/audio/imported/` → new clip row with the returned `file` |
| *Use existing…* | appends to `clips[]` | picker over already-imported clips; **copies no bytes**, just references |
| *Remove* | pops a clip | list shrinks; empty list is legal (see semantics below) |
| Volume | `clips[i].volume` | 0.0–1.0, range **read from the schema** (`minimum`/`maximum`), never hardcoded |
| In / Out trim | `clips[i].start` / `.end` | seconds; `end: 0.0` = play to the end (a sentinel, **not** `null` — plan:116-117, `data/CLAUDE.md:410-412`) |
| Loop | `loop` | bool |
| Pick | `pick` | enum, exactly `["random", "sequential"]` |
| ▶ Preview | — | plays the highlighted clip; see 1.3 |

**Empty-clips semantics differ by layer and MUST be surfaced in the widget's
tooltip** (plan:500-502): `clips: []` on a **global default** = silence;
`clips: []` on an **element override** = inherit the default. A designer who is
not told this will misread an empty override as "silent".

### 1.3 Preview — QtMultimedia, never `pygame.mixer`

`editor/panels/viewport.py:40` executes `os.environ.setdefault("SDL_AUDIODRIVER",
"dummy")` **at module level**, for the whole editor process. `pygame.mixer` in
the editor is therefore silent by construction — preview must not use it.

Preview uses **QtMultimedia, lazily imported inside the click handler**, exactly
as `editor/thats_my_producer.py:15-32` does:

```
    try:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    except ImportError:
        return
```

with that file's two further load-bearing details:
- the comment at `thats_my_producer.py:16-19` — QtMultimedia loads the platform
  audio stack **on import**, so a module-scope import would break `editor.main`
  on an audio-less box;
- `thats_my_producer.py:30-32` — the player and the `QAudioOutput` are kept
  alive on the parent; a GC'd `QMediaPlayer` stops mid-playback.

Difference from the easter egg: SD-3 must **degrade visibly** — when the import
fails, the ▶ button is constructed **disabled** with a tooltip saying
QtMultimedia is unavailable, rather than silently doing nothing. Volume and trim
are applied to the preview on a best-effort basis (`QAudioOutput.setVolume`,
`QMediaPlayer.setPosition` for `start`); a preview that ignores trim is
acceptable, a preview that raises is not.

### 1.4 Import-copy

Modelled on the existing audio import-copy flow, `editor/cutscene_import.py:93`
(`audio_dest`) + `:145` (`import_audio` — "ogg/mp3 passthrough, no transcoding",
returning the bare destination filename) over `_copy_if_different:128` (skips the
copy when source and destination resolve to the same file, `mkdir(parents=True,
exist_ok=True)` first).

Differences from `cutscene_import`:
- destination is `data/audio/imported/<name><suffix>`, and the stored `file` is
  **relative to `data/audio/`** (plan:147) — i.e. `imported/<name>.ogg`.
- the stem is **not** 1:1-owned by an id (a cutscene's audio is; a clip is
  shared), so name collisions must not silently overwrite: mint a suffixed name.
- accepted extensions are `.ogg` / `.wav` / `.mp3` (D8, plan:66); anything else
  is **rejected**, not copied.
- an optional transcode-to-`.ogg` path powered by `soundfile`; if `soundfile`
  does not import, `transcode_available()` is False, the checkbox is disabled,
  and the raw-copy path still works (plan:311-313, risk at :490-492).
- a size warning above a threshold — `data/audio/Bass_and_drum_Duo.wav` is
  already 49 MB (plan:313-314, :493-495).

### 1.5 "Use existing…" refcounting

Modelled on `editor/asset_import.py:55` `sheet_users` ("Slot keys whose manifest
entry points at `ref` — the refcount that makes Clear safe. Empty ⇒ the PNG is
unreferenced and free to delete") and `:66` `unreferenced_sheets` ("clearing a
linker must not delete art its source still needs"). The picker dialog mirrors
`editor/panels/sheet_picker.py:33` `SheetPickerDialog` (list + preview +
`QDialogButtonBox`, with a testable `chosen()`/`visible_sheets()` model half).

For SD-3 the "users" are **slot paths across the five balancing docs**, not
manifest entries. `clip_users` / `unreferenced_clips` are **pure functions over
passed-in docs** — they never load `data/` themselves.

**The counts are CROSS-DOMAIN** (orchestrator decision). Same-domain counts
would show a clip used by an enemy as unreferenced while the designer browses
`buildings`, so the unreferenced/cleanup affordance would invite deleting a clip
that is in use. The picker therefore counts across all five domains — `core`,
`ui`, `map`, `buildings`, `enemies` — and the loading site is pinned in §2.7.

### 1.6 Persistence

The widget stages the **whole slot object** through the panel's existing
`_commit` (`editor/panels/balancing.py:725`) — no second doc, no second dirty
set, no second writer. Save remains the balancing panel's one button
(`_on_save:818` → `save_changes:826` → `data_io.write_validated`). Humans never
hand-edit `data/` JSON.

---

## 2. Architecture plan

### 2.0 Invoke the skill

**This phase adds an editor feature; open with the `/add-editor-feature`
skill** (`editor/CLAUDE.md:14-17`: "Adding an editor feature or panel? Use the
`/add-editor-feature` skill… encodes the full pattern; don't hand-roll"). Follow
the skill's file/order/verify pattern rather than hand-rolling the edits; this
brief supplies the specifics the skill asks for.

### 2.1 New module — `editor/sound_import.py` (PURE)

Qt-free and pygame-free, the `asset_import.py` / `font_import.py` /
`cutscene_import.py` shape. Public surface (plan:293-298):

- `clip_ref(name)` → the `imported/<name><suffix>` string stored in `file`.
- `import_clip(data_dir, src, name, transcode=False)` → copy (or transcode)
  into `data/audio/imported/`, return the ref. Rejects non-audio extensions.
- `imported_clips(data_dir)` → the reuse picker's model (a frozen dataclass per
  clip: `ref`, `path`, size, `users` — `ImportedSheet`'s shape,
  `asset_import.py:71`).
- `clip_users(docs, ref)` / `unreferenced_clips(docs, refs)` — refcount, pure.
  `docs` is a **mapping `{domain: doc_or_None}`** covering all five domains; a
  `None` entry means *that domain could not be read*, which both functions must
  propagate as **"count unknown"**, never as zero (see §2.7).
- `usage_docs(data_dir, staged_domain=None, staged_doc=None)` — the ONE loader
  (§2.7). It is the only disk-reading function here, mirroring
  `asset_import.imported_sheets`'s precedent of a pure module that still globs
  `data/`.
- `transcode_available()` → `soundfile` imports.
- a size-threshold constant + a `warn_oversize(path)`-style predicate.

`data_dir` is injected on every function; no module-level `data/` path.

### 2.2 New panel module — `editor/panels/sound_slot.py`

`SoundSlotWidget(QWidget)`. Constructed with `(slot_value, slot_schema, path,
panel, data_dir, parent=None)` — it holds a reference to the `BalancingPanel`
and writes through `panel._commit` / `panel.stage_value` (`:747`), the
`vfx_preview.py` seam precedent (`editor/CLAUDE.md`: the VFX panel "STAGES
through `self._balancing.stage_value` — this panel does not become a second
writer").

Every numeric control is a `_NoWheelDoubleSpinBox` / `_NoWheelSpinBox` and every
combo a `_NoWheelComboBox`, **imported from `editor.panels.balancing`, never
copied** (`editor/panels/CLAUDE.md:156-161`, ED-30). Ranges/decimals come from
the schema node (`minimum`/`maximum`/`enum`), so SD-1 owns the bounds.

`QFileDialog` stays confined to ONE `_on_import_clicked` method, and **dialog
construction is split from display** so no test calls `exec()` (editor rule 12;
`master_sheet_dialog` / `sheet_picker` precedent — `chosen()` is the model half).

**Start-trim greying (plan §5, :485-489)**: SD-2 ships `end`-only trim when
numpy is absent. SD-3 must not import numpy at runtime nor import
`engine.audio`; instead the `start` spin is disabled behind a single
module-level feature probe (`try: import numpy`) with a tooltip explaining it.
This is the one coupling to SD-2's behaviour and it is expressed as a local
probe, not an import of SD-2.

### 2.3 The `x-widget` hook — ONE place

`_make_widget:670` stays **the one widget switch**: add a first branch

```
    if prop.get("x-widget") == "sound_slot":
        widget = SoundSlotWidget(...)
```

before the `"enum" in prop` branch, so the widget-construction knowledge has
exactly one home and `_make_widget`'s terminal `raise` (`:706`) still means
"unhandled schema".

`_build_object` must **route** to it, because a `sound_slot` is an `object` and
`_build_object:373-390` sends objects down the `CollapsibleSection` + recursion
path and never reaches `_make_widget`. Insert immediately after the `x-paired`
skip (`:371-372`) and **before** `kind = prop.get("type")` (`:373`):

```
    if prop.get("x-widget"):
        form = form or <new QFormLayout added to parent_layout>
        self._add_leaf_row(form, key, prop, value[key], path + (key,))
        continue
```

Reusing `_add_leaf_row:522` is deliberate: it is what registers the widget in
`self._widgets`, attaches the dirty dot, and sets the tooltip from
`description` — so the slot gets dirty-dot behaviour, history and rebuild
handling with no new bookkeeping. *(The plan's phase block says `_build_object`
intercepts and §2's fact-list says the hook lives in `_make_widget:670`; this
split satisfies both and is the only reconciliation this brief makes.)*

### 2.4 The two round-trip methods

- `_set_widget_value:795` — its `isinstance` chain must learn `SoundSlotWidget`
  (a whole-slot `set_slot(value)` call). Without this, **Version History**
  (`_apply_snapshot:806`, which iterates `self._widgets`) would silently skip
  every sound slot.
- `_apply_snapshot:806` itself needs no change once `_set_widget_value` knows
  the type — it already `continue`s on a missing path.

`_rebuild_form:309` clears `self._widgets` and re-walks, so an added/removed
clip can simply `_commit` the new `clips` list and call the panel's rebuild —
the `_commit_structure:513` idiom — or the widget can rebuild its own rows.
Either is acceptable; do **not** invent a second dirty set.

### 2.5 Layering / purity

- `editor/` never imports `game/`. Both new modules go into
  `test_editor_viewport.TestPurity`'s import list (`editor/CLAUDE.md:96-98`;
  the list is `tools/tests/test_editor_viewport.py:1494-1537`).
- `editor/sound_import.py` is pure — list it alongside `editor.cutscene_import`
  (`:1500`); `editor.panels.sound_slot` alongside `editor.panels.sheet_picker`
  (`:1512`).
- No `pygame.mixer` anywhere in this phase.

### 2.6 `requirements.txt`

Add `soundfile` marked **OPTIONAL**, in the existing style of
`opencv-python    # cutscene playback (engine/video.py) — OPTIONAL: absent =
cutscene gracefully skips`.

### 2.7 Where the five domain docs are loaded (pinned — do not invent)

The refcount functions stay pure; **the caller above the widget does the
loading**, and it is exactly these two named pieces:

1. **`editor/sound_import.usage_docs(data_dir, staged_domain=None,
   staged_doc=None)`** — builds `{domain: doc_or_None}` for the five domains.
   Paths come from `editor/domains.py:60` `balancing_path` + `:64`
   `schema_path` (never a hand-built path); each doc is read with
   `engine.data_io.load_validated` (`engine/data_io.py:69`).
   - **The domain named by `staged_domain` is NOT read from disk** — its entry
     is `staged_doc` verbatim. That is the live staged document, so a clip the
     designer attached seconds ago and has not saved counts as referenced.
     Without this, "Use existing…" would report the designer's own just-made
     attachment as unreferenced.
   - **The other four come from disk, and a read failure degrades to `None`
     ("count unknown"), never to an empty doc.** Catch the load error per
     domain, keep going, and let `clip_users`/`unreferenced_clips` surface
     unknown. A clip must never be reported unreferenced because a file failed
     to load — that is the one failure mode that costs a designer their audio.
     `unreferenced_clips` therefore returns nothing at all while any domain is
     unknown, and the picker labels those rows "usage unknown".
   - The domain list is `editor/domains.py:35` `domains(data_dir)` — derived,
     never a hardcoded five-element literal (`editor/panels/CLAUDE.md:211-232`:
     a new balancing domain must appear with zero editor edits). A domain with
     no sound slots simply contributes no users.

2. **`BalancingPanel.sound_usage_docs()`** — a new one-line public method on
   `editor/panels/balancing.py`, placed beside the existing `staged_value:741` /
   `stage_value:747` seam methods (the same "a caller outside this class needs
   the staged doc" section). It returns
   `sound_import.usage_docs(self._data_dir, self.domain, self._doc)` — the panel
   is the only object that holds both the live staged doc and its domain name.

**Invocation site**: `SoundSlotWidget._on_use_existing_clicked` calls
`self._panel.sound_usage_docs()` and hands the result to the picker dialog. The
widget itself never loads a file and never reaches for `data/` — it holds the
panel reference it already needs for `_commit`/`stage_value`.

---

## 3. File scope + shared-file contract

### 3.1 New files (SD-3 owns them outright)

- `editor/sound_import.py`
- `editor/panels/sound_slot.py`
- `tools/tests/test_sound_import.py`
- `tools/tests/test_sound_slot_widget.py`

### 3.2 Modified files

| File | Exact insertion point | Contract |
|---|---|---|
| `editor/panels/balancing.py` | `_build_object` — after the `x-paired` `continue` at `:371-372`, before `kind = prop.get("type")` at `:373` | route `x-widget` props to `_add_leaf_row` |
| `editor/panels/balancing.py` | `_make_widget:670` — a new FIRST branch, before `if "enum" in prop` | build the `SoundSlotWidget`; the `raise` at `:706` is untouched |
| `editor/panels/balancing.py` | `_set_widget_value:795` — a new `isinstance` arm in the existing chain | whole-slot set, for history/snapshot |
| `editor/panels/balancing.py` | a new `sound_usage_docs()` beside `staged_value:741` / `stage_value:747` | the ONE cross-domain loading site (§2.7) |
| `tools/tests/test_editor_viewport.py` | the `TestPurity` import string, `:1494-1537` | `+ editor.sound_import`, `+ editor.panels.sound_slot` |
| `requirements.txt` | after the `opencv-python` OPTIONAL line | `soundfile`, marked OPTIONAL |
| `editor/panels/CLAUDE.md` | the balancing-panel section | document the `x-widget` hook + the widget (architecture changed → the PANELS doc, not the router) |

**`editor/panels/balancing.py` is the one shared file.** All four edits above
are additive and confined to those three named methods plus one new public
method. Do not touch `_commit`, `_refresh_dirty`, `save_changes`, or the array
`+/- Row` machinery.

### 3.3 Schema keys this phase reads and writes (lockstep with SD-1)

SD-3 **reads** from the schema (never hardcodes):
- `x-widget: "sound_slot"` — the marker. **Confirmed by the orchestrator: SD-1
  put it INSIDE `$defs/sound_slot`, not beside the `$ref`**, precisely because
  `_build_object:370` derefs before inspecting the node (`_deref:335-341`). The
  hook at `:371-373` therefore sees it and fires. Do not also look for it on the
  `$ref` site.
- `$defs/sound_slot` (resolved via `_deref:335`; local `#/$defs/` only —
  cross-file refs are banned, `data/CLAUDE.md:438-455`, hence SD-1's per-domain
  duplication).
- `clips` (array) → `$defs/sound_clip` with `file` (string), `volume` (number,
  whose `minimum`/`maximum` drive the spin range), `start` (number), `end`
  (number).
- `loop` (boolean).
- `pick` (string enum, exactly `["random", "sequential"]` — drives the combo).
- every node's `description` → tooltips.

SD-3 **writes** back exactly that object shape and nothing else: no new keys, no
`null`, no absent keys (all keys are `required` per SD-1, plan:154-156, so the
widget always has every key present and never has to create one). `end: 0.0`
means "play to the end" — the widget must never write `null` there.

**Three things about SD-1's layout the widget must NOT assume** (all confirmed
by the orchestrator against SD-1's brief):
- **The case split is deliberate**: capital `Sounds` on
  `buildings.BuildingsGlobal`, lowercase `sounds` on the 12 leaf families. The
  widget is driven by the `x-widget` marker and its own path, so it must never
  match on either spelling.
- **The slot inventory is not fixed.** `core.Sounds.Game.game_over` was added
  after this brief was first written and needed no widget change — because
  nothing here enumerates slots. Keep it that way: no slot list, no slot-name
  branch, anywhere in `sound_slot.py` or `sound_import.py`.
- **`ui.Sounds` is CLOSED to exactly `button_click` + `not_enough_love`.** The
  per-button override is SD-6's, and it is a plain string key in
  `data/schemas/ui_screen.schema.json` — **not** a `sound_slot`, so this widget
  never renders it.

**If SD-1 renames a key or moves the marker, SD-3's `_make_widget` branch and
`SoundSlotWidget`'s field lookups are the only two places to change.** Drift is
caught by `test_sound_slot_widget.py`'s pinned fixture, not by the live schema.

### 3.4 Out of scope for SD-3

`engine/audio*` (SD-2), any `game/` trigger (SD-4–SD-7), the settings sliders
(SD-6), `data/schemas/*` and `data/balancing/*` content (SD-1). If a schema node
the widget needs is missing, **report it as an SD-1 gap** — do not patch the
schema from this phase.

**DO NOT CHANGE (pinned repo-wide by the orchestrator, restated here because
this brief mentions the audio surface):** `engine.audio`'s legacy `play_music` /
`stop_music` / `set_volume` all return `None`, asserted at
`tools/tests/test_audio.py:23-44`. SD-3 does not import `engine.audio` at all —
preview is QtMultimedia (§1.3) — so this is a boundary to stay clear of, not an
API to consume.

---

## 4. Exit gate + Quick Test

### Bare-minimum tests

Write only what pins the contract; do not broaden coverage.

`tools/tests/test_sound_import.py` (pure, **no Qt**, `DataDirCase` —
`tools/tests/temp_data.py:110`):
1. `import_clip` copies into a temp `data_dir`'s `audio/imported/` and returns
   the `imported/<name><suffix>` ref.
2. a non-audio extension is rejected.
3. `clip_users` / `unreferenced_clips` refcount over hand-built docs for **two
   different domains** (the cross-domain rule, §1.5), plus: one domain set to
   `None` makes the result "unknown", never "unreferenced" (§2.7).
4. transcode is skipped cleanly when `soundfile` is absent.

`tools/tests/test_sound_slot_widget.py` (`TempDataCase`, `self.track(...)` every
widget — editor rule 1, `editor/CLAUDE.md:544-550`):
1. a `BalancingPanel` over a **pinned fixture schema+doc** renders a
   `SoundSlotWidget` for an `x-widget: "sound_slot"` node.
2. editing volume/loop/pick round-trips into the panel's staged doc via
   `_commit`, and the whole slot survives `_set_widget_value`.
3. adding then removing a clip restructures `clips`.

Never assert against live `data/` (rule 2, `editor/CLAUDE.md:559-563`). Audio is
stubbed to **zero bytes** in the temp copy (`tools/tests/temp_data.py` docstring;
the opt-in flag lives at `:119`) — any test that actually decodes a clip must
opt in, so **prefer not to decode at all**. No test may `exec()` a dialog.

### Exit gate (run exactly these — nothing else)

```
py tools/smoke.py
py -m pytest tools/tests/test_sound_import.py tools/tests/test_sound_slot_widget.py tools/tests/test_editor_viewport.py -q
```

The gate is **ZERO failures**. Do **not** run `py tools/testgate.py check`, do
**not** pass `--affected`, do **not** run a tier sweep (`-m core` / `-m editor` /
`-m meta`) — `.claude/hooks/test_guard.py` denies all of these for a subagent.
The single full gate is the main session's step at handoff (root `CLAUDE.md`
§"Test Suite Policy" is the only authority).

### Quick Test (in-editor; the orchestrator or user runs it, not the coder)

`py editor/main.py` → select `buildings` → *DefenceBuildings → BasicDefence →
Sounds → attack* → **Import…** a short `.ogg` → the clip row appears → press ▶
(it plays; on a box without QtMultimedia the button is visibly disabled with a
tooltip) → set volume `0.5` → **Save Balancing Changes** → reopen the editor and
confirm the value persisted into `data/balancing/buildings.json` and the file
landed in `data/audio/imported/`. Then **Use existing…** on a second slot and
confirm it references the same file without copying a second time.

### Report

Tag every claim **measured** / **verified** / **inferred**. Report any SD-1
schema gap and any live-editor behaviour you could not exercise (e.g. no audio
device) rather than papering over it.
