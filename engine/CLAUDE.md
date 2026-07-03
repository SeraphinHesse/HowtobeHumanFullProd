# CLAUDE.md — ENGINE package

Self-contained guide for `engine/` — the pseudo-engine that carries exactly
this game's workload. You reached here from the root router. Requirements:
SPEC.md §4 (`E-*`). **When you change engine architecture/conventions, update
THIS doc** (not the router, not another package's doc).

## File scope you may edit
`engine/**` and engine-focused tests. Never edit `game/**` or `editor/**` from
an engine task; if an engine change forces a caller change, tell the user
(cross-package task).

## Module map
- `coords/` — THE coordinate authority (E-1..E-5). `world_to_screen`,
  `screen_to_world` (exact inverse), iso depth key, camera state. **No other
  module in the repo may do iso math.** Geometry constants come from `data/`,
  never hardcoded.
- `core/` — `GameObject`, `Component`, `Transform`, `Scene`, frame order
  (E-10..E-15). Rule: **components are what the editor sees; subclasses are
  behavior convenience.** All gameplay state lives in declared component
  fields — that is what makes serialization (E-15) and the editor inspector
  work. Never add authoritative state as a plain subclass attribute.
- `render/` — RenderItem submit → resolve frames via assets → depth sort →
  coords → blit (E-20..E-25). Target-agnostic: game window and editor
  viewport use the SAME pipeline. Overlay pass for range circles / highlights.
- `physics/` — waypoint movement, spatial grid (radius + Chebyshev queries),
  tile occupancy (E-30..E-32). Deliberately simple; do not grow forces or
  collision response without the user asking.
- `assets/` — data-driven slot registry, manifest v2 loader, `playback_order`
  row semantics (rows = animations, row 0 = idle), grey-X placeholder
  (E-33..E-38). Missing/corrupt art logs and falls back — never crashes boot.

## Hard rules
- **pygame imports are allowed ONLY in** `render/`'s backend and the asset
  surface cache. `coords/`, `core/`, `physics/`, and asset *metadata* code are
  pure Python — that is what keeps game logic headless-testable.
- Rendering never raises on a missing asset (grey X instead).
- No game-specific names in the engine (no "raider", no "flute_player") —
  those belong in `game/` and `data/`.

## Verify before finishing
- Pure-logic changes: run/extend the unit tests (coords round-trip,
  playback_order, grid queries) — T-3.
- Anything render/asset facing: run the headless smoke test (`tools/smoke.py`)
  and, if visuals changed, a live `py game/main.py` look. State exactly which
  you did.
