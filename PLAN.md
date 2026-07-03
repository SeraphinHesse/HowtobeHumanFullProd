# PLAN.md — How To Be Human: Full Production Rebuild

Status: **phase 0 (bootstrap) in progress.** Update the phase table at the bottom
as phases land. The behavioral spec for gameplay is the prototype repo at
`../HowToBeHuman/ClaudePrototype/HowToBeHuman` — the old repo is the *spec*, not
the starting point. The detailed requirements live in [`SPEC.md`](SPEC.md).

## 1. Vision

Rebuild How To Be Human from scratch as three cleanly separated parts: a
**pseudo-engine** (carries exactly this game's workload, nothing more), the
**game** built on it, and a **central editor** (PySide6) that is the designer's
only interface — balancing, map design, asset importing, and Claude agent
dispatch all happen in the editor.

**Design pillars** (tie-breakers for every future decision):

1. **Agent legibility** — small single-purpose files, one canonical data format
   with schemas, no editor-only hidden state. The repo must stay cheap for
   Claude agents to read and safe for them to edit. (This is *why* the project
   stays Python instead of moving to Godot/Unity.)
2. **Strict layering** — game logic never touches pygame; editor and game never
   import each other; both consume `engine/` and `data/`.
3. **Editor is the designer interface** — humans never hand-edit JSON. JSON
   persists underneath (diffable by git, writable by agents) but it is an
   implementation detail, like Unity's `.meta` files.

## 2. Repo bootstrap (first commit)

- `.gitignore`: `build/`, `dist/`, `__pycache__/`, `.venv/`, `*.exe`, editor
  prefs, logs. **Built artifacts are never committed** (fixes the prototype
  repo's dirty-binary-files problem). Committed: source, `data/` JSONs, source
  sprite sheets in `data/sprites/`.
- Folder skeleton with a CLAUDE.md router at root + one CLAUDE.md per package.
- `PLAN.md` (this file), `SPEC.md`, `requirements.txt`
  (`pygame-ce`, `PySide6`, `Pillow`, `jsonschema`), `README.md`.

```
HowtobeHumanFullProd/
├─ CLAUDE.md                # router → one package doc per task
├─ PLAN.md  SPEC.md  .gitignore  requirements.txt  README.md
├─ .claude/                 # commands (start-domain etc.), hooks, locks integration
├─ engine/                  # the pseudo-engine
│  ├─ CLAUDE.md
│  ├─ core/                 # loop, GameObject, Component, Transform, Scene, events
│  ├─ coords/               # THE coordinate system (world↔screen, iso projection)
│  ├─ render/               # RenderItem collection, depth sort, pygame backend
│  ├─ physics/              # movement, range/radius queries, spatial grid
│  └─ assets/               # manifest, slot registry, animation slicing, placeholder
├─ game/
│  ├─ CLAUDE.md
│  ├─ main.py               # window host: engine → pygame window
│  └─ buildings/ enemies/ map/ ui/ core/
├─ editor/                  # PySide6 application
│  ├─ CLAUDE.md
│  ├─ main.py               # shell, docking layout
│  ├─ panels/               # selector, viewport, balancing, asset import
│  ├─ run_controls.py       # Play / Build / Playbuild
│  ├─ spawnclaude.py        # launch scoped Claude sessions
│  └─ locks.py
├─ data/                    # single source of truth (editor + agents write; game reads)
│  ├─ CLAUDE.md
│  ├─ schemas/              # JSON Schema per file type — all writers validate
│  ├─ balancing/            # per-domain balancing JSON (locks live here)
│  ├─ maps/                 # map files + active_map selector
│  └─ sprites/              # imported sheets + asset_manifest.json
└─ tools/                   # headless smoke test, build script (PyInstaller)
```

## 3. Engine

**Coordinate system (`engine/coords/`)** — the linchpin, built first. One
authority for world space (fractional tile coords) → screen pixels (iso
projection + camera offset + zoom) and the exact inverse (screen → world,
needed for click-to-paint in the map editor and tile picking in game). Nothing
outside this module converts coordinates. Geometry constants (tile pitch, map
dims) are data-driven from `data/`.

**GameObject model (`engine/core/`)** — hybrid, with the sanity rule:
**components are what the editor sees; subclasses are behavior convenience.**

- `GameObject`: id, name, `Transform` (world pos, layer/height), list of
  `Component`s, lifecycle (spawn/update/despawn).
- `Component`: serializable data + optional `update(dt)`. Core set:
  `SpriteAnimator` (asset key + current animation state), `Health`, `Movement`,
  `RangeSensor`, plus game-defined ones. Phasing: `SpriteAnimator` + `Health`
  ship in phase 2; `Movement` + `RangeSensor` ship with `engine/physics`
  (whose queries they wrap) at the start of phase 9.
- Game code subclasses `GameObject` (e.g. `Building(GameObject)`) to wire
  components in `__init__` — but **no gameplay state outside components**, so
  the inspector and the serializer see everything generically.
- `Scene`: owns objects, drives update order, queryable (by type/tag/area).

**Render pipeline (`engine/render/`)** — three strict layers:

1. Game objects submit **visual data** each frame —
   `RenderItem(asset_key, animation, frame_time, world_pos, layer, tint, …)`.
   No pixels, no pygame.
2. The **renderer layer** collects all RenderItems, resolves each to a concrete
   surface+frame via the asset system, sorts for iso depth, converts every
   world position to pixels via `engine/coords`, producing a flat draw list.
3. The **pygame backend** blits the draw list to a target `Surface` — the
   *game window* in game, an *offscreen surface shown in a Qt widget* in the
   editor. Same pipeline, two hosts.

Game logic is fully headless-testable (layers 2–3 simply not invoked).

**Physics (`engine/physics/`)** — deliberately simple: waypoint/path movement,
range & radius queries (spatial grid so towers don't scan all enemies), tile
occupancy. No forces, no collision response.

**Asset system (`engine/assets/`)** — the prototype's asset-importer model,
generalized to *all* game visuals:

- **Universal slot registry**: every renderable thing declares an asset slot —
  buildings (type/tier/level), enemies, tiles, UI elements, VFX. Slot = key +
  frame size + category. Registry is data-driven, not hardcoded per family.
- **Manifest (v2 of the prototype format)**: per entry — sheet path,
  frame_w/h, offset_x/y, rows[] with
  `{animation, fps, hidden[], loop_start/end/count}`. Row 0 = idle. Same
  `playback_order` semantics (pre-roll, looped range × count, post-roll,
  hidden frames dropped).
- **Placeholder**: any slot without a manifest entry renders a **default grey
  X** (at the slot's frame size) — in game *and* editor. No procedural art
  system in the new engine; grey X is the universal "no asset yet" state.
- Animation vocabulary extensible per category (buildings:
  idle/attack/death/hurt/place/upgrade; enemies: idle/walk/attack/death;
  UI/VFX as needed).

## 4. Data (`data/`)

- **JSON is the only value store** — the prototype's py+json dual system is
  dead. Python is loader code only. Every file type has a JSON Schema in
  `data/schemas/`; editor and agents validate on write; game validates on load
  (fail loud in dev).
- `data/balancing/` — per-domain balancing files, carrying the `_lock` field
  for the branch+lock protocol.
- `data/maps/` — any number of map files (tile grid, zone rings, spawn points,
  base position) + an `active_map` pointer the game reads; the editor has a
  selector for which map is live.
- `data/sprites/` — imported sheets + `asset_manifest.json`.

## 5. Editor (PySide6)

One window, docked panels, everything **selection-driven**:

- **Selector panel** (tree): Map(s), Buildings (type→tier→level), Enemies, UI,
  VFX. Selecting a node drives the other panels. Assigned-asset markers (●).
- **Viewport panel** (embedded engine render surface):
  - Map selected → **tilemap editor** (Godot-style): tile palette + paint /
    erase / line / rect / bucket / picker tools; layers with visibility
    toggles (terrain, zone tint, base, deco-above-entities); spawning is a
    painted zone, base is the single draggable map object; right-drag pan,
    cursor-centered zoom, ghost preview; global Ctrl+Z/Y undo;
    create/duplicate/save maps; set active map. No autotiling.
  - Entity selected → **entity preview**: renders it via the real engine
    pipeline in idle animation, dropdown to preview any authored animation,
    range-radius overlay. Grey X if no asset.
- **Balancing panel** (below viewport): auto-generated form from the selected
  object's schema — spinboxes/sliders/dropdowns with validation; writes to
  `data/balancing/`. Respects domain locks (locked → read-only + owner shown).
- **Asset import** (contextual on selection): full parity with the prototype
  importer — import sheet PNG, per-row animation/fps/hidden/loop editors,
  offset nudge, animated preview, clear-to-placeholder — writing manifest v2.
- **Run controls**: **Play** = subprocess `py game/main.py` · **Build** = run
  PyInstaller · **Playbuild** = launch built exe. Editor stays open; data is
  saved before launch.
- **Spawnclaude**: pick a domain (or "small tweak / no lock") → editor sets the
  lock, opens a terminal running `claude` in the repo with the domain
  pre-locked. Locked domains greyed out. `/merge-domain` remains the only
  unlock.
- **Access limitations**: lock display/enforcement in-editor now; further ideas
  slot in later without structural change (the lock system is the single
  enforcement point).

## 6. Build order

Each phase ends runnable. Per the project's TDD workflow: every phase starts
with an acceptance checklist and a runnable test, then implementation iterates
until green.

| Phase | Deliverable | Proof it works | Status |
|---|---|---|---|
| 0 | Repo bootstrap: gitignore, skeleton, CLAUDE.mds, PLAN.md, SPEC.md | tree matches plan; docs in place | in progress |
| 1 | `engine/coords` + render pipeline + asset placeholder | headless test: world↔screen round-trips; grey-X grid renders to offscreen surface | done — `py -m unittest discover -s tools/tests -t .` (28 tests); visual check `py tools/render_demo.py` |
| 2 | GameObject/Component/Scene (`SpriteAnimator` + `Health` only) + `game/main.py` window host + minimal `tools/smoke.py` (T-2) | scrolling iso map of grey-X tiles in a pygame window; smoke test prints OK | done — `py -m unittest discover -s tools/tests -t .` (58 tests); `py tools/smoke.py` OK; live window ~60fps |
| 3 | **Qt viewport spike** — engine surface inside PySide6 at 60fps | same grid inside the editor window *(riskiest integration — done early on purpose)* | done — `py -m unittest discover -s tools/tests -t .` (63 tests); `py tools/smoke.py` OK; live `py editor/main.py` window ~62.5fps at 1280x720 (QImage-copy fallback, ~9ms/frame) |
| 4 | Data schemas + selector panel + balancing panel | edit a value in editor → validated JSON on disk → game subprocess loads it | done — `py -m unittest discover -s tools/tests -t .` (85 tests); `py tools/smoke.py` OK (7 data files); live QTest-driven editor edit landed canonical JSON on disk; windowed game subprocess ran clean on the new data; all five D-10 domains authored (map.json placeholder until phase 6) |
| 5 | Asset system v2 + import panel + entity preview | import a sheet for one building, preview animations in editor, see it in game | done — `py -m unittest discover -s tools/tests -t .` (191 tests); `py tools/smoke.py` OK (9 data files); prototype art migrated (14 sheets + manifest v2 committed); live windowed editor ~57fps: Defender → stone-thrower idle/attack preview, sheet imported for Painter, saved → preview + ● updated without restart, cleared → grey X; live windowed game 60fps: migrated sprites animate on two dummies, third stays grey-X |
| 6 | Map format + tilemap editor + active-map selector | paint a map, save, Play launches game on it | done — `py -m unittest discover -s tools/tests -t .` (260 tests); `py tools/smoke.py` OK (11 data files); live windowed QTest run ~57–62fps: opened the starter map, created a map, painted b/c/s with brush + rect + bucket, toggled tint eye + grid lines, dragged the base, placed a deco, Ctrl+Z/Y, saved, set active, reopened with edits intact; windowed game subprocess 60fps on the painted map; committed starter map `data/maps/first_light.json` (prototype-exact initial layout) + `active_map.json` |
| 7 | Run controls (Play/Build/Playbuild) | all three buttons work end-to-end | — |
| 8 | Spawnclaude + locks + `.claude/` commands ported | dispatch a locked-domain agent from the editor | — |
| 9+ | `engine/physics` (E-30..E-32) + `Movement`/`RangeSensor` components first, then port gameplay domain-by-domain (map → buildings → enemies → core phases → ui), prototype repo as spec | each domain: acceptance checklist → test → implement → live playtest | — |

## 7. Risks / open items

- **Qt + pygame embed** is the one integration with real unknowns → phase 3
  spike, immediately after the engine can render at all. Fallback exists
  (render to QImage) but costs a frame copy.
- **Access limitations**: more ideas pending from the designer; architecture
  keeps locks as the single enforcement point so additions don't restructure
  anything.
- **Manifest migration**: the prototype's imported sheets +
  `sprite_manifest.json` convert to manifest v2 via a one-off script during
  phase 5 — existing art carries over.
