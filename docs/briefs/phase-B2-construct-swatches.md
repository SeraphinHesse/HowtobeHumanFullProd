# Phase B2 — ConstructPreview swatches

Section S3 (Building colour) of `planning/MasterSheetColumnsPLAN.md`, phase
block at `planning/MasterSheetColumnsPLAN.md:652`. **B1 lands and is merged
into `section-S3` before this phase starts** — read §3's B1 contract first.

**Goal.** The colour swatches in the build-confirm modal: they appear only for a
colour-capable building, clicking one repaints the preview immediately, and the
building that gets placed carries the picked colour column.

---

## 1. Behavioral spec

### 1.1 What exists today (cited, not asserted)

- **The modal.** `ConstructPreview` (`game/ui/building_ui.py:295`) is a fixed
  **170×150** panel centred on the logical 640×360 surface
  (`building_ui.py:325-327`: `pw, ph = 170, 150`, `x, y = view_w // 2 - pw // 2,
  view_h // 2 - ph // 2`). Its geometry is built ONCE in `__init__` — there is
  no per-frame `layout()` (`building_ui.py:357-360`).
- **The dice button** is the last widget built before the confirm/cancel row:
  `self.dice_btn = Button((x + pw - 8 - 15, y + 48, 15, 15), T("building.btn.dice"), "md")`
  (`building_ui.py:331-332`).
- **The `ids` dict** — `{name: (kind, widget)}`, the contract `skinning.apply`
  and `tools/export_ui_layouts.py` both consume — is built at
  `building_ui.py:362-368`, then `self.skinning.apply(self.screen_id, self.ids)`
  and `self.rect = self._panel.rect`.
- **`handle_click`** (`building_ui.py:406-429`) returns an action string. Its
  order is close → cancel → confirm → dice → **`name_rect`**
  (`building_ui.py:424`, `if contains(self.name_rect, mx, my)`) → `None`.
  The `name_rect` branch is a plain rect containment test and it is the
  broadest one, so anything that overlaps that band must be tested BEFORE it.
- **`submit`** (`building_ui.py:441-506`) is ordered panel → buttons → text and
  says so at `building_ui.py:445-447`; the BUTTON block is
  `building_ui.py:458-469` (dice, confirm, cancel, close), and every standalone
  text submission follows it (`building_ui.py:470-506`). This order is
  regression-pinned by
  `tools/tests/test_hud_panel.py:157` (`TestConstructPreviewZOrder`).
