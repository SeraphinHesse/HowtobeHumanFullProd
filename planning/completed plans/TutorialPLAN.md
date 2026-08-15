<!-- status: COMPLETE — 7/7 phases -->

# TutorialPLAN.md — Guided tutorial + cutscene system

Phased, agent-executable plan (same family as `AgentDispatchPLAN.md` /
`MIGRATION_PLAN.md`). Base branch: `Development`. Runnable via
`/execute-plan-phases planning/TutorialPLAN.md TU-1-TU-7` or phase-by-phase.
Spans all four packages (engine / data / editor / game); each phase stays
single-package where possible so `coder` / `engine-coder` scoping is clean.

Source notes: the designer brief (Downloads/Tutorial.md) — forced first two
placements, guided highlight chain, two message texts, scripted first-round
loss, 3-lives intro.

## 1. Vision

New players must not ruin a run with their first two building choices. The
tutorial forces placement #1 — the **flute player** (`Musician`, economy) —
onto a designer-painted tile directly adjacent to the hole, and placement #2 —
the **stone thrower** (`Defender`, defence) — onto a designer-painted
diagonally-adjacent tile, via a guided chain:

> message box → white highlight on the designated tile (until clicked) → white
> box around the building's card in the construction list (until selected) →
> white box around Confirm in the details panel — with **all other input
> locked**.

After the required number of economy buildings is placed (balancing variable,
default 1) and the player presses **End Turn for the first time**, an MP4
cutscene plays (humans dragging out our munchkins) — **every game, before the
enemies spawn, even when the tutorial was skipped**. The round then runs and is
lost (no defences exist), which introduces the **3 lives** (the loss costs a
life by default — script-toggleable). A second message box explains lives /
destroyed-economy / defence buildings, then the same guided chain places the
stone thrower. The tutorial ends at 1 economy + 1 defence building placed.

The tutorial runs on **every new game** and is **skippable**. Everything
designer-facing is editable in the editor: message texts and step toggles
(Tutorial section), cutscene MP4s + companion audio (Cutscenes area, including
the intro), tutorial tiles (fourth map paint mode), message-box layout (UI
editor screen JSON).

The two message texts from the brief (initial content of the script):

1. *"You need love to create. In order for you to gain Love, you need economy
   buildings"*
2. *"Once the humans reach our hole the round is lost. You have only 3 lives.
   If economy buildings get destroyed during the human attack they don't yield
   resources. To defend your base you need to build defense buildings"*

## 2. Architecture decisions

- **D1 — Tutorial tiles are map markers.** `engine/tilemap.py` (pure, THE map
  authority) gains two nullable single-tile markers `tutorial_flute` /
  `tutorial_stone` — the exact `camera_start` pattern: schema-pinned in
  `map_file.schema.json`, bounds cross-checked in `validate_doc`, **never
  rendered by the emitters** (the editor draws its own overlay; the game never
  draws them). The editor paints them via a fourth paint mode; the game reads
  them off `TileMapDoc`. Rule-based tile picking was rejected — the designer
  wants exact control per map.
- **D2 — The engine tutorial piece is game-agnostic.** `engine/tutorial.py` is
  a **pure generic step-sequencer**: an ordered list of steps, each carrying
  `message` (string id), `highlight` targets (opaque string ids), an
  `advance_on` event id, an input `allow` list, and free-form `flags`. It knows
  nothing of flutes or holes (engine hard rule: no game vocabulary). The
  game-side **director** (`game/tutorial/director.py`) binds target ids to real
  things — the marker tiles, the construction-card index, the Confirm button,
  End Turn — and feeds events in (`tile_clicked:flute`,
  `building_selected:musician`, `building_placed:economy`, …).
- **D3 — The tutorial script is data.** `data/tutorial/tutorial.json` validated
  by `data/schemas/tutorial.schema.json` via a **directory exception** in
  `tools/smoke.py::validate_data` (exact precedent: `data/agent_forms/` →
  `agent_form.schema.json`). The script holds the step list, both message
  texts, `skippable: true`, `first_loss_costs_life: true` (the required
  toggle), and the highlight/gate wiring. Humans edit it only through the
  editor's Tutorial section (design pillar 3); agents via `write_validated`.
