# Phase UH-3 — Editor: honest controls (grey-out no-op Color/label) + pink-test verdict

Plan: `planning/UiEditorHonestyPLAN.md` §4 UH-3 (decision **D3 binding**: any
control that cannot take effect is disabled with an explanatory tooltip — never
silently accepted). Branch: work happens on the umbrella branch the orchestrator
names; base `Development`. Package doc: `editor/CLAUDE.md` +
`editor/panels/CLAUDE.md` (§Phase B4 screen mode).

---

## 1. Behavioral spec (with citations)

**The lie being fixed.** The screen-details form accepts `color` and `label`
overrides on every widget unconditionally (`editor/panels/screen_details.py:489-497`
Color click handler, `:509-518` label handler — no gating anywhere), but the game
discards both in two whole classes of cases:

- **Color on a skinned widget is dead in the game.** `Button.submit` with a
  `skin` set draws the sprite and documents "``color`` (a fill override) has
  nothing to fill and is ignored" (`game/ui/widgets.py:253-258`); `submit_panel`
  likewise: "``fill``/``border`` are then ignored" when skinned
  (`game/ui/widgets.py:110-119`). The editor viewport meanwhile *previews*
  `color` as a tint on skinned widgets (`editor/panels/viewport.py:933`) — the
  editor shows something the game will never draw. (UH-6 later makes tint real;
  UH-3 only stops the lie.)
- **Label on code-owned (dynamic) text is dead in the game.**
  `ScreenSkinning.apply` setattrs any override key onto the holder
  (`game/ui/skinning.py:136-141`), but the HUD readouts draw a per-frame
  computed string, not the holder's `label` — e.g. `love_text` submits the live
  `love_txt` value (`game/ui/hud.py:322-326`); `game/ui/CLAUDE.md`
  ("hud.py's ~12 stable readouts"): "the displayed TEXT is a live game-state
  value … and stays code-owned — the override surface is
  rect/font_key/text_color/visible only". Static titles are the sanctioned
  exception: "unlike hud.py's dynamic readouts — 'label' is a legitimate
  override field here too" (`game/ui/main_menu.py:56-58`). Buttons draw
  `self.label` (`game/ui/widgets.py:246-252,266`), and `apply()` runs after
  layout so an override wins (`game/ui/CLAUDE.md` §UI screen customization) —
  button labels ARE editable.

**Required behavior (all of it recomputed live, none of it saved state):**