- **The height constraint** is stated in the code, `building_ui.py:485-496`:
  the stat list starts at `sy = y + 69`, steps `_row_step("sm", leading=0)` =
  `layout_h("sm")` = **11**, and the worst case (the defence family's 5 rows)
  bottoms at `y + 69 + 4*11 + layout_h("sm") = y + 124`, against the
  CONFIRM/CANCEL row top `btn_y = y + ph - 24 = y + 126`
  (`building_ui.py:342`). **Two pixels of slack.** There is no room below the
  stat list, and pushing the stat list is forbidden by the phase block.
- **Widgets.** `Button(rect, label, font_key="lg", enabled=True, skin=None)`
  (`game/ui/widgets.py:398`); `Button.submit(renderer, *, color=None,
  text_color=None, anim_ms=0)` (`widgets.py:456`) — **`color` overrides the
  fill**, so a swatch needs NO new draw path. `configure_palette`
  (`widgets.py:92-104`) rebinds every `C_*` module constant IN PLACE at boot,
  which is why colours are read as `widgets.C_NAME` attribute access and never
  `from .widgets import C_NAME` (`widgets.py:102-104`).
- **Skinning helpers** `is_visible(widget)` (`game/ui/skinning.py:56`) and
  `button_kwargs(btn)` → `{"color": …, "text_color": …}`
  (`skinning.py:65-72`), both already imported by `building_ui.py:68`.
- **Unknown ids are safe.** `ScreenSkinning._validate_ids`
  (`skinning.py:214-229`) only validates ids the OVERRIDE doc names against
  `screen_defaults.json`; adding new ids to a screen's `ids` dict that
  `screen_defaults.json` does not know about raises nothing. **So B2 needs no
  `data/` regeneration** — and must not attempt one (out of scope).
- **The click-target floor.** `tools/tests/test_ui_min_targets.py:55`
  (`MIN_HARD = 12`) asserts `min(w, h) >= 12` for every `kind == "button"`
  reached through `tools/export_ui_layouts.py`'s builders
  (`test_ui_min_targets.py:116-157`). An empty label satisfies the two label
  checks trivially (`test_ui_min_targets.py:208-209, 274-275` both `continue`
  on a falsy label).
- **Placement.** `BuildingUI._do_place` (`building_ui.py:1915`) walks the
  selected tiles and calls `place_building(...)` at `building_ui.py:1928`,
  naming only the first tile (`:1948-1949`).
- **The colour IS the sprite column.** `SpriteAnimator.column: int = -1`
  (`engine/core/sprite_animator.py:28`) is a **sentinel meaning "no driver"**;
  `render_items` maps `-1 → RenderItem.column=None`
  (`sprite_animator.py:49`). **`0` is a real colour index and must never be
  used to mean "unset".** A building with no colour-capable art stays at `-1`.
  The building stores the **index**, not the name (plan D5,
  `planning/MasterSheetColumnsPLAN.md:69`).
- **The capability map is the host's job.** `game/main.py:596-600` builds
  `condition_art` once at boot by asking the manifest, precisely so `game/ui`
  never touches the asset layer (`game/main.py:590-595`). B1 follows that
  precedent for `{slot_key: (colour_name, …)}` (plan D6,
  `planning/MasterSheetColumnsPLAN.md:75-78`; E-37).
- **A building knows its own slot**: `Building.slot_key()`
  (`game/buildings/building.py:173`), which `apply_tier_stats` uses to rewrite
  the animator's slot (`building.py:189-191`). `ConstructPreview.__init__`
  already builds a temp building for its stats (`building_ui.py:317`), so the
  modal can resolve its own slot key with no new import.

### 1.2 Required behaviour

1. **Colour-capable only (D6).** `ConstructPreview` receives the host's
   capability map (see §3's B1 contract) and looks up the temp building's
   `slot_key()`. Absent, or fewer than 2 colours ⇒ **no swatch widgets are
   created at all**, no ids are registered, nothing is drawn, and
   `handle_click` behaves exactly as it does today. Degrade quietly — the
   `condition_art` / VFX-master-sheet rule, never a placeholder.
2. **N square swatches**, one per declared colour name, `widgets.Button(rect,
   "")` — no label. Registered in the `ids` dict so `skinning.apply` sees them.
3. **Selection.** The preview opens on the colour B1's roll would produce…
   **it does not.** The modal opens on **index 0** (see §2.4 for why) and
   `chosen_column` reports the player's live pick. Clicking swatch *i* sets
   `chosen_column = i`; the swatch row redraws with *i* marked selected on the
   very next `submit`, i.e. the same frame the click is consumed.
4. **The placed building carries the pick.** `_do_place` applies
   `preview.chosen_column` to every building it places in the batch (§3's B1
   contract fixes exactly how). A preview with no swatches leaves the column
   entirely alone — B1's roll stands.
5. **Hit order.** Swatches are hit-tested in `handle_click` **before** the
   `name_rect` branch (`building_ui.py:424`) and return a new action string
   `"color"`. They sit in the band directly above the name box, so a
   later test would let a near-miss click fall into "click to name".
6. **Draw order.** Swatches draw inside `submit`'s BUTTON block
   (`building_ui.py:458-469`), never the text block. The selected-swatch marker
   (a 1px ring) draws immediately after its own button — the sanctioned
   "highlight ring after its own button" exception already recorded in
   `game/ui/CLAUDE.md` ("HUD submission order", the `overlays.py
   MapOverlays.submit_buttons` precedent).
7. **No existing rect moves.** The panel stays 170×150, `btn_y` stays
   `y + ph - 24`, the stat list stays at `y + 69` with step 11. Any change to
   those would require regenerating `data/ui/screen_defaults.json`, which is
   out of scope for this phase.

---

## 2. Architecture plan

### 2.1 One reusable row object, not inlined code

B3 adds the same row to the `BuildingUI` **upgrade** panel
(`_build_upgrade` / `_layout_upgrade_rows`, `building_ui.py:~1394-1413`). So B2
builds a small module-level helper class in `game/ui/building_ui.py` and
`ConstructPreview` merely owns an instance of it. **B3 reuses it; B3 must not
re-implement it.** Exact signature in §3.2.

### 2.2 Vertical placement — the arithmetic

Font metrics (from `data/ui/fonts.json` + `game/ui/CLAUDE.md`'s "row step"
section): `layout_h("sm") == 11`, `layout_h("md") == 13`.

The modal's occupied bands, all relative to the panel's `y`:

| band | y range | source |
|---|---|---|
| title (`lg`, centred) | `y+6` … ~`y+22` | `building_ui.py:471` |
| cost (`md`) | `y+22` … `y+35` | `building_ui.py:473-475` (`y+22 + 13`) |
| **FREE** | **`y+35` … `y+48`** | — |
| "Name:" label (`sm`), LEFT of `x+8` only | `y+38` … `y+49` | `building_ui.py:476-477` |
| name box + dice | `y+48` … `y+63` | `building_ui.py:330-332` |
| stat list (5-row worst case) | `y+69` … `y+124` | `building_ui.py:485-496` |
| CONFIRM/CANCEL row | `y+126` … `y+143` | `building_ui.py:342` |

**The swatch row goes at `top = y + 36`, height 12, i.e. `y+36 … y+48`.**

- Above: the cost line's last pixel row is `y+34` (`y+22` + `layout_h("md") 13`
  → occupies `y+22..y+34`), so there is **1px of clearance**.
- Below: the name box's top edge is `y+48`; a 12px-tall rect at `y+36`
  occupies `y+36..y+47` inclusive, so it **exactly abuts** the box and never
  overlaps it.
- It is **entirely above `y+69`**, so the stat list does not move and the
  `y+124` vs `y+126` 2px slack at `building_ui.py:485-496` is untouched.
- The only thing sharing the band is the `"Name:"` label at `x+8`, which is
  ~5 glyphs at `sm` — the row is **right-aligned to `x + pw - 8`** and stops
  well clear of it (see §2.3).

`12` is the UR-5 floor exactly (`test_ui_min_targets.py:55`), and 12 is the
largest square that fits the 13px band. Do not use 11 (fails the gate) and do
not use 13 (overlaps the name box).

### 2.3 Horizontal placement

`SIZE = 12`, `GAP = 2`, right-aligned to `right = x + pw - 8` (the panel's own
8px gutter, the same one `name_rect` and the button row use).

- 4 colours ⇒ `4*12 + 3*2 = 54px`, so the row spans `x+108 … x+170-8`.
- The left bound is `left = x + 8 + text_size(T("building.preview.name_label"),
  "sm")[0] + 4` (`text_size` is already imported, `building_ui.py:73`;
  the string is `"Name:"`, `data/ui/strings.json`). Available ≈ 124px.
- The registry schema permits up to 16 colour names (`docs/handoffs/
  section-S1.md:11-12`), which would need 222px and does not fit. The helper
  therefore clamps: `max_fit = max(0, (avail + GAP) // (SIZE + GAP))` and lays
  out only the first `max_fit` colours. **Shipped sheets declare 4**, so this
  branch is dead today — see §4's open question.

### 2.4 Which colour the modal opens on

The modal opens on **index 0** and `chosen_column` is `0` until the player
clicks. Reason: `ConstructPreview` is pure `game/ui` and has no rng and no
building yet — B1's roll happens inside `place_building`, which does not run
until CONFIRM. Having the modal roll its own would duplicate B1's rng seam in a
second package. The consequence is deliberate and accepted: **opening the
confirm modal on a colour-capable building and confirming without touching a
swatch places colour 0, not a random colour.** Flag it in the report; do not
"fix" it by rolling in the UI. (See §4's open question — this is the one
place B2's behaviour visibly narrows B1's.)

### 2.5 The colour lookup — ONE function, for B3 to swap

```python
def _swatch_rgb(name, ui_balance=None):
    """A colour NAME -> (r, g, b) for the swatch fill.

    B2: a hardcoded map over the SHARED PALETTE, read as ``widgets.<NAME>``
    attribute access (never an import binding — ``configure_palette``
    rebinds these at boot, widgets.py:92-104). ``ui_balance`` is accepted
    and ignored.

    B3 REPLACES THIS BODY (and nothing else) with a read of
    ``ui_balance["BuildingColors"]``, falling back to this palette map and
    then to a neutral swatch for an unknown name — plan phase B3,
    planning/MasterSheetColumnsPLAN.md:705-710.
    """
```

B2's map, from the existing palette (`widgets.py:51-79`) — the plan already
records that the palette has **no pink** and that `game/ui/overlays.py:76-89`
reuses `C_PURPLE` as "the closest existing colour to pink"
(`planning/MasterSheetColumnsPLAN.md:705-710`), so do the same here:

| colour name | B2 source |
|---|---|
| `pink` | `widgets.C_PURPLE` (documented stand-in) |
| `red` | `widgets.C_RED` |
| `purple` | `widgets.C_PURPLE` |
| `yellow` | `widgets.C_GOLD` |
| anything else | `widgets.C_PANEL_INSET` (neutral) |

The neutral fallback is what makes an unknown name degrade instead of raising,
which is the same rule B3 will keep.

`ui_balance` is threaded in NOW (both call sites already hold one:
`ConstructPreview.__init__`'s `ui_balance` parameter, `building_ui.py:300`, and
`BuildingUI._ui_balance`) purely so B3's change stays one function body.

### 2.6 Layering

Nothing here imports `engine.assets`, reads `data/`, or touches
`game/buildings` beyond what `building_ui.py` already imports
(`building_ui.py:46-64`). The capability map arrives as plain data from the
host. `game/ui` stays pygame-free.

---

## 3. File scope + shared-file contract

### 3.1 File scope (hard boundary)

**Modified — these four files and nothing else:**

- `game/ui/building_ui.py`
- `game/ui/CLAUDE.md` (one short subsection under the building-panel material)
- `tools/tests/test_hud_panel.py` — **the real test home**; `ConstructPreview`
  is constructed there (`test_hud_panel.py:164-170`) and
  `tools/tests/test_building_ui.py` **does not exist** (the plan doc names it;
  the orchestrator measured its absence). Do not create it.
- `tools/tests/test_ui_min_targets.py`

**Explicitly OUT of scope:** anything under `engine/**`, `editor/**`,
`data/**`; `game/buildings/**` and `game/main.py` (**B1 owns both**);
`tools/export_ui_layouts.py` and `tools/screen_mocks.py` (adding a
colour-capable mock there would change the exported `building_panel` widget set
and force a `data/ui/screen_defaults.json` regeneration — B3's territory, per
`planning/MasterSheetColumnsPLAN.md:711-715`).

### 3.2 The reusable swatch row — B3 codes against THIS

Add to `game/ui/building_ui.py`, module level, above `class ConstructPreview`
(`building_ui.py:295`), beside `_swatch_rgb`:

```python
class ColorSwatchRow:
    """A right-aligned row of N square colour swatches (building colour).

    Pure layout + hit-test + draw over ``widgets.Button``, factored out
    because TWO screens use it: ConstructPreview (B2) and the BuildingUI
    upgrade panel (B3). It owns no game state — the caller keeps the
    selection and feeds it back in.
    """

    SIZE = 12   # UR-5 floor exactly (tools/tests/test_ui_min_targets.py:55)
    GAP = 2

    def __init__(self, colors, left, right, top, id_prefix, ui_balance=None):
        """``colors``    - tuple of colour NAMES from the host capability map
                           (``()`` => an empty, inert row).
        ``left``/``right`` - the horizontal band, in logical px; the row is
                           RIGHT-aligned to ``right`` and clamped to the
                           first ``(avail + GAP) // (SIZE + GAP)`` colours.
        ``top``        - the row's top edge, logical px.
        ``id_prefix``  - ``"preview_color"`` (B2) / ``"upgrade_color"`` (B3);
                           widget ids are ``f"{id_prefix}_{i}"``.
        ``ui_balance`` - passed straight to ``_swatch_rgb`` (B3's data hook).
        """

    #: ``{widget_id: ("button", Button)}`` — merge into the screen's own
    #: ``ids`` dict BEFORE it calls ``skinning.apply``. Empty when inert.
    @property
    def ids(self): ...

    def __bool__(self): ...          # False when there is nothing to draw

    def hover(self, mx, my, mouse_down=False): ...
    def update(self, dt): ...

    def hit(self, mx, my):
        """The colour INDEX under the cursor, or ``None``. Never returns 0
        for a miss — 0 is a real colour (S1's sentinel rule)."""

    def submit(self, renderer, selected, anim_ms=0):
        """Draw the row. Call from the caller's BUTTON block ONLY, never the
        text block. ``selected`` is the caller's current index (``None`` =>
        none marked); the marker ring is drawn right after its own swatch."""
```

Notes binding on both phases:
- `hit` returns an **index**, never a name — D5.
- The row NEVER mutates the selection; the owning screen does. That is what
  lets B3 point it at a live building's `SpriteAnimator.column` while B2 points
  it at a pending int.
- `submit` takes `selected` as an argument rather than storing it, for the
  same reason.

### 3.3 Insertion points B2 claims in `game/ui/building_ui.py`

B3 must claim **disjoint** ones (its own are all in `BuildingUI`, from
`_build_upgrade` / `_layout_upgrade_rows` at `building_ui.py:~1394-1413`).

| # | Site | What B2 does |
|---|---|---|
| 1 | module level, just above `class ConstructPreview` (`:295`) | new `_swatch_rgb()` + `class ColorSwatchRow` (§2.5, §3.2) |
| 2 | `ConstructPreview.__init__` signature (`:300-302`) | new **keyword-only, defaulted** param `building_colors=None` — a `{slot_key: (name, …)}` mapping. Defaulted so `tools/export_ui_layouts.py`, `tools/screen_mocks.py` and `test_hud_panel.py:166` keep constructing it unchanged. |
| 3 | `ConstructPreview.__init__`, immediately after the dice button (`:331-332`) | resolve `temp.slot_key()` (`game/buildings/building.py:173`) against the map, build `self.swatches = ColorSwatchRow(...)` at `top = y + 36`, set `self.chosen_column = 0 if self.swatches else None` |
| 4 | `ConstructPreview.__init__`, the `ids` dict (`:362-368`) | `self.ids.update(self.swatches.ids)` **before** `self.skinning.apply(...)` at `:368` |
| 5 | `ConstructPreview.hover` (`:387-394`) and `.update` (`:399-404`) | forward to `self.swatches` |
| 6 | `ConstructPreview.handle_click`, inserted **between** the dice branch (`:417-423`) and the `name_rect` branch (`:424`) | `idx = self.swatches.hit(mx, my)`; `if idx is not None: self.chosen_column = idx; return "color"` |
| 7 | `ConstructPreview.submit`, inside the BUTTON block (`:458-469`), after the close button | `self.swatches.submit(renderer, self.chosen_column, anim_ms=anim_ms)` |
| 8 | `BuildingUI._do_place` (`:1915-1951`), right after the successful `place_building` call at `:1928-1930` | apply `p.chosen_column` to the freshly placed building when it is not `None` (§3.4) |

B2 does **not** touch `MovePreview` (`:509`), `_construct_click` (`:1680`)
beyond the one new keyword argument at the `ConstructPreview(...)` construction
site `:1716-1719`, or any upgrade-mode code.

### 3.4 The B1 contract this phase REQUIRES

`docs/briefs/phase-B1-colour-state.md` **did not exist when this brief was
written** (verified: `docs/briefs/phase-B1-*.md` matches only the unrelated
older `phase-B1-screen-formats.md`). **Read it first if it now exists and
reconcile the names below with what B1 actually shipped** — do not invent B1
internals, and report any mismatch upward rather than editing B1's files.

What B2 needs from B1, in precise terms:

1. **A capability map reachable by `BuildingUI` without editing
   `game/main.py`.** Shape: `{slot_key: tuple[str, ...]}` — colour NAMES in
   sheet order, so index *i* in the tuple IS master column *i*. Built once at
   boot from `engine.assets.master_registry` + the manifest
   (`game/main.py:596-600`'s `condition_art` precedent). B2 reads it, threads
   it from `BuildingUI` into `ConstructPreview` at `building_ui.py:1716`, and
   assumes **B1 already passes it to `BuildingUI`** (a `building_colors=None`
   keyword on `BuildingUI.__init__` is B2's insertion point — but the
   `game/main.py:779-780` call that supplies it is B1's line). *If B1 shipped
   no such wiring*, B2 still lands: the parameter defaults to `None`, no
   swatches ever appear in game, the tests below pass on an injected map, and
   the missing host wiring is reported as a one-line B3/orchestrator follow-up.
   **Do not edit `game/main.py` to close the gap.**
2. **A way to set a placed building's colour from `_do_place`.** Preferred:
   `place_building(..., column=None)` where `None` keeps B1's roll and an int
   overrides it. If B1 did not publish that keyword, B2 sets the column on the
   returned building instead — `building.get_component(SpriteAnimator).column
   = p.chosen_column` — which needs a `from engine.core import SpriteAnimator`
   in `building_ui.py` (`game/buildings/building.py:21` shows the same import
   is already normal one layer down). **State in your report which of the two
   you used.**
3. **`-1` stays the "no driver" sentinel** (`engine/core/sprite_animator.py:28`)
   and **`0` is a real colour**. B2 must never write `0` to mean "unset": a
   building whose slot offers no colours is left untouched by `_do_place`.

---

## 4. Exit gate + Quick Test

### Tests to write (bare minimum — do not broaden)

In `tools/tests/test_hud_panel.py`, copying the existing fixture pattern
verbatim — module-level `load_balance(FIXTURE_DATA, …)` docs
(`test_hud_panel.py:32-36`), `build_cost("defence", BUILD, 0)` and
`ConstructPreview("defence", cost, BUILD, UI, VIEW_W, VIEW_H)` exactly as
`TestConstructPreviewZOrder._preview` does (`test_hud_panel.py:164-170`), the
`RecordingRenderer` at `test_hud_panel.py:43`, and `build()` at
`test_hud_panel.py:56` for anything needing a session. The capability map is a
**literal dict in the test** keyed on the temp building's `slot_key()` — never
live `data/`:

1. A preview built with **no** capability map (today's call) has no swatch ids
   and `handle_click` over the swatch band still returns `"name"`.
2. A preview built with a **colour-capable** map has one `("button", …)` id per
   colour in its `ids`, and a click on swatch *i*'s centre returns `"color"`
   and leaves `chosen_column == i` (test at least one non-zero *i* — 0 must not
   be able to pass by accident).
3. The placed building carries the picked column: drive `_do_place` through the
   `build()` session with a preview whose `chosen_column` is set, and assert the
   placed building's `SpriteAnimator.column` equals it.
4. In `tools/tests/test_ui_min_targets.py`: one focused test that constructs a
   colour-capable `ConstructPreview` directly and asserts every swatch rect
   clears `MIN_HARD` (the module's existing walker only sees ids the exporter
   builds, and the exporter's preview has no colours — so the walker cannot
   cover these).

Nothing else. No new coverage of `ColorSwatchRow` internals, no golden-file
work, no `screen_mocks` additions.

### Exit gate

```
py tools/smoke.py
py -m pytest tools/tests/test_hud_panel.py tools/tests/test_ui_min_targets.py -x -q
```

Both must be green. **Nothing wider**: no full suite, no
`py tools/testgate.py check`, no `--affected`, no tier sweep (`-m core` /
`-m editor` / `-m meta`). The `test_guard.py` hook DENIES all four from a
subagent — the single full gate belongs to the main session at handoff
(root `CLAUDE.md` §"Test Suite Policy").

**If `test_guard` denies a command: do NOT re-issue it, do not vary the flags**
(the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command fingerprints
identically) and do not reach for the guard's escape hatch. Report the deny
text and the result it quotes back to the orchestrator and stop testing.

### Quick Test (in-game — the orchestrator or user runs this, not the coder)

`py game/main.py` → open the confirm modal on a **colour-capable** building
(one whose slot links a master sheet declaring `columns`; if none is imported
yet, say so and report the gate as tests-only). Click each swatch and watch the
preview panel's marked selection follow the cursor; CONFIRM; the placed
building stands on the board in the chosen colour. Then re-open the modal on a
building with **no** colour-capable art and confirm the row is simply absent —
no placeholder, no gap, and the name box, dice and stat list all sit exactly
where they did before.

---

## Open questions for the orchestrator (do not resolve in code)

1. **Does the modal roll, or open on 0?** §2.4 chooses index 0 because
   `game/ui` has no rng seam and B1 owns the roll. The plan block
   (`planning/MasterSheetColumnsPLAN.md:652-687`) does not say. If the intended
   feel is "the modal shows the colour you are about to get", the roll must
   move — that is a B1 change, not a B2 one.
2. **More than ~8 colours.** The schema allows 16 names
   (`docs/handoffs/section-S1.md:11-12`); only ~8 twelve-px swatches fit the
   modal band. §2.3 clamps to what fits, which makes the tail unreachable.
   Shipped sheets declare 4, so nothing is lost today, but a real answer
   (two rows / a smaller swatch / a scroll) is unowned.
3. **Where B1's capability map is handed to `BuildingUI`** — §3.4 item 1.
   Reconcile against `docs/briefs/phase-B1-colour-state.md`.
