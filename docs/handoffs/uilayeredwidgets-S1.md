# Section S1 handoff

**Landed** — branch `ul-section-S1` @ `259bd7a`. Both phases merged in plan
order, reviewed clean, 0 fix rounds.
- UL-1 | `ul-phase-UL-1-align` | `docs/briefs/phase-UL-1-align.md` | clean
- UL-2 | `ul-phase-UL-2-fonts` | `docs/briefs/phase-UL-2-fonts.md` | clean

**Interface deltas**
- `data/schemas/ui_screen.schema.json` — optional `align` enum
  (`left|center|right`) on per-widget overrides, before `color`. Absent→`left`.
- `editor/panels/_screen_primitives.py::resolve_align(spec, override)` — pure,
  override wins over default.
- `data/schemas/fonts.schema.json` — 7 required keys unchanged; extra
  `^[a-z][a-z0-9_]*$` keys now validate via `patternProperties`.
- `engine/render/fonts.py::configure_fonts(doc)` — accepts extras; missing-key
  check pinned to `_REQUIRED_KEYS` (frozen at import); `_LAYOUT_H` derives one
  entry per custom key each call; 7 pinned entries never overwritten.
- `editor/theme_ops.py` — new `PINNED_FONT_KEYS`, `is_valid_preset_name`,
  `is_pinned_preset`. `game_theme.py` — Add/Rename/Remove UI; pinned keys
  refused in code, not just UI.
- `editor/panels/screen_details.py` — new Alignment combo (UL-1); font combo
  needed zero change for custom presets (already read live `fonts.json`).

**Open findings**
- `data/CLAUDE.md:735` widget-key list stale; left untouched, avoids
  colliding with S2's `layers` addition — owner: doc pass after S2 lands.
- Fixture schema mirrors stale (no `align`/`patternProperties`); nothing red
  today — owner: next fixture refresh.
- Deleting a custom font preset has no usage scan (falls back to `md`, dialog
  warns) — owner: user decision, out of scope.

**Quick Tests**
- UL-1: `hud.love_text.align="right"` in `data/ui/screens/hud.json`, run
  `py game/main.py`, number spreads leftward, icon stays put.
- UL-2: add `title_big` (34, bold) in Theme panel, point `main_menu`'s title
  at it, run `py game/main.py`, only that title is larger.

**Gate** — `py tools/smoke.py` PASS; `py -m pytest test_ui_align.py
test_ui_skinning.py test_font_presets.py test_theme_data.py -q` → **64 passed,
38 subtests passed, 0 failed** (measured, post-merge).
