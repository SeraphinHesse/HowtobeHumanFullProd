# Phase TU-6 — Engine sequencer + game director + guided flute chain

Source plan: `planning/TutorialPLAN.md` §3 "Phase TU-6" (goal, file list, tests,
exit gate verbatim there); architecture decisions D1/D2/D6/D7/D8 in §2. This
brief assumes **TU-1** (map markers `tutorial_flute`/`tutorial_stone` on
`TileMapDoc`; `data/tutorial/tutorial.json` + `tutorial.schema.json`) and
**TU-2** (a real painted test map) have landed. Neither TU-1's actual
committed schema/content nor a TU-5 brief exist in this repo yet at the time
of writing — see "Open questions" at the end; this brief is self-consistent
and names the exact contract TU-6 needs from each.

## 1. Behavioral spec

Round-1 guided chain, first (economy) placement only:

1. On `build_gameplay()` (new game), a message box appears immediately:
   text #1 verbatim from `planning/TutorialPLAN.md` §1 ("You need love to
   create…"), with a **Skip tutorial** button visible only when the script
   says `skippable` (D7, plan §2 D7). Modelled on
   `game/ui/game_over.py:27-84` (construct → `layout()` → `update()` →
   `hit()` → `submit()`, `ScreenSkinning` ids/ `is_visible`/`button_kwargs`
   throughout — `game/ui/game_over.py:36-50` is the ids/`layout()` shape to
   copy, `:52-61` the `update`/`hit` shape, `:63-84` `submit()`).
2. Dismissing the message (a Continue-style click, or Skip) starts the guided
   chain: a **white diamond outline** on the `tutorial_flute` marker tile,
   drawn via `submit_tile_diamond` (`game/ui/widgets.py:187-192`) with a new
   white constant, **until the player clicks that tile**. Any other click
   (any other tile, HUD, panel) is rejected — the panel never opens for it.
3. Clicking the flute tile opens the construct panel exactly as it does today
   (`game/ui/building_ui.py:406-424` `open_for_tile` →
   `game/ui/building_ui.py:480-…` `_build_construct`, unchanged) — but a
   **white box** now outlines the Musician card
   (`game/ui/building_ui.py:480-520`'s `self.cards` list, `(btype, btn)`
   tuples with `btn.rect`, `game/ui/building_ui.py:316`) until the player
   clicks that specific card. Clicking any other card, closing the panel, or
   clicking elsewhere is rejected.
4. Selecting the Musician card opens `ConstructPreview`
   (`game/ui/building_ui.py:700-716` `_construct_click`) — a **white box**
   now outlines its `confirm_btn`
   (`game/ui/building_ui.py:146-153`/`161`, `preview_confirm_btn` id) until
   Confirm is clicked. Cancel/close/name-edit/dice are rejected (name typing
   is optional cosmetic — see §2 open item on whether it stays allowed).
