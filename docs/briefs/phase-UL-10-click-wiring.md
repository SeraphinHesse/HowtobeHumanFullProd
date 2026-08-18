# Phase UL-10 — Wire clickable layers into the click path

Section S4 of `planning/UiLayeredWidgetsPLAN.md`. Depends on UL-9 (merged to
`ul-section-S4` before this phase's coder starts — **read UL-9's actual
committed `engine/ui_layers.py` and `data/schemas/ui_screen.schema.json`
first**; the signature below is UL-9's documented contract at plan-write time
and may have shifted in trivial ways, e.g. param order or a small helper
name).

## 1. Behavioral spec

- **D7 (amended)** — a layer entry may carry `clickable: bool` and
  `target: str`. `target` is either a widget id present in the SAME screen
  (retarget — fires that widget's own action) or one of three reserved tokens
  `close_window` / `back` / `noop`, or an id-shaped string matching neither
  (unroutable — allowed, WARN in the editor)
  (`planning/UiLayeredWidgetsPLAN.md:94-113`).
- **D8** — the hit resolver is pure; `Hud.hit()` is called twice per click
  (MOUSEBUTTONDOWN pan-arming probe, MOUSEBUTTONUP real handler) and must
  stay a pure read — no mutation, no toggling
  (`planning/UiLayeredWidgetsPLAN.md:114-119`, `game/ui/hud.py:454-478`
  already documents this for the existing drag-select toggle at
  `game/ui/hud.py:468-476`).
- **UL-9's contract** (`planning/UiLayeredWidgetsPLAN.md:507-518`): schema
  gains `clickable`/`target` on a layer entry (permissive `target`, not a
  closed enum); `engine/ui_layers.py` gains
  `hit(layers, owner_rect, mx, my, state) -> layer_id | None`, topmost-first
  within `over`, then the owner, then `under`, pure. **Confirm this exact
  signature against UL-9's landed code before writing `hit_layer`** — this
  brief's architecture section is written against it but is not the source of
  truth once UL-9 has merged.
- **Existing HUD hit path** — `game/ui/hud.py:454-478` (`Hud.hit`), consulted
  from `game/main.py:1094` (`hud_action = gp["hud"].hit(mx, my)`) and again at
  `game/main.py:1476` (the pan-arming `over_ui` probe). Action-string returns
  are routed at `game/main.py:1095-1118` (`"pause"`, `"end_turn"`,
  `("speed", n)`, `"drag_select"`).
- **BuildingUI hit path** — `game/ui/building_ui.py:1636-1658`
  (`BuildingUI.handle_click`, returns bool "consumed", not an action string);
  mode-specific sub-handlers `_move_select_click:1660`,
  `_unlock_click:1680`, `_construct_click:1702`; `self.close()` and
  `_back_to_upgrade` (`:1670-1678`) are the existing "close"/"back" behaviors
  this screen already has, and are what the reserved tokens map onto here.
- **Button-based menu screens** — the shared idiom is a `hit(self, mx, my)`
  that loops `(btn, action)` pairs and returns the first hit's action string,
  e.g. `game/ui/pause.py:84-88`. The same idiom recurs at
  `game/ui/add_name.py:127`, `game/ui/boss_cutscene.py:149`,
  `game/ui/cheat_menu.py:215`, `game/ui/credits.py:79`,
  `game/ui/debug_settings.py:148`, `game/ui/enemy_intro.py:159`,
  `game/ui/game_over.py:85`, `game/ui/highscores.py:159`,
  `game/ui/levelup.py:172`, `game/ui/main_menu.py:206`,
  `game/ui/player_intro.py:140`, `game/ui/settings.py:184`,
  `game/ui/tutorial_message.py:74`.
- **`submit_layers`** — `game/ui/skinning.py:230-258`, already wired into
  every screen's `submit()` (S2); `ids: Dict[name, (kind, widget)]` is the
  same dict every `hit()`/`handle_click` already has in scope
  (`game/ui/hud.py:322-330`, `game/ui/pause.py:68-74`).
- **Editor inspector** — `editor/panels/screen_details.py:1058-1169`
  (`_build_layer_inspector`), base-only (non-state-patch) rows `Z`/`Band` at
  `:1146-1166` are the pattern to copy for `Clickable`/`Target`. Widget ids in
  the open screen: `self._current_screen_defaults().get("widgets", {})`
  (`editor/panels/screen_details.py:808`, used by `_refresh_parent_combo`).
  `set_layer_field` is the S3 write path (`docs/handoffs/section-S3.md:10`),
  already used for base-only fields via `_on_reset_layer_base_field`
  (`editor/panels/screen_details.py:1152-1155`, `:1163-1165`).
- **Viewport wiring, S3-scoped-out** — `viewport.layer_selected` Signal
  (`editor/panels/viewport.py:186`), emitted at `:1094` and `:1105`, currently
  unconsumed (`docs/handoffs/section-S3.md:23`). Cross-wiring precedent:
  `editor/main.py:301-302` connects `screen_details.widget_selected` and
  `viewport.widget_selected` both ways. `screen_details.select_layer(widget_id,
  layer_id)` already exists (`editor/panels/screen_details.py:992`).
  Viewport's own preview-state dropdown is `self._state_combo`
  (`editor/panels/viewport.py:330-333`, `set_screen_state` at `:633`,
  `_refresh_state_combo` at `:644`); the inspector's is
  `screen_details.layer_state_combo` (`editor/panels/screen_details.py:1067-
  1072`), currently unlinked (`docs/handoffs/section-S3.md:14,24`).

## 2. Architecture plan

### 2.1 `game/ui/skinning.py::hit_layer(...)` — pure

New function (module-level, not on `ScreenSkinning`, matching
`engine.ui_layers`'s free-function style):

```python
def hit_layer(ids, widgets_spec, mx, my, state_of):
    """Consult every widget's clickable layers for this click; return an
    ACTION STRING/token exactly like `Hud.hit()` returns for a widget's own
    button, or None if no clickable layer was hit. `widgets_spec`: this
    screen's override dict (`ScreenSkinning._widgets_spec(screen_id)`),
    already loaded by the caller — no disk I/O here, matching
    `submit_layers`'s existing contract."""
```

For each `(name, (_kind, widget))` in `ids`, read `spec.get("layers")`, call
`ui_layers.hit(layer_list, widget.rect, mx, my, state_of(widget))`. If it
returns a `layer_id`, find that layer entry, and if `clickable` is truthy,
resolve `target`:
- `target` in `ids` (a widget id in THIS screen) → **retarget**: return
  exactly what that target widget's own hit-branch would return. Cheapest
  correct way: build `{widget_id: action}` once per screen (module-level
  const or built alongside `ids`, e.g. `pause.py`'s existing
  `_ACTION_IDS` reversed) and look up `target` in it. Do not hand-roll a
  second copy of each screen's action table — reuse what's already there
  (`_ACTION_IDS` in `pause.py`, the literal strings/tuples `Hud.hit` already
  returns).
- `target` in `("close_window", "back", "noop")` → return that literal
  string — a NEW token, not colliding with any existing action string used
  in `game/ui/CLAUDE.md` today (grep before landing to be sure).
- `target` unroutable (neither) → **RULING 1 (this phase, see below):
  SWALLOW.** Return `"noop"` (i.e. treat exactly like the reserved `noop`
  token) rather than `None`. Returning `None` here would tell the caller "no
  layer was hit," which falls through to the owner widget underneath — the
  exact worse failure mode `planning/UiLayeredWidgetsPLAN.md:642-644` flags.
- `clickable` falsy on the hit layer → return `None` (the layer is decorative
  only, click passes through to normal widget hit-testing — unchanged
  behavior, D5 parity).

**Ruling 1 — dead target SWALLOWS, does not fall through.**
Rationale (one line): a swallowed click is indistinguishable from "this decal
does nothing," which is a correct, honest UI state; a click that fell through
to the button behind a dead-target layer would look like the layer was never
clickable at all, silently changing what the designer thinks they configured
— exactly the risk the plan's new-risk bullet names
(`planning/UiLayeredWidgetsPLAN.md:639-644`). Consistent with `noop`'s own
semantics: both mean "this click stops here."

### 2.2 Each screen's hit path consults `hit_layer` FIRST

`Hud.hit(self, mx, my)` (`game/ui/hud.py:454`): as its first statement (after
the existing `if self._panel_open: return None` guard, which must stay
first — a closed-off panel is not clickable at all, layers included), call

```python
layer_action = hit_layer(self.ids, self.skinning._widgets_spec(self.screen_id),
                         mx, my, self.skinning.state_of)
if layer_action is not None:
    return layer_action
```

then fall through UNCHANGED to the existing branches. `Hud.hit` stays pure —
`hit_layer` never mutates. `game/ui/skinning.py`'s `_widgets_spec` is already
a private method on `ScreenSkinning` used internally by `apply`/`submit_layers`
(`game/ui/skinning.py:156, 245`); either expose it (drop the leading
underscore is the smaller change and matches `widget_rect`/`defaults`'s
existing public-accessor pattern at `:184-204`) or add a one-line public
wrapper — coder's call, keep it small.

`BuildingUI.handle_click` (`game/ui/building_ui.py:1636`): same idea, but the
return contract is bool-consumed, not an action string, and there is no
single flat `ids` dict spanning the three classes (`ConstructPreview`,
`MovePreview`, `BuildingUI` each have their own pair per S2's handoff,
`docs/handoffs/section-S2.md:19`). Scope this phase's `BuildingUI` wiring to
the outer `BuildingUI.handle_click` only (the Quick Test's screen is `hud`,
not building panels — this is defense in depth, not the tested path). Consult
`hit_layer` right after the `close_btn` check (`:1645-1647`, so an explicit
close is not reinterpreted by a stray layer) and before the mode dispatch
(`:1648`). Map the three reserved tokens for this screen: `close_window` →
`self.close(); return True`, `back` → if `self.mode == "move_select"`:
`self._back_to_upgrade(session); return True`, else same as `noop`, `noop` →
`return True` (consume, do nothing). A retarget resolves the SAME way as
`Hud`'s — look up `target` against this screen's own `ids`/action mapping;
`BuildingUI` has no single action-string table today, so retarget here means
"call whatever that target id's own click branch does" — if that plumbing
isn't a 10-line addition, it is acceptable to implement retarget for
`BuildingUI` as: only the three reserved tokens + swallow-on-unroutable in
this phase, and leave widget-id retargeting on this one screen as a follow-up
noted in the phase's report (state this explicitly if taken — do not silently
drop scope).

**Button-based menu screens** (`pause.py` and the 13 siblings listed in §1):
identical idiom — `hit_layer` consulted first, falling through to the
existing `for btn, action in self.buttons: ...` loop unchanged. Use
`pause.py:84-88` as the reference implementation (fully wire it — it is the
screen the Quick Test does NOT cover but the pattern is proven there first),
then apply the same 3-line insertion to the other 13 files. `target` retarget
resolves against each screen's own `(label, action)` table (`pause.py`'s
`_ACTION_IDS`, or the equivalent local dict in each sibling file — read each
file's own `hit()` to find its action table before editing it, they are not
identical in shape). Since **no shipped screen JSON authors a `layers` entry**
(D5), this is 100% dead code on every existing screen today — the insertion
must be a no-op verified by the golden-parity check, not a "trust me" claim.

