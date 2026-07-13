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

## Code graph (Graphify) — optional, recommended

A queryable knowledge graph of `engine/` · `game/` · `editor/` · `tools/`
(~5k symbols), built locally from tree-sitter ASTs — no LLM, no API key. Use it
to find where something lives and what it touches, instead of grepping:

```bash
graphify explain "place_building()"     # a symbol's callers/callees
graphify path "BaseBuilding" "TileMap"  # how two symbols connect
graphify affected "BaseBuilding"        # blast radius before a change
```

The graph itself (`graphify-out/`) is **generated and gitignored** — everyone
builds their own, so it always matches your checkout. First-time setup:

```bash
uv tool install git+https://github.com/Graphify-Labs/graphify.git
graphify hook install                      # rebuilds the graph on each commit
graphify extract . --code-only && graphify cluster-only . --no-label
```

Full agent-facing rules → [`CLAUDE.md`](CLAUDE.md) "Step 0".