5. Confirming places the building (`game/ui/building_ui.py:789` `action ==
   "confirm"` branch, `place_building` — untouched, D6: "the gate sits in the
   UI layer, not the placement seam"). Once
   `Tutorial.economy_buildings_required` (D5, `core.json`, default 1) economy
   buildings are placed, **all other input stays rejected except End Turn**,
   which gets the same white-box treatment around `hud.end_turn.rect`
   (`game/ui/hud.py:151` — an existing public attribute; no Hud change
   needed).
6. Skip (button on message box #1, only when `skippable`) ends ALL gating
   immediately: highlights vanish, every click/End Turn works normally, no
   further message boxes this run (TU-7 territory, out of scope here).
7. A map with no `tutorial_flute` marker (e.g. an old/unpainted map) must
   never crash: the tutorial auto-skips with one logged warning, and the game
   is fully playable from the first frame (input never locked).

Input choke points (D6, plan §2): the click-consume ladder in
`game/main.py:377-441` `handle_world_click` (the `panel.handle_click()` calls
at `game/main.py:410` and `:424`, and the tile-pick branch at
`game/main.py:429-434`), and `game/core/session.py:228-254` `end_turn()`
(second choke point, phase-advance calls). `place_building`
(`game/buildings/registry.py`) stays untouched, confirmed by plan §2 D6.

## 2. Architecture plan

### `engine/tutorial.py` (pure, no pygame, **no game vocabulary** — engine hard
rule, `engine/CLAUDE.md:97-98`: "No game-specific names in the engine (no
'raider', no 'flute_player')")

```python
@dataclass(frozen=True)
class Step:
    id: str
    message: str | None = None       # opaque; the director/script decides
                                      # whether this IS display text or an id
    highlight: tuple[str, ...] = ()  # opaque target ids
    advance_on: str | None = None    # opaque event id that ends this step
    allow: tuple[str, ...] = ()      # opaque action ids permitted this step
    flags: dict = field(default_factory=dict)

class TutorialSequencer:
    def __init__(self, steps, *, skippable=True): ...
    @property
    def active(self) -> bool: ...      # not skipped, not past the last step
    @property
    def finished(self) -> bool: ...    # skipped OR past the last step
    @property
    def current(self) -> Step | None: ...
    @property
    def skippable(self) -> bool: ...
    def advance(self, event_id) -> bool:
        """Advance past `current` iff `current.advance_on == event_id`.
        No-op (returns False) if finished, if current.advance_on is None, or
        the id doesn't match — an unrelated event never advances the chain."""
    def skip(self) -> None:
        """Terminal, only if `skippable`; a no-op otherwise (defensive: no UI
        should ever call this when the script disallows it, but the engine
        does not trust the caller)."""
    def allows(self, action_id) -> bool:
        """True when finished (D6 zero-overhead path) or when action_id is in
        current.allow; False otherwise."""
    def highlight_ids(self) -> tuple[str, ...]: ...  # () when finished
    def message_id(self) -> str | None: ...          # None when finished
    def flags(self) -> dict: ...                      # {} copy when finished
```

Knows nothing about tiles, buildings, cards, End Turn, or love — every id
above is an opaque string chosen by the data script and interpreted only by
`game/tutorial/director.py`. This mirrors `video_playback.py`'s "pure
clock the caller gives game meaning to" shape (`engine/CLAUDE.md:82-87`).

### `game/tutorial/director.py` (binds opaque ids to real things)

```python
class TutorialDirector:
    def __init__(self, data_dir, map_doc, tutorial_balance): ...
        # loads data/tutorial/tutorial.json (TU-1's loader/schema), builds a
        # list[engine.tutorial.Step] from it, reads map_doc.tutorial_flute /
        # .tutorial_stone (nullable {"col","row"} dicts, the camera_start
        # pattern — D1). If the script is missing/invalid OR
        # map_doc.tutorial_flute is None: log ONE warning
        # ("tutorial: <reason> — auto-skipping"), build an EMPTY sequencer and
        # call .skip() immediately, and set self.active = False. NEVER raises.
    def allows(self, action) -> bool: ...
        # action: ("tile", col, row) | ("card", building_type) | ("confirm",)
        # | ("end_turn",) | ("other",). Resolves to an opaque id (comparing
        # col/row against the bound flute-tile marker, "card:<type>", etc.)
        # and delegates to sequencer.allows(). True immediately if
        # self.sequencer.finished (D6 zero-overhead path).
    def allows_end_turn(self) -> bool: ...   # allows(("end_turn",)) — the
                                              # exact callable Session.end_turn
                                              # will hold (see §3).
    def on_tile_clicked(self, col, row) -> None: ...   # feeds
        # "tile_clicked:flute" into sequencer.advance() iff (col,row) is the
        # bound flute marker
    def on_card_selected(self, building_type) -> None: ...  # feeds
        # f"building_selected:{building_type}"
    def on_building_placed(self, category) -> None: ...  # feeds
        # f"building_placed:{category}" ("economy"/"defence" — category comes
        # from the placed building's family, duck-typed the way
        # building_ui.py:69-99 `_building_stats` duck-types by hasattr)
    def on_message_dismissed(self) -> None: ...  # feeds "message_dismissed"
    def skip(self) -> None: ...                  # sequencer.skip()
    @property
    def message_visible(self) -> bool: ...       # sequencer.message_id() is
                                                  # not None
    def message_text(self) -> str | None: ...
    def skippable(self) -> bool: ...
    def highlight_targets(self) -> tuple[str, ...]: ...  # passthrough for the
        # overlay-submit code in main.py to resolve into rects
```

The director is where "flute"/"musician"/"economy" vocabulary lives — never
in `engine/tutorial.py`. This is the exact D2 boundary the brief was asked to
call out for the coder: **if the `coder` agent (not `engine-coder`, since
this phase spans packages) is tempted to add a check like `if target ==
"flute"` inside `engine/tutorial.py`, that is a layering violation — it goes
in `director.py` instead.**

### `game/ui/tutorial_message.py` (D7 — copies `game/ui/game_over.py`'s shape
exactly: `SCREEN_ID`, `ids` dict, `layout()`, `update(dt, mx, my,
mouse_down)`, `hit(mx, my)`, `submit(renderer, text, view_w, view_h)`)

