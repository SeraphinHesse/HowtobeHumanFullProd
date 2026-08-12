---
description: Use when the task is to add or create a new VFX effect for a specific building or enemy, driven by a text description of the visual. Wires a per-type trigger, a tuned procedural effect (or new emitter family), and a placeholder sprite slot for later art.
argument-hint: <building/enemy type + moment + visual, e.g. "Storm Priest, on attack: a crackling purple arc">
allowed-tools: Read, Edit, Write, Grep, Glob, Bash(git rev-parse*), Bash(git switch*), Bash(git status*), Bash(py tools/smoke.py*), Bash(py tools/testgate.py*), Bash(py -m pytest*)
---

Add a VFX effect: **$ARGUMENTS**. Unlike a sprite import, there is **no
image-generation tool anywhere in this repo** (`/replace-visual` documents
this: "no `sprite_gen` / procedural fallback"), so the prompt is realized as
tuned NUMBERS feeding `engine/vfx/`'s existing procedural emitters — colour,
particle shape, velocity, life — not as generated pixel art. A placeholder
`vfx_*` sprite slot is also scaffolded so a human artist can later import
real art that overrides the procedural effect (E-37).

## Branch logic
1. `git rev-parse --abbrev-ref HEAD`.
2. On `Development`/`main`: create a short-lived feature branch first (`git
   switch -c feature/vfx-<slug>`) — never edit these files in place on a base
   branch. If invoked through `/dispatch`, its own git setup already did
   this — check `git status` before re-branching.
3. Otherwise (already on a feature/dispatch branch) continue in place.

## Read first (token-light)
1. `engine/CLAUDE.md`'s `engine/vfx/` row (no subsystem doc of its own — that
   router table IS the doc) — the procedural emitters, `VfxParams`, no
   defaults on any dataclass field (G-7), no game vocabulary in the engine
   (D5).
2. `data/CLAUDE.md`'s vfx balancing-domain entry + `data/balancing/vfx.json`
   + `data/schemas/vfx.schema.json` — the `procedural.*` families and the
   existing 10-key `triggers` object's shape (closed enum both on the event
   key and the row's own `sprite_slot`/`procedural` sub-enums).
3. `game/ui/effects.py`'s `_play`/`_run_procedural`/`_triggers_from_balance`
   (search the ESV-5/ESV-6 docstrings) — the ONE dispatch seam every trigger
   event goes through, and its call sites: `watch_buildings`,
   `watch_enemies`, `spawn_building_vfx`, `spawn_death_events`,
   `spawn_splash_impact_events`, `spawn_projectile_hit_events`,
   `spawn_defender_fire_events`.
