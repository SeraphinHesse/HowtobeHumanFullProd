---
description: Use when the task is to add a new engine Component. Produces declared JSON-safe fields, on_added seam, auto-registration, keeping the module pure per the engine/core conventions.
argument-hint: <component name + what state it holds>
allowed-tools: Read, Edit, Write, Grep, Glob, Bash(py -m unittest*), Bash(py tools/smoke.py*)
---

Add an engine component: **$ARGUMENTS**. Components are what the editor sees and the
serializer persists — **all authoritative gameplay state lives in declared component
fields** (E-11/E-15). This is an `engine/` task; if a caller in `game/` must change,
that's a cross-package task — tell the user.

## Read first (token-light)
1. `engine/core/CLAUDE.md` — component field rules, serialization, the `on_added`
   owner seam, spatial queries.
2. The closest existing component (`Movement`/`RangeSensor` in `engine/core/`,
   `Health`/`SpriteAnimator`) — copy its shape.

## Steps
1. **Declare fields** as class-level annotations with defaults (`speed: float =
   0.0`). `Component.__init_subclass__` collects them into `cls._fields`, so only
   JSON-safe types are allowed (bool/int/float/str/list/dict) — a non-JSON default is
   rejected at class-creation. This is also what auto-registers the class by name for
   `component_from_dict` (no manual registry edit).
2. **Owner access** — if the component needs its owner's transform, override
   `on_added(self, owner)` and cache `self._owner = owner` (underscore transient; the
   E-11 setattr guard is on GameObject, not Component). Never store authoritative
   state on `self` outside a declared field.
3. **Behavior** — put per-frame logic in `update(dt)`; a visual component defines
   `render_items(transform) -> iterable[RenderItem]` (pure data — `engine.core` may
   import `engine.render.item` but NOT pygame).
4. **Stay pure** — no pygame in `engine/core`/`engine/physics` (respect the router's
   import allow-list). If it wraps a physics primitive, put the primitive in
   `engine/physics/` and the component in `engine/core/`, like `Movement`.
5. **Purity/serialization tests** — add the component to whatever `TestPurity` /
   serialization round-trip test covers `engine/core`.

## Avoid
- Authoritative state as a plain instance attribute (breaks inspector + save/load).
- Game vocabulary in the engine (no "raider", no "flute_player") — those live in
  `game/`.

## Verify
- `py -m unittest discover -s tools/tests -t .` — field collection, serialization
  round-trip, and the component's own behavior test.
- `py tools/smoke.py` if anything render/asset-facing.

## Final report
- Changed files; the component's fields; verification performed; whether
  `engine/core/CLAUDE.md` needed a durable-rule update.