- ids: `backdrop`, `message_text` (label — the copy is NOT game-state, so per
  `game/ui/CLAUDE.md`'s "every static title is an id too" convention its
  `label` IS an override field, but this screen's actual text comes from the
  director/script at runtime, not a fixed literal — treat it like
  `game_over.py`'s dynamic stat lines: NOT id-overridable text, only
  rect/font/color are), `btn_continue`, `btn_skip` (present in `ids` always;
  visibility gated by `is_visible`/script `skippable`, same pattern as
  `game_over.py`'s single button and `ConstructPreview`'s conditional
  `cancel_btn`, `game/ui/building_ui.py:163-164`).
- `hit()` returns `"continue"` / `"skip"` / `None`.
- Host wiring: constructed once per `build_gameplay()`
  (`game/main.py:276-312`), alongside `gp["panel"]`/`gp["hud"]`, sharing
  `shell.skinning` (the existing convention, `game/main.py:287-295`).

### `data/ui/screens/tutorial_message.json` — new, starts `{}` (every screen
override file "started life EMPTY", `data/CLAUDE.md` "UI screen data"
section), matching the other 13.

### Highlight rendering (D8 — reuses existing primitives, no new render-backend
work)

- **Tile highlight**: `submit_tile_diamond` (already exists,
  `game/ui/widgets.py:187-192`) with a new white constant —
  `C_TUTORIAL_HIGHLIGHT = (255, 255, 255)` in `game/ui/widgets.py` beside
  `C_HIGHLIGHT`/`C_HIGHLIGHT2` (`game/ui/widgets.py:58-59`).
- **UI box highlight** (card / Confirm / End Turn): **no existing HudRect
  outline helper for a UI box was found** — `submit_panel`
  (`game/ui/widgets.py:164-175`) draws a filled panel with a 1px border, not
  a highlight ring around an existing widget. Add one new pure function,
  next to `submit_tile_diamond_fill` (`game/ui/widgets.py:195-205`):
  ```python
  def submit_ui_box_highlight(renderer, rect, color=C_TUTORIAL_HIGHLIGHT,
                              width=3):
      """A highlight ring around a UI element (card / Confirm / End Turn) —
      the tutorial guided-chain highlight (D8). Plain HUD-space rect."""
      renderer.submit_hud(HudRect(rect, color, width=width))
  ```
  `HudRect` is already imported in `widgets.py:18`. This is the "new white
  constants" + "no new render-backend work" D8 requires.

### `game/ui/building_ui.py` exposure (the flagged risk item — see explicitly
below)

Two small **read-only, additive** methods, added right after `dismiss()`
(`game/ui/building_ui.py:388-404`), before `open_for_tile`
(`game/ui/building_ui.py:406`):

```python
# -- TU-6: tutorial highlight rect queries (read-only, additive) ----------
def card_rect(self, building_type):
    """Screen rect of the construct-mode card for `building_type`, or None
    if not currently shown. Read-only — never mutates panel state."""
    if self.mode != "construct":
        return None
    for btype, btn in self.cards:
        if btype == building_type:
            return btn.rect
    return None

def confirm_rect(self):
    """Screen rect of the open ConstructPreview's CONFIRM button, or None
    when no preview is open."""
    return self.preview.confirm_btn.rect if self.preview is not None else None
```