- **D4 — Cutscenes become a registry.** `data/video/cutscenes.json` +
  `data/schemas/cutscenes.schema.json` (second directory exception, or a
  stem-paired schema if the file moves to `data/cutscenes.json` — implementer
  picks whichever keeps `validate_data` simplest): entries
  `id → { video, audio (nullable), length, trigger }`. `trigger` enum:
  `intro` (the existing pre-menu slot, **migrated** — the hardcoded
  `data/video/cutscene.mp4` path in `game/main.py` moves into the registry) and
  `first_end_turn` (new — fires in `session.end_turn()` on round 1 **before**
  `spawner.begin_round()`). Room to grow (boss etc.) later. Playback reuses
  `engine.video.VideoSource` (OpenCV, lazy import, graceful skip preserved)
  for frames and `engine/audio.py` for the **companion audio file** — the
  MP4's own audio track is deliberately not decoded (no new dependency).
- **D5 — One new balancing tunable** (per the brief):
  `Tutorial.economy_buildings_required` (default 1, min 1) as a new `Tutorial`
  section in `data/balancing/core.json` + `data/schemas/core.schema.json` —
  the `/add-balancing-value` pattern. Gameplay-numeric values go to balancing;
  behavioral toggles (`skippable`, `first_loss_costs_life`) live in the
  tutorial script (D3) so the tutorial editor owns them.
- **D6 — Input gating is a whitelist at the two existing choke points**: the
  click dispatch around `panel.handle_click()` in `game/main.py` and the
  phase-advance calls in `game/core/session.py` (`end_turn` and friends). The
  director exposes `allows(action) -> bool`; when the tutorial is inactive,
  skipped, or finished it allows everything (zero-overhead path).
  `place_building()` (`game/buildings/registry.py`) is **untouched** — the
  gate sits in the UI layer, not the placement seam.
- **D7 — The message box is a normal data-driven screen**:
  `game/ui/tutorial_message.py` + `data/ui/screens/tutorial_message.json`,
  copying the `game/ui/game_over.py` shape (ids / layout / update / hit /
  submit + `ScreenSkinning`), so wording fallback and layout are UI-editor
  editable like every other screen. The first message box carries the
  **Skip tutorial** button (visible only when the script says `skippable`).
- **D8 — Highlights reuse existing primitives.** Tile: `submit_tile_diamond` /
  `submit_tile_diamond_fill` (`game/ui/widgets.py`) with new white constants.
  UI boxes (construction card, Confirm, End Turn): `HudRect` outlines drawn in
  an overlay pass above the normal HUD. No new render-backend work.

## 3. Build order

| Phase | Scope (package) | Status |
|-------|-----------------|--------|
| TU-1  | Foundations: map markers + tutorial script + cutscene registry + balancing var (engine + data) | not started |
| TU-2  | Editor: fourth map paint mode — first flute / first stone | not started |
| TU-3  | Editor: Cutscenes area — MP4 + companion-audio import, incl. intro slot | not started |
| TU-4  | Editor: Tutorial section — message texts + toggles | not started |
| TU-5  | Game: cutscene playback via registry — intro migrated + first-end-turn trigger | not started |
| TU-6  | Engine + game: step-sequencer + director + guided flute chain (message box, highlights, gating, skip) | not started |
| TU-7  | Game: scripted loss + lives intro + stone-thrower chain + tutorial end | *(LANDED — branch `phase-tu-7-scripted-loss-stone-chain`, off `Tutorial` at `b46b0e0`; full `py tools/testgate.py check` → GATE PASS 1588 ran, 0 failures; pending merge into `Tutorial`)* |

Dependencies: TU-2/TU-3/TU-4 depend only on TU-1 and are mutually independent
(parallelizable). TU-5 depends on TU-1; TU-6 on TU-1 (+TU-2 for a painted test
map); TU-7 on TU-5 + TU-6.

### Phase TU-1 — Foundations (engine + data, no UI)

**Goal**: every data shape exists and validates; the map format carries the
tutorial markers. Nothing player-visible yet.

**Files** — new: `data/tutorial/tutorial.json` (step list + both brief texts
verbatim + `skippable: true` + `first_loss_costs_life: true`),
`data/schemas/tutorial.schema.json`, `data/video/cutscenes.json` (entries:
`intro` → existing `cutscene.mp4`, length 44.2; `first_end_turn` → video path
placeholder, audio null), `data/schemas/cutscenes.schema.json`,
`tools/tests/test_tutorial_data.py`. Modified: `engine/tilemap.py`
(`tutorial_flute` / `tutorial_stone` markers on `TileMapDoc`, load/save,
`validate_doc` bounds checks), `data/schemas/map_file.schema.json`,
`tools/smoke.py` (directory exceptions per D3/D4),
`data/balancing/core.json` + `data/schemas/core.schema.json`
(`Tutorial.economy_buildings_required`), `tools/tests/test_tilemap_model.py`
(marker round-trip), `engine/CLAUDE.md` (tilemap marker note — architectural
change lands in the package doc).

