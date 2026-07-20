# CLAUDE.md — ENGINE package (router)

Self-contained guide for `engine/` — the pseudo-engine that carries exactly this
game's workload. You reached here from the root router. Requirements: SPEC.md §4
(`E-*`).

This doc is a **router**: it holds the cross-cutting rules + the conventions for
the top-level `engine/*.py` files, and points to one **subsystem doc per
subfolder**. Those `<subfolder>/CLAUDE.md` files auto-load when you edit inside
them. **When you change a subsystem's architecture, update THAT subsystem's doc**
(not this router, not another package's doc); change a top-level module or a
cross-cutting rule → update this file.

**Adding a new engine Component? Use the `/add-engine-component` skill** — it
encodes the JSON-safe-fields + `on_added` seam + auto-registration + module-purity
pattern; don't hand-roll it.

## File scope you may edit
`engine/**` and engine-focused tests. Never edit `game/**` or `editor/**` from an
engine task; if an engine change forces a caller change, tell the user
(cross-package task).

## Subsystem docs (read the ONE that matches your task)
| Subfolder | Doc | Owns |
|---|---|---|
| `coords/` | `engine/coords/CLAUDE.md` | THE coord authority (E-1..E-5); iso math lives ONLY here; windowed tile culling |
| `core/` | `engine/core/CLAUDE.md` | GameObject/Component/Transform/Scene; serialization; `Movement`/`RangeSensor`; spatial queries |
| `render/` | `engine/render/CLAUDE.md` | RenderItem→depth-sort→blit; backend throughput; HUD pass + fonts; the ground cache |
| `physics/` | `engine/physics/CLAUDE.md` | SpatialGrid, TileOccupancy, waypoint `advance` (E-30..E-32) |
| `assets/` | `engine/assets/CLAUDE.md` | slot registry, manifest v2, `playback_order`, grey-X placeholder |
| `vfx/` | none yet (this table is its doc) | procedural particle/gold/slash/splatter emitters + `VfxSystem` (ESV-3a); beam/crater/lightning/announce param dataclasses (ESV-3b, no engine-side state — see below) |

## Top-level modules (`engine/*.py`) — this router IS their doc
- **`tilemap.py`** (pure — no pygame, no Qt) is the ONE authority for the D-20 map
  file format, shared by game and editor (they may not import each other;
  user-approved scope addition). `TileMapDoc` + `load_map`/`save_map` (schema via
  data_io PLUS fail-loud ValueError cross-checks the schema can't express: row
  counts/lengths vs dims, bounds, id == filename stem). NO game vocabulary: terrain
  cells are single chars resolved through the map file's own schema-pinned `legend`
  (`defaults_from_schema` digs the canonical legend/base slot out of
  `map_file.schema.json`'s consts — schemas over convention). `TileMapDoc` also
  carries the nullable single-object markers `camera_start` and `start_area`
  (the 2×2 starting area's min corner; bounds cross-checked in `validate_doc`);
  **the emitters deliberately never render `start_area`** — the game doesn't
  draw it and the editor draws a pure 2×2 outline via `submit_overlay_lines`.
  - **Checkerboard parity is PROTOTYPE-EXACT** (src/map/tile.py):
    `slot_for_code`/`slot_for_cell` append `_b` iff the legend entry has `checker:
    true` AND `(col + row + 1) % 2 == 1` (col+row even). Background kinds never
    alternate. Pinned in `test_tilemap_model`.
  - **Three emitters** — pick by need:
    - `render_items(doc, *, terrain/base/deco, tint_for_code)` emits the WHOLE map
      (ground tiles w/ optional per-code tint, base on `entities`, deco on `deco`
      above entities per E-26). Kept for tests / small full-map consumers.
    - `visible_render_items(doc, col_min, col_max, row_min, row_max, …)` — the
      **windowed** variant (same output for covered cells, clamped to the map;
      base/deco gated by a `tall_margin`). Pair with
      `CoordinateSystem.visible_tile_window` so game AND editor viewports only
      generate on-screen tiles — the reason a 1024² map stays at full fps.
    - `band_render_items(doc, d_min, d_max, s_min, s_max, …)` — ground only,
      addressed by rotated iso coords `d = col−row`, `s = col+row`, for a thin
      diagonal on-screen strip (the ground cache's scroll-fill; a rectangular
      window for such a strip balloons to the whole viewport). See
      `engine/render/CLAUDE.md` "Ground layer cache". Optional
      `code_overrides={(col,row): code}` consults the caller's RUNTIME zone
      state before `doc.terrain` (the game's unlock/recede visuals) so the doc
      stays pristine; overrides resolve through the same legend/checker rule.
- **`data_io.py`** — the schema-validating JSON load/write (pure Python; used by
  coords to load geometry, by the editor/agents to write). Deterministic dumps:
  sorted keys, 2-space indent, trailing newline (D-3).
- **`audio.py`** — thin `pygame.mixer.music` wrapper
  (`play_music`/`stop_music`/`set_volume`). Every call **swallows ALL exceptions**
  → silent no-op when audio is unavailable (no device, missing file, mixer not
  initialised, SDL dummy). No game vocabulary; the caller passes the path.
- **`video.py`** — OpenCV `VideoSource(path, length, target_size=None)` for the
  cutscene. cv2 is imported LAZILY; **graceful skip** (`enabled=False`,
  `done=True` immediately) if cv2 is absent, the file is missing, or the capture
  won't open — never crashes, never hangs, headless-safe. Timing delegates to the
  pure `video_playback` clock. `update(dt)` advances + reads one frame;
  `frame_surface()` does BGR→RGB → optional resize →
  `pygame.surfarray.make_surface`; `skip()`/`release()` free the capture.
  opencv-python is OPTIONAL (absent = cutscene skips); `tools/build.py` bundles it
  for the frozen exe (`--collect-all cv2` `--hidden-import cv2`).
- **`video_playback.py`** — pure clock/state machine
  (`VideoPlayback(length, enabled=True)`) the cv2 source composes for timing:
  `advance(dt)` accumulates and marks `done` at the `length` cap;
  `finish/skip/mark_source_ended` all end it; `enabled=False` starts `done`.
  `length` is a constructor param (engine stays game-agnostic; the prototype's
  44.2 s cap is a caller concern).

## `engine/vfx/` (ESV-3a) — procedural VFX emitters
Pure Python, no doc of its own yet (this row is it). `params.py` holds frozen
dataclasses with NO defaults (one per `data/balancing/vfx.json` `procedural.*`
table — a default here would be a second home for a value that belongs in
`data/`, G-7); `particle.py` holds the stateful `Particle`/`GoldHighlight`/
`Slash` objects; `emitters.py` holds pure `emit_*(rng, ...)` functions —
**every emitter takes an injected `rng`** (`random.Random`-compatible), never
the stdlib `random` module directly, so seeded-RNG parity tests are possible;
`system.py`'s `VfxSystem` owns the particle/gold/slash/splatter lists,
`update(dt)`, and two submit surfaces (world-overlay vs HUD — the host
interleaves them at different points in the frame, so one submit method would
reorder the draw). `game/ui/effects.py`'s `_params_from_balance` is the ONE
place a `data/balancing/vfx.json` key name and an `engine.vfx` dataclass field
meet — this package never imports a balancing loader, never calls `open()`,
never learns a JSON key name (D5's top risk here: don't add a convenience
`load_defaults()` helper, it would smuggle the loader back in).

**ESV-3b** added four more frozen dataclasses to `params.py` — `BeamParams` /
`CraterParams` / `LightningParams` / `AnnounceParams` (Sun Scorcher beam,
mortar crater, lightning bolt/flash/marker, boss announce). Unlike the
ESV-3a five, `VfxSystem` owns **none** of their state: the scene already owns
the crater/lightning fade clocks (`CraterFade`/`LightningFXFade` components in
`game/enemies/combat.py`/`game/core/lightning.py`), so a parallel engine-side
list would be a second source of truth for the same fade. `game/ui/effects.py`
holds these four straight off its `VfxParams` bundle (`self._vfx_params`) and
draws them itself (`submit_beams`/`submit_craters`/`submit_lightning`/
`submit_announce` stay in `game/ui/` — they read `scene.by_tag(...)` and
building components, game vocabulary the engine must not learn). The two
cosmetic fade lifetimes NOT captured in these dataclasses (`crater.life`,
`lightning.bolt_life`/`marker_life`) are threaded as required constructor
arguments all the way from `resolve_combat`'s/`lightning.strike`'s
`vfx_balance` argument down to the `CraterFade`/`LightningFXFade` component
fields that actually own the despawn clock — never a `None`-defaulted
optional (G-7).

## Hard rules (whole package)
- **pygame imports are allowed ONLY in** `render/`'s backend, `render/fonts.py`,
  `render/ground_cache.py`, the asset surface cache (`assets/store.py`,
  `assets/placeholder.py`), `engine/audio.py`, and `engine/video.py`. `coords/`,
  `core/`, `physics/`, `tilemap.py`, `data_io.py`, `video_playback.py`, and asset
  *metadata* code are pure Python — that is what keeps game logic
  headless-testable.
- Rendering never raises on a missing asset (grey X instead).
- No game-specific names in the engine (no "raider", no "flute_player") — those
  belong in `game/` and `data/`.

## Conventions shared across subsystems
- **Tests** live in `tools/tests/` — still `unittest.TestCase`, but **run by
  pytest** (`pytest` + `pytest-xdist` are declared deps; pytest collects
  TestCase natively, so nothing was rewritten). From the repo root:
  `py tools/testgate.py check`, or `py -m pytest -m core` for the fast tier.
  SDL dummy drivers are set in-code, so no env setup is needed.
- **Every new test module needs a tier** in `conftest.py`'s `TIERS` table.
  `test_tiers.py` fails if you forget — an unmarked module would silently never
  run under a marker-selected gate.

## Verify before finishing
- Pure-logic changes: run/extend the unit tests (coords round-trip,
  playback_order, grid queries) — T-3. `py tools/testgate.py check --affected`
  runs just the blast radius while you iterate.
- Anything render/asset facing: run the headless smoke test (`tools/smoke.py`)
  and, if visuals changed, a live `py game/main.py` look. State exactly which you
  did.
- **The gate is ZERO failures** (`GATE PASS`). No baseline, no tolerated
  failures.