No change to `self.cards`, `_build_construct`, `_construct_click`, or any
existing method — these two additions read state that already exists
(`self.cards`, `self.preview.confirm_btn`). Nothing about card/Confirm
selection *events* needs a new hook either: `director.on_card_selected` /
`on_building_placed` are called from `game/main.py`, not from inside
`building_ui.py` (see §3 exact insertion points) — so `building_ui.py`
itself gains **only these two getters**, nothing else. This satisfies the
plan's own risk note (§4: "if it turns invasive, fall back to the director
reading the panel's existing `ids`/geometry") — in practice it turned out
NOT invasive: everything the director needs (`self.cards`, `self.preview`)
was already a plain readable attribute; the two getters are a thin
convenience, not new state or a new hook system. **No End Turn hook is
needed in `game/ui/hud.py` at all** — `hud.end_turn.rect`
(`game/ui/hud.py:151`) is already a public attribute.

### Gating shape (D6)

`allows(action)` is checked at exactly two `game/main.py` sites (the tile
click and the `panel.handle_click()` calls) and one `session.py` site
(`end_turn()`), matching the plan's own file-scope note verbatim ("input
whitelist around `panel.handle_click()`; director event hooks at the
tile-click site"). Blocked actions are **silently swallowed** (consumed,
no-op) — never an error, never a log spam per-click (only the one map-less
warning at construction time).

## 3. File scope + shared-file contract

**New files** (no conflicts):
- `engine/tutorial.py`
- `game/tutorial/__init__.py`, `game/tutorial/director.py`
- `game/ui/tutorial_message.py`
- `data/ui/screens/tutorial_message.json`
- `tools/tests/test_tutorial_engine.py`, `tools/tests/test_tutorial_director.py`

**Modified files — exact insertion points:**

### `game/main.py`

1. **`build_gameplay()`** (`game/main.py:276-312`): after
   `gp["panel"] = BuildingUI(...)` (`:288-289`), add construction of the
   director and message screen:
   ```python
   gp["tutorial"] = TutorialDirector(data_dir, map_doc, core_balance["Tutorial"])
   gp["tutorial_message"] = TutorialMessageScreen(view_w, view_h,
                                                  skinning=shell.skinning)
   gp["world"].session.tutorial_gate = gp["tutorial"].allows_end_turn
   ```
   (last line — the session hook, see the `session.py` section below).
   `teardown_gameplay()` (`:314-323`) gets `"tutorial"`, `"tutorial_message"`
   added to the tuple of keys reset to `None` (`:317-318`).
   Add `gp = {"world": None, …}` two new keys at `:270-274` too
   (`"tutorial": None, "tutorial_message": None`).

2. **`handle_world_click()`** (`game/main.py:377-441`): insert a new branch
   immediately after the `GAME_OVER` early-return (`:383-387`), **before**
   the `# -- 10H: cheat menu` comment (`:388`):
   ```python
   tutorial = gp["tutorial"]
   if tutorial.message_visible:
       result = gp["tutorial_message"].hit(mx, my)
       if result == "skip":
           tutorial.skip()
       elif result == "continue":
           tutorial.on_message_dismissed()
       return
   ```
   This is the highest-priority branch bar GAME_OVER — the message box
   consumes every click while visible, matching "all other input rejected".

