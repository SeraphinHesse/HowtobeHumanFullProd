# Section S1 handoff

**Landed** — branch `ul-section-S1` @ `259bd7a`; both phases merged in plan
order (UL-1 then UL-2), reviewed clean, no fix rounds needed.
- UL-1 | `ul-phase-UL-1-align` | `docs/briefs/phase-UL-1-align.md` | review: clean/0 findings
- UL-2 | `ul-phase-UL-2-fonts` | `docs/briefs/phase-UL-2-fonts.md` | review: clean/0 findings

**Interface deltas**
- `data/schemas/ui_screen.schema.json` — new optional `align` enum
  (`"left"|"center"|"right"`) on the per-widget override object, inserted
  before `color`. Absent → `"left"`.
- `editor/panels/_screen_primitives.py` — new pure `resolve_align(spec,
  override)` (override wins, else spec, else `"left"`).
- `data/schemas/fonts.schema.json` — 7 required keys unchanged; opened to
  extra `^[a-z][a-z0-9_]*$` keys via `patternProperties` (same `font_spec`
  shape), `additionalProperties: false` retained.
- `engine/render/fonts.py::configure_fonts(doc)` — now accepts extras;
  missing-key check pinned via `_REQUIRED_KEYS` (frozen at import, never a
  live read); `_LAYOUT_H` gains one derived entry per non-pinned key each
  call (`_PINNED_LAYOUT_KEYS` guards the 7 from ever being overwritten).
- `editor/theme_ops.py` — new `PINNED_FONT_KEYS`, `is_valid_preset_name`,
  `is_pinned_preset`.
- `editor/panels/game_theme.py` — Add/Rename/Remove preset UI; pinned keys
  refused in code (`is_pinned_preset` guard), not just a disabled button.
- `editor/panels/screen_details.py` — new Alignment combo (UL-1, in
  `__init__` after the Font row); font combo needed **zero** change for
  custom presets (`_populate_font_combo` already sourced live `fonts.json`
  keys via `theme_ops.font_keys`).
- `game/ui/CLAUDE.md` — one new bullet documenting `align` as a real
  override (distinct from `screen_defaults.json`'s pre-existing draw hint).

**Open findings**
- `data/CLAUDE.md:735`'s widget-key list is now stale (missing `tint`,
  `text_id`, `parent`, `align`) — left untouched by design, since S2's
  `layers` key lands in the same spot; owner: whoever does the doc pass
  after S2 also lands (likely UL-12 or the top orchestrator).
- `tools/tests/fixtures/data/schemas/{ui_screen,fonts}.schema.json` are now
  stale mirrors of the live schemas (no `align`, no `patternProperties`).
  Nothing is currently red (no test validates fixture bytes against live
  schema content) — owner: next fixture refresh, not blocking.
- Deleting a custom font preset in the Theme panel has no cross-file usage
  scan; a widget still naming it silently falls back to `md` at draw time.
  Confirm dialog warns; owner: user decision, out of this phase's scope.
- UL-1 coder found `editor/panels/screen_details.py::_set_widget_form_enabled`
  needed the new align widgets added too (not in the brief's named region
  list) — done, verified in review, no UL-2 collision.

**Quick Tests**
- UL-1: set `hud.love_text`'s `align` to `right` in `data/ui/screens/hud.json`,
  run `py game/main.py`, confirm the love number spreads leftward from its
  stored x and the icon does not move.
- UL-2: add a `title_big` preset (size 34, bold) in the Theme panel, point
  `main_menu`'s title at it, run `py game/main.py`, confirm the title draws
  larger while every other screen is unchanged.

**Gate**
- `py tools/smoke.py` → PASS (62 data files schema-valid, 5-frame headless
  boot OK).
- `py -m pytest tools/tests/test_ui_align.py tools/tests/test_ui_skinning.py tools/tests/test_font_presets.py tools/tests/test_theme_data.py -q`
  → **64 passed, 38 subtests passed, 0 failed** (measured, run by this
  orchestrator post-merge). D5 golden parity confirmed unmoved; D6 pinned
  presets confirmed untouched (both by review and by test).
