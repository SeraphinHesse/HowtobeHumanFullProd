# CLAUDE.md — GAME package

Self-contained guide for `game/` — How To Be Human itself, built on `engine/`.
You reached here from the root router. Requirements: SPEC.md §6 (`G-*`).
Behavior source: the prototype repo
(`../HowToBeHuman/ClaudePrototype/HowToBeHuman`) — what the prototype does is
the required behavior unless SPEC.md says otherwise. **When you change game
architecture/conventions, update THIS doc.**

## File scope you may edit
`game/**` and `data/balancing/*` (lock rules apply — check `_lock` first).
Never import or edit `editor/**`. Engine changes are a cross-package task —
tell the user.

## Layout & domains
- `main.py` — the ONLY entry point (`py game/main.py`): pygame window, engine
  loop, input routing.
- `map/` · `buildings/` · `enemies/` · `core/` · `ui/` — these mirror the
  prototype's five balancing domains, which still scope branches and locks
  (`/start-domain buildings` etc.).

## Host conventions (`main.py`, Phase 2)
- `main(max_frames=None)` is importable so `tools/smoke.py` can drive the
  same code headlessly (G-8); `py game/main.py` runs it windowed.
- Frame order is fixed per E-14: input → `Scene.update(dt)` →
  render submit (grid tiles + `scene.render_items()`) → `flush` → `flip`.
- **Camera input mapping (E-5) lives here**, on pure engine camera state:
  right-click-drag pans (`cs.pan` + `cs.clamp` to map bounds); scroll
  wheel steps through the data-driven `geometry.json` zoom levels, keeping
  the viewport-centre world point fixed via `screen_to_world`/
  `world_to_screen` only (no iso math in the host); Esc quits.
- Window size / fps / caption come from `data/display.json`
  (schema-validated, G-7) — never hardcode them.

## Conventions
- Game classes subclass `GameObject` but keep ALL state in components (engine
  rule) — the editor's inspector and save/load depend on it.
- No pygame calls in gameplay logic; visuals are submitted as RenderItems via
  `SpriteAnimator`. HUD/menus may use the direct HUD layer (G-6).
- Every tunable comes from `data/balancing/` at startup (G-7). If you need a
  new constant, add it to the domain's JSON + schema — never hardcode.
  ×10 combat HP/DMG scale applies; `BASE_HP` stays 10.
- Combat-capable buildings advertise capability via components/tags (the
  prototype's `IS_COMBAT` contract) — core sweeps must stay type-agnostic.
- Phase machine + income ordering (snapshot → income → upkeep → painters →
  revive → cleanup) is prototype-exact (G-5); do not reorder without the user.

## Porting protocol (PLAN phase 9+)
Port one domain at a time, prototype as spec: acceptance checklist → runnable
test → implement → iterate until green → live playtest. State what you
verified (smoke test vs live round vs static read).

## Verify before finishing
Headless smoke test (`tools/smoke.py`) after every change; live
`py game/main.py` round for phase/combat/UI behavior. If balance changed:
schema validation passes, lock respected.
