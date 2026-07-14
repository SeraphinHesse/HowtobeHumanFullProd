---
description: Use when the task is to add a new slot-registry CATEGORY to data/slots.json — optionally a full balancing domain — and update every place that hardcodes the domain/category list.
argument-hint: <category key + display name, e.g. "projectiles (Projectiles), asset-only, 64x64">
allowed-tools: Read, Edit, Write, Grep, Glob, Bash(py tools/smoke.py*), Bash(py tools/testgate.py*), Bash(py -m pytest*), Bash(py -c *)
---

Add a new registry category: **$ARGUMENTS**. A *category* is a top-level node of
`data/slots.json` (the editor tree's top level). It is a **balancing domain** when it
also has `data/balancing/<key>.json` + `data/schemas/<key>.schema.json` — the editor
DERIVES that set (`editor/domains.py::domains()`), so no editor edit is ever needed
here. Adding a GROUP/variant inside an existing category is NOT this skill: use the
editor's `+ Variant` / `+ Type` buttons or `/add-asset-importer`. Wiring the import
path for the new category's art is `/add-asset-importer`'s job — this skill stops at
data + the checklist and hands off.

## Read first (token-light)
1. `data/CLAUDE.md` — slots.json shape (`categories[]`, `key`/`display_name`/`frame_w`/
   `frame_h`/`animations`/`groups`, `animations[0] == "idle"`), balancing-file
   shape (D-10), schema house style (D-3/D-12: every property `description`d, every
   numeric bounded, `additionalProperties: false`, all keys `required`).
2. `editor/panels/CLAUDE.md` — how the selector builds top-level nodes from the
   registry and how `editor/domains.py::domains()` derives the balancing domains.

## Steps
1. **slots.json** — append the category to `data/slots.json`'s `categories[]` (order IS
   the editor tree order; balancing domains conventionally come before the asset-only
   ones). Give it at least one leaf group with one slot key (`^[a-z][a-z0-9_]*$`), the
   frame size, and the `animations` vocabulary starting with `idle`. Write it via
   `engine.data_io.write_validated` against `data/schemas/slots.schema.json` — never
   hand-format. A slot key may NOT repeat across categories (the loader raises).
   `data/schemas/slots.schema.json` needs a change ONLY if you introduce a new
   category-level *field* — a plain new category needs none.
2. **Balancing domain (only when the payload's `is_balancing_domain` is true)** — create
   BOTH:
   - `data/balancing/<key>.json` with at least one real tunable (an empty domain
     renders an empty form).
   - `data/schemas/<key>.schema.json` — house style: `$id`, draft 2020-12,
     `additionalProperties: false`, every key `required`, a `description` on every
     property, `minimum`/`maximum` on every numeric (ED-30). No cross-file `$ref`
     (`engine.data_io` uses a plain `jsonschema.validate`).

   `tools/smoke.py` stem-pairs `data/balancing/<key>.json` ↔
   `data/schemas/<key>.schema.json` automatically — no smoke change.
3. **Walk the hardcoding checklist — every site, explicitly.** Grep first:
   `grep -rn "buildings.*enemies.*map.*ui.*core" --exclude-dir=.git --exclude-dir=.claude/worktrees .`

   | # | Site | Action |
   |---|------|--------|
   | 1 | `tools/tests/test_assets_registry.py::TestRealRegistry.test_category_order_is_domain_order_plus_asset_only` | **ALWAYS** (asset-only categories too). It asserts the literal category tuple; add your key in slots.json order or the suite goes red. |
   | 2 | `game/core/balance.py::DOMAINS` (re-exported by `game/core/__init__.py`) | **Balancing domains only.** `load_all()` iterates it — without this the game never loads your domain. |
   | 3 | `tools/tests/test_balancing_data.py::DOMAINS` (~L22) | **Balancing domains only.** Adds the D-3/D-11/D-12 acceptance walk to your new domain. |
   | 4 | `tools/tests/test_balancing_parity.py::DOMAINS` (~L23) | **Inspect; usually NO change.** It is a frozen prototype↔repo migration gate; a brand-new domain has no prototype counterpart. Touch it only if a `balancing_parity_map.json` entry resolves into your domain. |
   | 5 | `.claude/commands/add-balancing-value.md` (frontmatter `description` + body ~L9) and `.claude/commands/processtodo.md` (~L20) | **Balancing domains only.** Domain enumerations in prose — extend them. |
   | 6 | Docs/prose: root `CLAUDE.md` (~L88 "five balancing domains"), `data/CLAUDE.md` (~L48 "All five domains exist"), `SPEC.md` (~L52 **Domain** glossary row), and `data/schemas/slots.schema.json` **twice** (~L91 `categories` "the first five keys mirror the balancing domains", ~L136 the category `key` description enumerating them) | **Balancing domains only.** Prose that says "the five domains" — keep it true. A new ASSET-ONLY category still shifts what "the first five" means only if you insert it *before* `core`: append it after the domains and these stay correct. |
   | — | `editor/domains.py` | **NOTHING TO DO.** `domains(data_dir)` derives the list from slots.json ∩ `data/balancing/*.json` (AD-6). The selector + balancing panel pick your domain up with zero editor edits. |
4. **Art** — every new slot renders as a grey X until a sheet is imported (E-37). Point
   the user at `/add-asset-importer` (import path) or `/replace-visual`.

## Avoid
- Hand-formatting any `data/` JSON (D-3 — use `write_validated` / `dumps_deterministic`).
- Reusing a slot key from another category (the registry loader raises).
- Cross-file `$ref` in the new schema, or `allOf` composition (it breaks
  `additionalProperties: false`).
- Editing `editor/domains.py` to "register" the domain — it is derived.

## Verify
- `py tools/smoke.py` — slots.json + the new balancing file validate.
- `py tools/testgate.py check` — zero new failures (item 1 of the
  checklist is the one that bites).
- Live: `py editor/main.py` → the new category is a top-level tree node; a balancing
  domain also shows its form. State exactly what you ran.

## Final report
Changed files; the new category key + whether it is a balancing domain; which checklist
items applied; verification performed; whether `data/CLAUDE.md` needed a durable update.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
