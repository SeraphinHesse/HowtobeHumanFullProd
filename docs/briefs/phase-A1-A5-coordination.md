> **SUPERSEDED — historical record.** This brief predates the ZERO-failure
> gate. Any "baseline", "N pre-existing failures", "no NEW failures vs
> Development" or `unittest discover` instruction below is DEAD: the suite is
> green, the gate is ZERO, and a red test is yours. Which tests you may run is
> role-scoped — §"Test Suite Policy" in the root `CLAUDE.md` is the only
> authority. Do not follow this file's verification section.

# Slice 10L-A (A1–A5) — orchestrator coordination

Reconciliation of the five phase briefs' §3 file scopes. **Binding.** Where this
file and a phase brief disagree, this file wins.

## Branch / wave layout

| Branch | Phases | Cut off | Runs |
|---|---|---|---|
| `phase-A1-A2-engine` | A1 then A2 (one coder) | umbrella | sub-wave 2a |
| `phase-A3-ui-slots` | A3 | umbrella | sub-wave 2a |
| `phase-A4-slice-editor` | A4 | umbrella **after 2a merges** | sub-wave 2b |
| `phase-A5-skinned-button` | A5 | umbrella **after 2a merges** | sub-wave 2b |

A1+A2 share a coder because both edit the HUD folding block of
`engine/render/renderer.py` (lines 137-148): A1 owns the
`assets.frame(slot_key, animation, anim_time_ms)` call, A2 owns `slice=` on the
`DrawCall` built in that same block. A1 lands green before A2 starts.

## File ownership (no file appears twice)

- **A1+A2** — `engine/render/{hud,renderer,item,backend}.py`,
  `engine/assets/{manifest,types,store}.py`,
  `data/schemas/asset_manifest.schema.json`;
  tests `test_hud_items.py` (A1), `test_render.py` / `test_asset_store.py` /
  `test_assets_manifest.py` / new `test_nine_slice.py` (A2);
  docs `engine/render/CLAUDE.md`, `engine/assets/CLAUDE.md`, `data/CLAUDE.md`.
- **A3** — `data/slots.json` (ui category only), `editor/main.py`
  (`_VARIANT_TARGETS` only); tests `test_assets_registry.py`,
  `test_registry_ops.py`.
- **A4** — `editor/panels/details.py`; tests `test_details_panel.py`,
  `test_editor_viewport.py`; doc `editor/panels/CLAUDE.md`.
- **A5** — `game/ui/**`, `game/main.py`; new test
  `tools/tests/test_button_skin.py`; doc `game/ui/CLAUDE.md`.

## Ruling 1 — `data/CLAUDE.md` belongs to A2 alone

A2 documents the manifest `slice` key there. A3 changes the `ui` slot groups,
which `data/CLAUDE.md` also describes — but A3 **must not** edit that file
(parallel branch, guaranteed conflict). The orchestrator adds the ui-slots line
to `data/CLAUDE.md` during Wave 4 integration.

## Ruling 2 — the `slice`-drop-on-reimport risk is A4's, and is narrower than A2 thought

A2's brief (§3, "Known follow-up") flags that
`editor/asset_import.import_idle_sheet` (`editor/asset_import.py:69-84`)
rebuilds a manifest entry from scratch and would drop an existing `slice`.

**Scope correction:** `editor/panels/details.py` imports only `pad_to_frame`
from that module (`details.py:40`) — it does **not** call `import_idle_sheet`.
`import_idle_sheet` is the single-`idle`-row importer used by the map/deco
categories, which are never sliced (slice is ui-only). So there is **no live
data-loss path**, and `editor/asset_import.py` stays out of every A-phase's
scope. Nobody edits it.

What **is** real, and is **A4's** to handle inside `details.py`: clicking
**Import** on a slot that already has slice margins must not silently zero them.
A4 seeds the slice spinboxes in `set_slot` and emits them from `draft_entry()`;
the coder must confirm the import path re-uses the current spinbox values rather
than resetting them, and pin it with a test.

## Ruling 3 — A4/A5 dependency gate

A4 and A5 branch off the umbrella only after A1+A2 and A3 have merged. Each
coder's first action is to confirm its dependency actually landed on its base:

- **A4** — open `data/schemas/asset_manifest.schema.json` and confirm the
  per-entry `slice` property exists with the shape A2 landed (`additionalProperties:
  false` means a mismatched key name fails validation). Confirm `data/slots.json`'s
  `ui` category has the 4-row vocab. If either is missing: **stop and report** —
  do not edit A2's or A3's files.
- **A5** — open `engine/render/hud.py` and confirm `HudSprite` carries
  `animation` / `anim_time_ms` **after `flip`**. Always pass them by keyword. If
  absent: **stop and report** — `engine/**` is out of A5's scope.

## Exit gate (every branch, every merge)

`py -m unittest discover -s tools/tests -t .` + `py tools/smoke.py`.
Baseline on the umbrella: **1086 tests, 16 failures, 1 skipped**. The gate is
**no NEW failures**, not zero. The 16 pre-existing failures live in
`test_run_controls` ×1, `test_details_panel` ×1, `test_editor_viewport` ×3,
`test_editor_panels` ×2, `test_editor_map_mode` ×2, `test_balancing_parity` ×6.
Do not fix them — they are out of scope for this slice. Note that none are in
`engine/` or `game/` tests, so a new failure there is unambiguously the phase's
own fault.