1. **Color picker** (`self.color_button`, `screen_details.py:130-134`) is
   **disabled iff the selected widget currently resolves to a skin**, with the
   tooltip pinned in §2. "Resolves to a skin" is exactly the viewport's own
   resolution (`editor/panels/viewport.py:924-929`): per-widget `skin` override
   if present, else the screen doc's `defaults.button_skin` for `kind ==
   "button"` / `defaults.panel_skin` for `kind == "panel"`. Unskinned →
   enabled, tooltip cleared.
2. **Text Color** (`self.text_color_button`, `:136-141`) **stays enabled on
   skinned widgets** — `text_color` still applies to the label overlay
   (`game/ui/widgets.py:251` → `:266`; `game/ui/skinning.py:59-66`
   `button_kwargs`). Do not touch it.
3. **Label edit** (`self.label_edit`, `:143-147`) is **disabled on code-owned
   text, enabled on data-owned text**, per the pinned `label_is_code_owned`
   rule in §2: buttons editable; `label`-kind editable only for the pinned
   static-title ids; `panel`/`backdrop`/`bar`/`field` kinds disabled (the game
   draws no holder label for panels/backdrops — `submit_panel` takes no label,
   `game/ui/widgets.py:108-121`; `bar` = the xp bar whose text is live state;
   `field` content is user-typed at runtime, `game/ui/CLAUDE.md` cheat-menu
   round field). Disabled → the tooltip pinned in §2.
4. **Recompute triggers** — the disabled state is derived, never stored, and
   must be recomputed on every path that can change the resolution:
   - widget (re)selection / form population — `_populate_widget_form`
     (`screen_details.py:400-445`);
   - per-widget skin assigned or cleared — `_on_skin_changed` (`:462-470`) and
     `_on_reset_field("skin")` (`:533-547`, already ends in
     `_refresh_widget_form`);
   - screen-level `button_skin`/`panel_skin` default changed or cleared —
     `_on_default_combo_changed` (`:633-640`), `_on_reset_default_field`
     (`:642-650`) (today these refresh only the defaults section, not the
     widget form);
   - undo/redo — `_refresh_after_undo` (`:311-314`) already calls
     `_refresh_widget_form`, so it comes free once the recompute lives in
     `_populate_widget_form`.
5. **Per-field reset buttons keep their existing rule** ("does THIS key have an
   override", `_refresh_reset_buttons`, `:387-398`): a pre-existing dead
   `color` override on a now-skinned widget keeps its "↺" enabled so the user
   can *remove* the dead override — they just can't author a new one. Honest
   both ways.
6. **No other control changes.** Rect/skin/font/visible and the whole
   screen-level section behave exactly as today; `_set_widget_form_enabled`
   (`:370-385`) keeps blanket-enabling on selection — the honest recompute runs
   after it and narrows.

## 2. Architecture plan

**New pure module `editor/panels/_screen_rules.py`** (Qt-free, pygame-free —
sibling in spirit to `editor/panels/_screen_primitives.py`; MUST be added to
`test_editor_viewport.TestPurity`'s import list per `editor/CLAUDE.md`):

- `resolved_skin(spec, override, style) -> str | None` — the pinned resolver,
  a literal mirror of `editor/panels/viewport.py:924-929` (`override.get
  ("skin")`, else `style.get("button_skin")` for kind `button` /
  `style.get("panel_skin")` for kind `panel`). Docstring must cite viewport
  924-929 as the mirrored source and name the drift risk; UH-3 deliberately
  does NOT refactor viewport to import it (viewport is UH-2's shared file).
- `label_is_code_owned(screen_id, widget_id, kind) -> bool` — **the pinned
  code-owned-label helper** the plan left to the planner. Rule, in order:
  1. `kind == "button"` → **False** (editable; `game/ui/widgets.py:246-266`).
  2. `kind == "label"` → False iff `(screen_id, widget_id)` is in
     `_STATIC_TITLE_IDS`, else **True**. Pinned table — exactly the static
     titles `game/ui/CLAUDE.md` sanctions ("Every static title/header is an
     id too"):
     `{("main_menu","title"), ("main_menu","subtitle"), ("pause","title"),
     ("settings","title"), ("credits","title"), ("game_over","title"),
     ("add_name","title")}`.
     The executor MAY extend this table only with a `file:line` citation
     proving the game draws that holder's `.label` (the `main_menu.py:56-58`
     pattern); anything unproven stays disabled — disabling a static label is
     a smaller lie than enabling a dead one.
  3. any other kind (`panel`/`backdrop`/`bar`/`field`) → **True**.
  Kinds are the six-value enum pinned by
  `data/schemas/screen_defaults.schema.json` / `game/ui/skinning.py:16-19`;
  the helper reads `spec["kind"]` from the loaded defaults
  (`data/ui/screen_defaults.json` widgets carry `{kind, label, rect}` —
  verified live). No exporter/schema change in UH-3 (keeps UH-3 independent of
  UH-1/UH-4's `screen_defaults.json` regeneration, plan §3).
- **Tooltip constants** (module-level, so UH-6 can retarget ONE symbol when it
  repurposes Color as tint):
  - `TOOLTIP_COLOR_SKINNED = "Colors come from the sprite sheet — this widget renders a skin. Clear the skin (or the screen's default skin) to color the flat fallback."`
  - `TOOLTIP_LABEL_CODE_OWNED = "This text is written by game code at runtime — edit it in game code, not here."`

**In `editor/panels/screen_details.py`** (Qt side, all logic delegated to the
pure module):

- Import the three names from `_screen_rules`.
- New method `_refresh_honest_controls(self)` in the "per-widget form" region:
  reads `spec` (current screen defaults), `override`
  (`self._session.doc["widgets"].get(id, {})`) and `style`
  (`self._session.doc.get("defaults", {})`), then:
  `self.color_button.setEnabled(resolved_skin(...) is None)` +
  `setToolTip(TOOLTIP_COLOR_SKINNED if disabled else "")`;
  `self.label_edit.setEnabled(not label_is_code_owned(...))` + tooltip
  likewise. Qt delivers tooltip events to disabled widgets, so the
  explanation shows exactly when it matters (standard Qt behavior — executor
  confirms live).
- Call sites (the recompute triggers of §1.4): one call at the **end of
  `_populate_widget_form`** (after `_refresh_reset_buttons`, line 445); one
  `self._refresh_widget_form()` added in `_on_skin_changed` (after the
  baseline update, line 470); one `self._refresh_widget_form()` added in each
  of `_on_default_combo_changed` (after line 640) and
  `_on_reset_default_field` (after line 650) — `_refresh_widget_form` is
  no-op-safe with no selection (`:447-449`).

**Tests** — new module `tools/tests/test_screen_honest_controls.py`
(editor tier marker; `QtCase` + `self.track(...)` per `editor/CLAUDE.md`
§Testing; `TempDataCase`-style temp `data/` — never assert live `data/`):
pure matrix tests for `label_is_code_owned` (all six kinds × static-title
hit/miss) and `resolved_skin` (override / button-default / panel-default /
none) need no Qt; Qt tests cover: Color disabled + `TOOLTIP_COLOR_SKINNED`
present after `push_skin_assign`, re-enabled after clearing the skin (the
plan's named test), disabled via `defaults.button_skin` alone, label edit
disabled on a `hud` readout id and enabled on `main_menu`/`title`, dead-color
reset button still enabled, undo of a skin assign re-enables Color. Plus the
one-line TestPurity registration in `tools/tests/test_editor_viewport.py`.

## 3. File scope + shared-file contract

| File | Change |
|---|---|
| `editor/panels/_screen_rules.py` | **NEW** — pure helpers + tooltip constants (§2). No other UH phase creates or touches it. |
| `editor/panels/screen_details.py` | **MOD, shared — see warning** |
| `tools/tests/test_screen_honest_controls.py` | **NEW** — tests (§2) |
| `tools/tests/test_editor_viewport.py` | **MOD** — one line: add `_screen_rules` to `TestPurity`'s import list, nothing else |

**SHARED-FILE WARNING — `editor/panels/screen_details.py`.** UH-2 (view
filtering) and UH-4 (display names) also modify it. UH-3's footprint is
pinned to exactly:

- the module import block (add the `_screen_rules` import);
- ONE new method `_refresh_honest_controls`, inserted in the
  "per-widget form" region immediately after `_refresh_reset_buttons`
  (`:387-398`);
- ONE added call at the end of `_populate_widget_form` (`:400-445`, after the
  existing `_refresh_reset_buttons(override)` call);
- ONE added `self._refresh_widget_form()` line in each of `_on_skin_changed`
  (`:462-470`), `_on_default_combo_changed` (`:633-640`) and
  `_on_reset_default_field` (`:642-650`).

UH-3 must NOT touch `_refresh_widget_list` (`:337-342`) or
`_current_screen_defaults` (`:322-325`) — those are UH-2's insertion points —
and must NOT touch the widget-list item text — that is UH-4's. It reads
`spec`/`override`/`style` only through the accessors `_populate_widget_form`
already uses, so it composes with UH-2's per-view filtering regardless of
landing order. `editor/panels/viewport.py` is deliberately **untouched**
(UH-2's file; the `:933` tint preview stays as-is until UH-6). **UH-6
contract**: UH-6 repurposes the Color control as tint on skinned buttons — it
flips the §2 enable rule and rewrites `TOOLTIP_COLOR_SKINNED` in
`_screen_rules.py`; keep both names stable so UH-6's diff is those two spots.
No exporter, schema, `data/`, `engine/` or `game/` code changes in UH-3
(the pink test *writes* `data/ui/screens/building_panel.json` through the
editor's normal validated Save — that is content, not a code change).

## 4. Exit gate + Quick Test

**Gate.** This is an editor-tier-only phase, and testgate's `--affected`
narrowing has a known vacuous-pass bug for exactly that shape
(`tools/testgate.py:222-238`; plan §5) — so name the modules explicitly while
iterating:

```bash
py -m pytest tools/tests/test_screen_honest_controls.py tools/tests/test_editor_viewport.py -q
py tools/smoke.py                # data validation (the saved pink override must validate)
py tools/testgate.py check       # full gate, ONCE, at handback — GATE PASS / zero
```

**Quick Test — the artifact's "pink test" (mandatory, verdict goes in the
report either way):**

1. `py editor/main.py` → selector: ui → Screens → `building_panel` → select
   `boss_btn` in the widget list. Observe honest state first: if `boss_btn`
   resolves to a skin, **Color…** is greyed with the sprite-sheet tooltip
   while **Text Color…** stays enabled.
2. Click **Text Color…**, pick pink (255, 0, 255), **Save**.
3. `py game/main.py` → start a run → open the building panel's base-info mode
   (click the base) so the boss button is visible
   (`game/ui/building_ui.py:1235-1237` submits it with
   `**button_kwargs(self.boss_btn)`, which forwards the `text_color` override
   — `game/ui/skinning.py:59-66`).
4. **PASS**: the boss button's label renders pink. **FAIL**: pink does not
   appear → the live game-side bug the artifact suspects — file it in the
   phase report with the exact repro (the saved
   `data/ui/screens/building_panel.json` fragment + the screen/mode you
   observed), and do NOT expand UH-3 to fix game code; the gate above still
   must be green for UH-3 itself.
5. Also exercise the recompute live: assign a skin to `boss_btn` → Color
   greys out with tooltip; Ctrl+Z → Color re-enables; set the screen's
   `Defaults → Button skin` → Color greys out again; select `love_text` on
   the `hud` screen → Label greyed with the code-owned tooltip; select
   `main_menu`'s `title` → Label editable.

State in the report exactly what was exercised live vs statically read, per
the `/report` taxonomy.