### 2.3 `game/main.py` — route the reserved tokens + 2 editor wiring items

**Reserved tokens for `Hud`** (`game/main.py:1094-1118`, right after the
existing branches, before the drag-select block or after — either position
is fine since these are new distinct string values, no existing branch can
match them): add

```python
if hud_action == "noop":
    return
if hud_action == "close_window":
    # HUD's pause button is the closest analogue to "the window" here;
    # HUD has no other closable window of its own. Route to pause-close
    # if a panel/menu owns "close" semantics elsewhere; otherwise treat
    # identically to noop on this screen (swallow).
    return
if hud_action == "back":
    return   # HUD has no "back" concept; swallow (same rationale)
```

(Coder: if `pause.py`/`building_ui.py`'s own reserved-token handling already
covers `close_window`/`back` meaningfully for THEIR screens per §2.2, HUD's
own branches genuinely are swallow-only — HUD is a persistent overlay, not a
window. State this in the phase report rather than inventing HUD-specific
window-closing behavior that doesn't exist elsewhere in the codebase.)

**Editor wiring item 1** — `editor/main.py:301-302`, alongside the existing
`widget_selected`/`select_widget` cross-connect, add:

```python
self.viewport.layer_selected.connect(self.screen_details.select_layer)
```

(One direction only — `screen_details` has no matching `layer_selected`
signal to connect back; `select_layer(widget_id, layer_id)` already exists,
`editor/panels/screen_details.py:992`.)

**Editor wiring item 2** — link `screen_details.layer_state_combo`
(`editor/panels/screen_details.py:1067`) and `viewport._state_combo`
(`editor/panels/viewport.py:330`) so they show the same state. Precedent for
loop-safe two-way linking: `blockSignals`/`_populating` guards already used
throughout `screen_details.py` (e.g. `_refresh_parent_combo`,
`editor/panels/screen_details.py:811,821`). Wire in `editor/main.py` near the
line-301 cross-connect:

```python
self.viewport._state_combo.currentTextChanged.connect(
    self.screen_details.sync_layer_state)
self.screen_details.layer_state_combo.activated.connect(
    lambda _i: self.viewport.set_screen_state(
        self.screen_details.layer_state_combo.currentData()))
```

Add `screen_details.sync_layer_state(name)` as a small new method: sets
`layer_state_combo`'s current index to `name` with `blockSignals` around it
(mirroring `:1386-1388`'s existing pattern), then calls the panel's existing
`_refresh_layer_inspector()` so the rows follow. Guard against re-entrant
loops the same way `_populating` already guards elsewhere in this file.

### 2.4 `editor/panels/screen_details.py` — Clickable checkbox + target picker

Insert as two new BASE-ONLY rows (never state-patch keys, matching `Z`/`Band`
at `:1146-1166`) right after the Band row, before `box_layout.addLayout(form)`
(`:1168`):

```python
self.layer_clickable_check = QCheckBox("Clickable", self)
self.layer_clickable_check.toggled.connect(self._on_layer_clickable_toggled)
clickable_row, self.layer_clickable_reset_button = self._field_row(
    (self.layer_clickable_check,), "clickable",
    lambda: self._on_reset_layer_base_field("clickable"))
form.addRow("", clickable_row)

self.layer_target_combo = _NoWheelComboBox(self)
self.layer_target_combo.setEditable(True)   # id-shaped free text, D7 amended
self.layer_target_combo.activated.connect(self._on_layer_target_changed)
self.layer_target_combo.editTextChanged.connect(self._on_layer_target_edited)
target_row, self.layer_target_reset_button = self._field_row(
    (self.layer_target_combo,), "target",
    lambda: self._on_reset_layer_base_field("target"))
form.addRow("Target", target_row)

self.layer_target_warning = QLabel("", self)
self.layer_target_warning.setWordWrap(True)
self.layer_target_warning.setStyleSheet("color: #d08820;")  # WARNING, not error
form.addRow("", self.layer_target_warning)
```

Populate `layer_target_combo` from `self._current_screen_defaults().get(
"widgets", {})` (the same source `_refresh_parent_combo` reads,
`:808`) plus the three reserved tokens, refreshed whenever the layer selection
changes (same refresh hook `_refresh_layer_inspector`/`_refresh_parent_combo`
already use). On every value change (`_on_layer_target_changed` and
`_on_layer_target_edited`), recompute routability — target in this screen's
widget ids, OR one of the three reserved tokens — and set
`layer_target_warning`'s text to `""` (routable) or a one-line warning
(unroutable) — **this is D7 amended's required visible warning**
(`planning/UiLayeredWidgetsPLAN.md:109-113`, `docs/UiLayeredWidgetsPLAN.md`
risk bullet `:639-641`). Do not gate saving on this — the amendment is
explicit that an unroutable target still saves.

Both rows write via `self._session.set_layer_field(widget_id, layer_id,
"clickable"/"target", old_value, new_value)` — the S3 write path
(`docs/handoffs/section-S3.md:10`), same call shape already used at
`editor/panels/screen_details.py:1250,1268,1279`.

## 3. File scope + shared-file contract

| File | What UL-10 does | What UL-10 must NOT touch |
|---|---|---|
| `game/ui/skinning.py` | Add `hit_layer(...)` (new function). | — |
| `game/ui/hud.py` | Add the `hit_layer` consultation as the first statement in `Hud.hit()` (`:454-478`), after the `_panel_open` guard. | **`ids` dict** (`:322-330`) — UL-11 adds `life_1`/`life_2`/`life_3` there; UL-10 reads `self.ids`, never edits its contents. |
| `game/ui/building_ui.py` | Add `hit_layer` consultation + reserved-token handling in `BuildingUI.handle_click` (`:1636-1658`), right after the `close_btn` check. | The three mode sub-handlers' internals beyond the insertion point; `ConstructPreview`/`MovePreview`'s own hit paths (out of this phase's cited scope — plan names only the outer `BuildingUI.handle_click`). |
| `game/ui/pause.py` + the 13 sibling menu screens (§1 list) | Add the same 3-line `hit_layer` consultation to each screen's `hit()`. | Each screen's own `(label, action)` table shape — read, don't restructure. |
| `game/main.py` | Add the 3 reserved-token branches after `hud_action = gp["hud"].hit(mx, my)` (`:1094-1118`); nothing else in this file. | The `over_ui` probe block (`:1468-1495`) — it already calls `gp["hud"].hit(px, py)` (`:1476`) and needs NO changes, since `hit_layer`'s new returns are non-`None` exactly when a real hit occurred, which `over_ui` already treats as "over UI." **UL-11 may also touch `main.py` minimally** (e.g. life-lost event wiring) — coordinate by touching ONLY the click-routing block cited above, nothing else in this file. |
| `editor/panels/screen_details.py` | Add `Clickable`/`Target`/warning rows in `_build_layer_inspector` (`:1146-1168`) + their handlers + populate/refresh logic. | The state-patch rows above them (`:1080-1144`) — clickable/target are base-only, do not add them to the state-patch machinery. |
| `editor/main.py` | Add the `layer_selected` connect + the two state-combo cross-connects, both near `:301-302`. | Everything else in this file. |
| `engine/ui_layers.py`, `data/schemas/ui_screen.schema.json` | **Do not touch.** UL-9 owns these and merges to `ul-section-S4` before this phase starts — read them, never edit them. | |

## 4. Exit gate

```
py tools/smoke.py
py -m pytest tools/tests/test_ui_layer_click.py tools/tests/test_hud_panel.py -q
```

New test file `tools/tests/test_ui_layer_click.py` (mirror
`tools/tests/test_ui_layer_ops.py`'s / `test_ui_layers.py`'s fixture style —
`TempDataCase`/in-memory `ScreenSkinning.from_overrides`, never live `data/`):

1. A retargeting clickable layer produces the target widget's own action
   (build a minimal `ids` + override with one `clickable`/`target` layer,
   call `hit_layer`, assert the returned action equals what the target's own
   branch would return).
2. `Hud.hit()` called twice with identical `(mx, my)` returns identical
   answers and mutates nothing observable (D8) — assert no attribute on
   `self.ids`' widgets or `self._panel_open` etc. changed between the two
   calls.
3. A screen with no `clickable` layers (or no `layers` at all) routes exactly
   as it did before this phase — a regression check against the pre-UL-10
   branch behavior for at least one existing action (`"pause"` via
   `btn_pause`).
4. **Ruling 1 proof**: a layer with `clickable: true` and an unroutable
   `target` (e.g. `"no_such_widget"`), when hit, returns `"noop"` (swallow) —
   NOT the action of the widget underneath it. Construct the case so the
   underlying widget WOULD fire a real, distinguishable action if the click
   fell through, and assert it did not.

**RULING 2 — `test_ui_min_targets.py` scope.** Read
`tools/tests/test_ui_min_targets.py` in full before implementing (already
read for this brief: `_buttons()` at `:145-153` filters
`_capture_screen_ids()`'s `{name: (kind, widget)}` pairs on
`kind != "button"`, and `_capture_screen_ids` (`:107-142`) only ever captures
what each screen's `ids` dict puts there — a clickable LAYER is never an
entry in `ids`; it is a sub-rect authored inside an EXISTING widget's
`layers` array, resolved only via `engine.ui_layers.resolve`/`ordered`, and
never reaches `_widgets_from_ids`). **Ruling: clickable layers join the
12–16px NON-BLOCKING lint only, not the ≥12px hard-floor assertion.**
Rationale: (1) mechanically, joining the hard floor means teaching
`_capture_screen_ids`/`_buttons()` to also resolve every screen's layer
geometry via `engine.ui_layers`, which is a structural change to a test whose
whole design is "walk `ids`, not layers" — out of proportion to this phase;
(2) a clickable layer is very often DECORATIVE art retargeted onto an
existing, already-floor-checked button (the Munchkin-on-Pause Quick Test is
exactly this shape) — the real click target underneath still clears 12px
even when the decal itself is smaller, so a hard failure on the decal's own
size would be a false positive on an already-accessible control; (3)
`game/ui/CLAUDE.md`'s standing rule (`:116`, "do not mass-resize controls to
silence the lint") forbids fixing a hard failure by resizing designer art,
which is exactly what a clickable-layer hard-floor assertion would pressure
designers to do for purely decorative click surfaces. Implement as: extend
`tools/tests/test_ui_min_targets.py`'s existing NON-BLOCKING lint
(`test_report_small_click_targets`, `:174-184`) to also walk clickable layers
(resolve each via `engine.ui_layers.resolve`, using the SAME `_capture_screen_ids`
data plus each screen's raw `layers` list) and print any under 16px alongside
the existing button roster — same `[UR-5 lint]` prefix, same "never fails"
contract. Do **not** add clickable layers to `TestButtonMinSize`. Do **not**
touch `MIN_HARD`/`MIN_LINT`. Do not resize any existing control to satisfy
this.

**Quick Test (in game, run by the orchestrator/user, not the coder):** author
a `clickable: true` layer on `hud.btn_pause` in `data/ui/screens/hud.json`
(or a test-only override doc) with `target: "btn_end_turn"`; run
`py game/main.py`; click the Munchkin/layer art and confirm the turn ends;
confirm clicking the REST of the pause button's rect (outside the layer)
still pauses.

**D5 reminder** — this phase must leave `data/ui/screen_previews.json`,
`data/ui/screen_defaults.json`, and `tools/tests/test_ui_skinning.py` BYTE
IDENTICAL. No shipped screen JSON gets `clickable: true` by default in this
phase; only test fixtures/the Quick Test's throwaway override author one.
Verify with `git diff --stat <base>..HEAD -- data/ui/screen_previews.json
data/ui/screen_defaults.json tools/tests/test_ui_skinning.py` before
reporting done — empty output required.
