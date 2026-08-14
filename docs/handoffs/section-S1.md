# Section S1 handoff

**Landed** — branch `ul-section-S1` @ `259bd7a` (handoff commit `55c3e67`).
Both phases merged in plan order, reviewed clean, 0 fix rounds.
- UL-1 | `ul-phase-UL-1-align` | `docs/briefs/phase-UL-1-align.md` | review: clean
- UL-2 | `ul-phase-UL-2-fonts` | `docs/briefs/phase-UL-2-fonts.md` | review: clean

**Interface deltas**
- `data/schemas/ui_screen.schema.json` — optional `align` enum
  (`left|center|right`) on per-widget overrides, before `color`. Absent→`left`.
- `editor/panels/_screen_primitives.py::resolve_align(spec, override)` — pure,
  override wins over default.
- `data/schemas/fonts.schema.json` — 7 required keys unchanged; extra
  `^[a-z][a-z0-9_]*$` keys now validate via `patternProperties`.
- `engine/render/fonts.py::configure_fonts(doc)` — accepts extras; missing-key
  check pinned to `_REQUIRED_KEYS` (frozen at import); `_LAYOUT_H` derives one
  entry per custom key each call, 7 pinned entries never overwritten
  (`_PINNED_LAYOUT_KEYS` guard).
- `editor/theme_ops.py` — new `PINNED_FONT_KEYS`, `is_valid_preset_name`,
  `is_pinned_preset`.
- `editor/panels/game_theme.py` — Add/Rename/Remove preset UI; pinned keys
  refused in code, not just UI.
- `editor/panels/screen_details.py` — new Alignment combo (UL-1); font combo
  needed zero change for custom presets (already read live `fonts.json`).

**Open findings**
- `data/CLAUDE.md:735` widget-key list now stale (missing `align` + others);
  left untouched to avoid colliding with S2's `layers` addition to the same
  line — owner: doc pass after S2 lands (UL-12 or top orchestrator).
- `tools/tests/fixtures/data/schemas/{ui_screen,fonts}.schema.json` are stale
  mirrors (no `align`/`patternProperties`); nothing red today — owner: next
  fixture refresh.
- Deleting a custom font preset has no cross-file usage scan (widget falls
  back to `md`); confirm dialog warns — owner: user decision, out of scope.

**Quick Tests**
- UL-1: set `hud.love_text.align="right"` in `data/ui/screens/hud.json`, run
  `py game/main.py`, confirm number spreads leftward, icon stays put.
- UL-2: add `title_big` (34, bold) in Theme panel, point `main_menu`'s title
  at it, run `py game/main.py`, confirm only that title is larger.

**Gate**
- `py tools/smoke.py` → PASS.
- `py -m pytest tools/tests/test_ui_align.py tools/tests/test_ui_skinning.py tools/tests/test_font_presets.py tools/tests/test_theme_data.py -q`
  → **64 passed, 38 subtests passed, 0 failed** (measured, post-merge). D5/D6
  invariants confirmed by review + test.