**Tests**: marker save/load round-trip incl. `null`; out-of-bounds marker →
`ValueError`; both new JSON files validate via smoke; an invalid script
(unknown step key, missing text) fails; balancing load exposes the new
tunable; existing maps (no markers) still load.

**Exit gate**: `py tools/smoke.py` + `py tools/testgate.py check` → GATE PASS.

### Phase TU-2 — Editor: tutorial map paint mode

**Goal**: the designer paints "first flute" and "first stone" onto a map as a
fourth paint mode; markers save through `save_map`. (Use `/add-editor-feature`.)

**Files** — modified: the map-editor paint-mode toggle + viewport (add a
"Tutorial" mode with two sub-brushes: First flute / First stone; painting sets
the marker — one per kind, repainting **moves** it, right-click/erase clears;
drawn as labeled white diamond outlines via `submit_overlay_lines`, same idiom
as the `start_area` outline), `editor/panels/CLAUDE.md` (or the map-editor's
subsystem doc) for the mode description; tests in the editor tier.

**Tests** (offscreen Qt, temp data dir): entering the mode + click sets
`doc.tutorial_flute`; second click elsewhere moves it; erase clears; save →
reload round-trips; the other three paint modes are unaffected.

**Exit gate**: smoke + full testgate; **live Quick Test**: `py editor/main.py`,
paint both markers on a map, save, reopen, markers persist and render.

### Phase TU-3 — Editor: Cutscenes area

**Goal**: a Cutscenes editor surface — one row per registry entry (including
`intro`): import an MP4 (copied under `data/video/`), pick an optional
companion audio file (ogg/mp3, copied beside it), length auto-read via cv2
when available (manual spin-box fallback), trigger shown read-only. Writes
`data/video/cutscenes.json` via `write_validated`. (Use `/add-editor-feature`;
model the import-copy flow on the existing asset importer.)

**Files** — new: cutscenes panel module under `editor/panels/` + tests.
Modified: `editor/main.py` wiring, `editor/panels/CLAUDE.md`.

**Tests** (offscreen Qt, temp data dir + temp repo): import copies the file
and rewrites the registry (validated, deterministic format); missing cv2 path
falls back to the manual length field; audio optional (nullable round-trip).

**Exit gate**: smoke + full testgate; **live Quick Test**: import a small mp4
into the `first_end_turn` slot, confirm the file lands in `data/video/` and
the registry updates.

### Phase TU-4 — Editor: Tutorial section

**Goal**: the tutorial editor — edit both message texts, `skippable`, and
`first_loss_costs_life`; step *structure* is fixed (no reordering UI), only
texts/flags are editable. Writes `data/tutorial/tutorial.json` via
`write_validated`. (Use `/add-editor-feature`.)

**Files** — new: tutorial panel module under `editor/panels/` + tests.
Modified: `editor/main.py` wiring, `editor/panels/CLAUDE.md`.

**Tests** (offscreen Qt, temp data dir): edits round-trip through save/reload;
toggle states persist; invalid text (empty) blocked or schema-rejected loudly.

**Exit gate**: smoke + full testgate; **live Quick Test**: flip
`first_loss_costs_life`, reopen editor, the toggle held.

### Phase TU-5 — Game: registry-driven cutscene playback

**Goal**: `CutscenePlayer` generalizes the intro blit loop; both triggers work.

**Files** — new: `game/ui/cutscene_player.py` (or `game/core/` — implementer's
call; wraps `VideoSource` + `engine.audio.play_music`/`stop_music` for the
companion file, click/key skip like the intro, graceful-skip when cv2 or the
file is absent) + tests. Modified: `game/main.py` (intro path reads the
registry `intro` entry instead of the hardcoded path/length; host plays
`first_end_turn` when session requests it), `game/core/session.py`
(`end_turn()` on round 1 sets a `pending_cutscene` request **before**
`spawner.begin_round()` — fires every game, independent of tutorial state),
`game/CLAUDE.md` or the relevant subsystem doc.

**Tests** (headless): registry load; `end_turn()` round 1 requests the
cutscene exactly once per run (round 2+ never); missing video → graceful skip
and the round still starts; audio calls are no-ops under SDL dummy (already
guaranteed by `engine/audio.py`).

**Exit gate**: smoke + full testgate; **live Quick Test**: `py game/main.py`,
end the first turn → cutscene plays (with audio if a companion file is set),
click skips it, enemies spawn after.