3. **`panel.handle_click()` whitelist** — both call sites,
   `game/main.py:409-412` (preview branch) and `game/main.py:424-426`
   (normal branch), wrapped through one new local helper defined just above
   `handle_world_click` (or as its first statement) so the two sites share
   one gate:
   ```python
   def _tutorial_allows_panel_click(mx, my):
       """True when the tutorial is inactive/finished, OR the click lands on
       a target the current step allows (musician card / Confirm)."""
       tutorial = gp["tutorial"]
       if tutorial.sequencer_finished:  # fast path, D6
           return True
       panel = gp["panel"]
       if panel.preview is not None:
           if panel.preview.confirm_btn.hit(mx, my):
               return tutorial.allows(("confirm",))
           return True  # cancel/close/name box: not gated (see open Q below)
       if panel.mode == "construct":
           for btype, btn in panel.cards:
               if btn.hit(mx, my):
                   return tutorial.allows(("card", btype))
           return True  # clicking the panel body/close, not a card
       return True  # unlock/upgrade/base_info modes: untouched by TU-6
   ```
   then each site becomes `if _tutorial_allows_panel_click(mx, my) and
   panel.handle_click(...): ...` (preview branch keeps its unconditional
   `return` after; normal branch keeps its `if …: return`). When the click IS
   a card/Confirm hit but is NOT allowed, the function returns False, so
   `panel.handle_click()` is skipped entirely (the click is fully swallowed —
   consistent with "clicking anywhere else does nothing").
   Immediately **after** a successful `panel.handle_click()` that resulted in
   a card selection or a placement, feed the director:
   `tutorial.on_card_selected(btype)` (right after the preview opens inside
   `_construct_click` — **but per the "building_ui.py gains no new hook"
   decision above, this call lives in `main.py`, not inside
   `building_ui.py`**: after `panel.handle_click(...)` returns True while
   `panel.mode == "construct"` and `panel.preview is not None` — i.e. a card
   was just selected this call — call `tutorial.on_card_selected(panel.preview.building_type)`.
   Similarly, `tutorial.on_building_placed(category)` fires after a
   `panel.handle_click()` call that just closed the preview (placement
   succeeded) — `category` from `building_ui.CATEGORY_OF[btype]` or
   duck-typed off the placed building the same way
   `game/ui/building_ui.py:69-99` duck-types stats; **implementer's call**
   which is simpler, flag in report if it needs a third small
   `building_ui.py` getter (e.g. `panel.last_placed_category`) — still
   additive, still fits the risk note's "if it turns invasive" escape hatch.

4. **Tile-click site** (`game/main.py:429-434`, inside the `BUILDING` phase
   branch): wrap the existing `update_selection(tile, shift, session)` call:
   ```python
   if session.state.phase == GamePhase.BUILDING:
       tile = tile_at_screen(world.tile_map, cs, mx, my)
       if tile is not None and not gp["tutorial"].allows(
               ("tile", tile.col, tile.row)):
           return  # tutorial: reject every tile but the bound marker
       if tile is not None:
           gp["tutorial"].on_tile_clicked(tile.col, tile.row)
       shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
       update_selection(tile, shift, session)
   ```

5. **Overlay/message submits** — two insertion points in the render block
   (`game/main.py:791-833`):
   - Tile highlight (world-space): right after
     `gp["floaters"].submit_lightning(renderer, cs, world.scene)`
     (`:805`) and **before** `gp["panel"].submit(renderer, session)`
     (`:806`), matching the existing "10J: … world overlay, before the
     panel's selection highlights" precedent comment at `:799-800`:
     ```python
     for col, row in gp["tutorial"].tile_highlight_targets():  # 0 or 1 tiles
         widgets.submit_tile_diamond(renderer, col, row, widgets.C_TUTORIAL_HIGHLIGHT)
     ```
   - UI box highlights + message box (screen-space): after
     `gp["hud"].submit(renderer, session, view_w, view_h, hover_cost=…)`
     (`:816-817`) and **before** `gp["game_log"].submit(renderer, view_h)`
     (`:818`):
     ```python
     for rect in gp["tutorial"].ui_highlight_rects(gp["panel"], gp["hud"]):
         widgets.submit_ui_box_highlight(renderer, rect)
     if gp["tutorial"].message_visible:
         gp["tutorial_message"].submit(renderer, gp["tutorial"].message_text(),
                                       view_w, view_h)
     ```
     `ui_highlight_rects` is a small director helper that resolves each
     `highlight_targets()` id starting with `"card:"`/`"confirm"`/`"end_turn"`
     into a rect via `panel.card_rect(...)`/`panel.confirm_rect()`/
     `hud.end_turn.rect`, skipping any that resolve to `None` (panel not in
     the right mode yet — never crashes mid-transition).

### `game/ui/building_ui.py`
Two getters only — see §2 above. Insertion point: immediately after
`dismiss()` ends (`game/ui/building_ui.py:404`), before `open_for_tile`
(`:406`).

### `game/ui/widgets.py`
- `C_TUTORIAL_HIGHLIGHT = (255, 255, 255)` beside `C_HIGHLIGHT`/`C_HIGHLIGHT2`
  (`game/ui/widgets.py:58-59`).
- `submit_ui_box_highlight` function, inserted right after
  `submit_tile_diamond_fill` ends (`game/ui/widgets.py:205`), before
  `submit_bar` (`:207`).

### `game/core/session.py` — **TU-6's insertion, distinct from TU-5's**

- `__init__` (`game/core/session.py:44-75`): add one new attribute right
  after `self.occupancy = occupancy` (`:58`):
  ```python
  # TU-6: optional callable, host-set (BuildingUI/on_build_vfx precedent) —
  # allows()->bool gate consulted by end_turn(). None (default) = always
  # allowed (a bare Session built by a logic test never gates).
  self.tutorial_gate = None
  ```
- `end_turn()` (`game/core/session.py:228-254`): insert the gate check
  **immediately after** the existing early-return guard
  (`:235-236`, `if st.state != GameState.GAMEPLAY or st.phase !=
  GamePhase.BUILDING: return`) and **before** `self.tilemap.set_round(...)`
  (`:237`):
  ```python
  if st.state != GameState.GAMEPLAY or st.phase != GamePhase.BUILDING:
      return
  if self.tutorial_gate is not None and not self.tutorial_gate():
      return                                    # <-- TU-6 insertion
  self.tilemap.set_round(st.round_num)
  ...
  ```
  **TU-5 reconciliation flag**: `docs/briefs/phase-tu-5-cutscene-playback.md`
  does not exist yet at the time of writing this brief, and the plan's own
  dependency note says TU-5 and TU-6 are mutually independent (both depend
  only on TU-1) — so whichever lands second must manually merge into the
  other's edited `end_turn()`. Per plan §3 TU-5, its edit is "sets a
  `pending_cutscene` request **before** `spawner.begin_round()`" — that
  insertion point is `game/core/session.py:238` (right before the
  `self.spawner.begin_round(...)` call), which is **below** TU-6's insertion
  (between the guard and `set_round`) and does not overlap it textually, but
  **the orchestrator must serialize these two phases' `end_turn()` diffs**
  (whichever coder branch merges second resolves the trivial adjacency
  conflict) rather than parallelizing them blind.

### `game/CLAUDE.md` (router)
Add a new row to the "Layout & domains" table (`game/CLAUDE.md:26-32`):
`| tutorial/ | game/CLAUDE.md (this section) | TutorialDirector — binds the
engine sequencer to real tiles/cards/buttons |` — plus a short new
subsection (mirroring the "Host conventions" numbered-phase style already
used) documenting: the director's construction site (`build_gameplay`), the
two `main.py` gating sites, the `session.tutorial_gate` hook, and the D6
zero-overhead contract ("inactive/skipped/finished tutorial costs one
`finished` bool check per gated call site"). This is a **new subsection**,
independent of whatever TU-5 or TU-7 append to this same file — the
orchestrator should ensure they land as separate subsections, not
overlapping edits to the "Host conventions" numbered list itself.

### `engine/CLAUDE.md` (router)
Append a **new** "Top-level modules" bullet for `tutorial.py`, styled like
the existing `video_playback.py` entry (`engine/CLAUDE.md:82-87`) — e.g.
after the `video_playback.py` bullet, before "## Hard rules"
(`engine/CLAUDE.md:89`). **This is a separate, new bullet — TU-1 already
appended its own tilemap-marker note to the `tilemap.py` bullet
(`engine/CLAUDE.md:33-44` per plan §3 TU-1's file list); TU-6's addition
must not touch that bullet, only add a new one for `tutorial.py`.**

### `conftest.py`
Add to `TIERS` (`conftest.py:36-…`), alphabetically among the `core` entries
(`conftest.py:62-…`, e.g. near `test_tiers`/`test_theme_data` alphabetically
between existing keys):
```python
"test_tutorial_director": "core",
"test_tutorial_engine": "core",
```

## 4. Exit gate + Quick Test

**Exit gate**: `py tools/smoke.py` then `py tools/testgate.py check` →
`GATE PASS` (zero failures, full run — this is not a mid-task
`--affected` check).

**Live Quick Test** (`py game/main.py`, on a map with painted
`tutorial_flute`/`tutorial_stone` markers per TU-2 — e.g. the committed
`first_light` map once TU-2 paints it, or any map TU-2's Quick Test used):
1. Start a new game → message box #1 appears immediately, showing text #1,
   with a Skip button (assuming the shipped script's `skippable: true`).
2. Click anywhere else on screen (HUD, empty world tile, End Turn) → nothing
   happens; the message box stays up.
3. Dismiss the message box → a white diamond appears on the flute marker
   tile; clicking any other tile does nothing.
4. Click the flute tile → the construct panel opens with a white box around
   the Musician card; clicking any other card (or the panel's Close) does
   nothing.
5. Click the Musician card → the naming modal opens with a white box around
   CONFIRM; clicking Cancel/typing a name/clicking elsewhere does nothing
   (per the open question below on whether name-typing is meant to stay
   locked — verify against whichever behavior the coder implements and
   confirm it matches "all other input rejected" or flag the divergence).
6. Click CONFIRM → the Musician is placed; the End Turn button gets a white
   box outline (since `economy_buildings_required` defaults to 1).
7. Start a second new game and click **Skip** on message box #1 immediately
   → no highlights ever appear, every click/End Turn works normally from the
   first frame.
8. (Regression) On a map with no painted tutorial markers (any pre-TU-2 map,
   if one still exists, or a temp map with both markers `null`): new game
   boots straight to normal, ungated play — no message box, no crash, one
   warning line in the console/log.

## Open questions for the orchestrator / a human

- **`building_ui.py` coupling risk (flagged explicitly, per the task)**: in
  this design it turned out **NOT invasive** — `card_rect`/`confirm_rect` are
  two pure getters over already-existing public state (`self.cards`,
  `self.preview.confirm_btn`), no new fields, no new events raised from
  inside `building_ui.py` itself (the director's `on_card_selected`/
  `on_building_placed` calls are made from `game/main.py`, reading
  `panel.mode`/`panel.preview` from the outside — see §3.3). If the coder
  finds they need a third getter (e.g. `panel.last_placed_category` to avoid
  a `main.py`-side duck-type of the placed building), that is still within
  the "minimal, additive" budget the plan's risk note allows — only escalate
  if the coder needs to change `_construct_click`/`open_for_tile` control
  flow itself, not just add a read-only accessor.
- **Exact `data/tutorial/tutorial.json` step schema** is owned by TU-1 and
  was not available to read while writing this brief (TU-1 has not actually
  landed in this repo yet, though the task asked this brief to assume it
  has). §2's `Step`/director field names (`message`/`highlight`/
  `advance_on`/`allow`/`flags`) mirror the plan's own D2/D3 wording verbatim,
  so they should match, but the coder must diff against TU-1's real committed
  schema before trusting the loader code in this brief literally — adapt the
  loader, never `engine.tutorial.Step`'s shape (D2 is the invariant, not the
  loader).
- **TU-5/TU-6 both edit `end_turn()` independently** (flagged above in §3) —
  no TU-5 brief exists yet to reconcile against; the orchestrator should
  either sequence TU-5 before TU-6 (or vice versa) rather than dispatching
  both in parallel, or explicitly assign one of the two coders the merge.
- **Should ConstructPreview name-typing/dice stay locked during the guided
  chain?** The goal text only calls out "white box on Confirm", not an
  explicit ban on naming; §3.3's `_tutorial_allows_panel_click` above allows
  name-box/dice clicks through unconditionally (treats them as cosmetic, not
  gated) while still requiring the actual placement click to land on
  Confirm. If the intent is stricter ("all other input rejected" taken
  literally, including the name box), that is a one-line change to the same
  helper — flagged for a human/orchestrator confirmation rather than
  guessed at silently.
- **`Tutorial.economy_buildings_required` > 1**: TU-6's chain as specified
  only forces ONE placement via the painted marker. If the shipped balancing
  default is ever changed above 1, the "End Turn highlighted once
  `economy_buildings_required` is met" behavior needs the director to count
  ALL economy buildings placed this run (not just the marker one) — the
  `on_building_placed("economy")` hook as designed already generalizes to
  this (it fires on every economy placement, not just the guided one; the
  director keeps its own counter and only lights up End Turn once the count
  is reached), but this repo's default is 1 so TU-6's Quick Test cannot
  exercise the >1 path — noted, not blocking.