4. `editor/CLAUDE.md`'s "VFX preview" section + `editor/panels/
   vfx_preview.py` — the family combo is DATA-DRIVEN off the keys under
   `procedural` (a new family shows up for free), but `_EMIT_FAMILIES`/
   `_LEVERS`/`_RAMP_KEY` are hardcoded tuples a brand-new dataclass family
   needs an entry in to get a real live preview instead of a placeholder.
5. `data/schemas/cutscenes.schema.json` — this repo's one precedent for an
   OPEN, designer-growable registry (`additionalProperties: {$ref: ...}`),
   the shape to copy for a new per-type trigger table rather than adding
   one more closed key.

## Steps
1. Parse **$ARGUMENTS**: the target building/enemy **type**, the trigger
   **moment** (attack / place / death / hit / tier-up / … — a new event name
   is fine if none of the 10 existing global ones fit), and the free-text
   visual description.
2. **Reuse an existing procedural shape before inventing one.** Match the
   description against what's already there: `spark` = a burst, `slash` =
   radial lines, `muzzle` = a spray, `splatter` = a ground blob, `beam` = a
   continuous line, `crater`/the lightning marker = a fading ring,
   `gold_highlight` = a fading diamond, `drummer_aura` = a pulsing ring.
   - **Same shape, new tuning** → add a new NAMED PRESET the way
     `spark.presets.{place,level1,level2,tier}` already shares one dataclass
     across several tuned instances, or a new sibling family under
     `procedural.*` with its own params.
   - **Nothing fits** → only then add a new frozen dataclass to
     `engine/vfx/params.py` (NO defaults — G-7), an `emit_*` function in
     `engine/vfx/emitters.py` (an INJECTED rng, never bare `random`), wire it
     into `VfxSystem` (`engine/vfx/system.py`), and add its `$defs` block +
     `procedural.<name>` schema entry in `vfx.schema.json` with a per-key
     `description` + `minimum`/`maximum` (D-12). Register the family in
     `vfx_preview.py`'s `_EMIT_FAMILIES`/`_LEVERS`/`_RAMP_KEY` so it previews
     live instead of degrading to a placeholder.
3. **Per-type trigger binding.** If `vfx.schema.json` has no
   `triggers_by_type` object yet, add ONE new sibling of the existing
   `triggers` object, OPEN rather than closed — `{"type": "object",
   "additionalProperties": {"type": "object", "additionalProperties":
   {"$ref": "#/$defs/trigger_row"}}}` (the `cutscenes.schema.json`
   precedent) — so a designer can add the next building's/enemy's VFX by
   DATA alone from here on; never add another hand-typed key to the flat
   `triggers` object instead. If `triggers_by_type` already exists (a later
   run of this skill), just add this type's row. Mirror the content into
   `data/balancing/vfx.json`: `triggers_by_type.<type>.<event> =
   {sprite_slot, procedural}`.
4. **Dispatch wiring** in `game/ui/effects.py`. If it doesn't exist yet, add
   `_play_typed(self, event, type_key, wx, wy, **kw)`: resolve
   `triggers_by_type` the same flattening `_triggers_from_balance` already
   does for `triggers`, look up `(type_key, event)` first, and fall back to
   the existing `self._play(event, wx, wy, **kw)` when no override exists —
   so every type without one keeps its exact current behavior (E-37/
   back-compat). Repoint the ONE matching call site to pass the type key
   through and call `_play_typed` instead of `_play`: `watch_buildings`
   already carries `b.building_type`, `watch_enemies` already carries
   `etype = getattr(e, "ETYPE", ...)`; the other drains
   (`spawn_building_vfx`/death/splash/projectile-hit/defender-fire) do NOT
   carry a type today and need one threaded through from their own caller if
   the event you're adding needs one.
5. **Sprite slot scaffold** — add a new key to `data/slots.json`'s `vfx`
   category, "Effects" group (64×64, inherits the category default), grey-X
   until imported; wire it as this trigger row's `sprite_slot` so
   `engine.vfx.spawn_play_once` picks it up the moment a human artist
   imports real art (E-37 — never required for the procedural effect to
   work today).
6. Never hand-format any touched JSON — every write goes through
   `engine.data_io.write_validated` / the editor's own writers.

## Avoid
- Adding a new CLOSED key to the flat `triggers` object for a per-type
  event — use the open `triggers_by_type` registry (step 3) instead.
- Branching on a building/enemy type STRING inside `engine/vfx/` — that is
  game vocabulary and belongs only in `game/ui/effects.py` (D5 layering).
- Reinventing an emitter shape that already exists — a new dataclass is a
  last resort, not the default (step 2).
- Skipping the branch-first check, even for one small preset addition — see
  Branch logic above.
- Leaving a new family unregistered in `vfx_preview.py` — it still works
  (E-37 degrades to a placeholder), but the whole point is a designer being
  able to see and tune it there.

## Verify
- `py tools/smoke.py` — schema + manifest validation.
- `py -m pytest tools/tests/test_vfx.py -x -q` (targeted; the full
  `testgate` runs once at handoff, per CLAUDE.md's Test Suite Policy).
- Live: `py editor/main.py` — select the `vfx` domain, confirm the new
  family/preset appears and previews (particle burst + lever strip if
  registered, else the generic recursive tree); if a building/enemy of the
  target type exists on the active map, a live `py game/main.py` round
  exercising the new trigger moment.

## Final report
- Changed files; whether an existing family was reused or a new one added;
  the new trigger key (`triggers_by_type.<type>.<event>`); the new `vfx_*`
  slot; verification performed; whether `engine/CLAUDE.md` / `data/
  CLAUDE.md` / `editor/CLAUDE.md` needed a durable update (the FIRST
  invocation of this skill adds the `triggers_by_type` registry itself —
  an architectural addition worth a doc update; later invocations are just
  data and don't).
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