### Phase TU-6 — Engine sequencer + game director + guided flute chain

**Goal**: the round-1 guided chain works end-to-end: message box #1 (with Skip
when `skippable`) → white tile highlight until clicked → white box on the
Musician card until selected → white box on Confirm → placement; all other
input rejected; End Turn highlighted once `economy_buildings_required` is met.

**Files** — new: `engine/tutorial.py` (pure sequencer per D2 — engine-coder
scope; **no game vocabulary**), `game/tutorial/__init__.py` +
`game/tutorial/director.py` (loads the script + map markers, binds targets,
`allows()`, event feed), `game/ui/tutorial_message.py`,
`data/ui/screens/tutorial_message.json`, `tools/tests/test_tutorial_engine.py`,
`tools/tests/test_tutorial_director.py`. Modified: `game/main.py` (input
whitelist around `panel.handle_click()`; director event hooks at the tile-click
site; overlay submits for highlights + message box), `game/ui/building_ui.py`
(expose card/Confirm rects for the highlight overlay + selection events —
minimal, additive), `game/ui/widgets.py` (white highlight constants),
`game/core/session.py` (skip/allow checks on `end_turn`), `game/CLAUDE.md` +
`engine/CLAUDE.md` (new modules), `conftest.py` TIERS for the new test modules.

**Tests** (headless): sequencer unit tests (advance on matching event only,
allow-list queries, skip → terminal state, flags exposure); director driven
with fake events walks the whole flute chain; `allows()` blocks unlock/other
tile clicks mid-chain and allows everything when skipped/finished; map without
markers → tutorial auto-skips with a logged warning, never crashes.

**Exit gate**: smoke + full testgate; **live Quick Test**: new game → message
box #1 appears; clicking anywhere else does nothing; the chain walks
tile → card → Confirm; Skip button ends all gating immediately.

### Phase TU-7 — Scripted loss, lives intro, stone-thrower chain, tutorial end

**Goal**: the round-1 loss plays out (no defences → enemies reach the hole),
costing a life iff `first_loss_costs_life`; message box #2 (lives text) shows
at ROUND_END; round 2 opens the guided stone-thrower chain against
`tutorial_stone`; after that placement the tutorial ends and all input is
released.

**Files** — modified: `game/tutorial/director.py` (loss handling, second
chain, end state), `game/core/session.py` (`on_base_hit` consults the director
for the free-loss case — only during the scripted tutorial round),
`data/tutorial/tutorial.json` (script gains the round-2 steps — schema from
TU-1 already covers them), tests extended.

**Tests** (headless): with `first_loss_costs_life: true` the run ends round 1
with 2 lives, with `false` still 3; message box #2 fires at ROUND_END of round
1 only; round-2 chain binds to `tutorial_stone` and only the Defender card is
selectable; after the defence placement `allows()` returns True for
everything; skipped-tutorial runs never see boxes #1/#2 but still get the
TU-5 cutscene.

**Exit gate**: smoke + full testgate (this is the hand-back phase — full
`check` once); **live Quick Test**: full playthrough of the tutorial from new
game to free play, then a second run using Skip.

## 4. Risks / open items

- **OpenCV optionality**: cutscenes silently skip without cv2 (engine
  contract). The tutorial must therefore gate on *events* (end_turn,
  placements), never on "cutscene finished" — TU-5/TU-6 tests pin this.
- **Audio/video sync is best-effort**: `mixer.music` starts alongside the
  first frame; companion files are authored to match. No drift correction in
  scope.
- **OneDrive**: MP4 imports copy large files into the synced tree; accepted
  for now (same posture as existing `data/video/cutscene.mp4`). Also note the
  known OneDrive silent-reversion risk when verifying imports.
- **Maps without painted markers**: tutorial auto-skips with a logged warning
  (never crashes). An editor save-time warning ("map has no tutorial tiles")
  is a possible follow-up, not in scope.
- **`BOSS_CUTSCENE` overlap**: the boss modal stays as-is; unifying it into
  the cutscene registry is explicitly out of scope for this plan.
- **`building_ui.py` coupling** (TU-6): exposing card/Confirm rects must stay
  additive; if it turns invasive, fall back to the director reading the
  panel's existing `ids`/geometry instead of new hooks — decide in-phase.
- **Brief ambiguity, resolved**: the brief's static sketch is superseded by
  painted markers (D1); "editable via the UI editor" is satisfied by D3+D7
  (script text in the Tutorial section, box layout in the UI editor screen).
