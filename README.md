# How To Be Human — Full Production

Isometric tower defence: spend *love* to unlock tiles and place musicians and
defenders that protect "the hole" from enemy waves.

Full-production rebuild of the [ClaudePrototype](../HowToBeHuman) as three
cleanly separated parts:

- **`engine/`** — a pseudo-engine that carries exactly this game's workload
  (coordinates, game objects, render pipeline, simple physics, assets).
- **`game/`** — How To Be Human itself, built on the engine.
- **`editor/`** — the central PySide6 editor: balancing, map design, asset
  importing, play/build controls, and Claude agent dispatch.

Start here:

- [`PLAN.md`](PLAN.md) — the rebuild plan and phased build order.
- [`SPEC.md`](SPEC.md) — the full project specification.
- [`CLAUDE.md`](CLAUDE.md) — router for agents working in this repo.

Setup: `pip install -r requirements.txt` (Python 3.11+).
Nothing is runnable yet — see PLAN.md phase status.
