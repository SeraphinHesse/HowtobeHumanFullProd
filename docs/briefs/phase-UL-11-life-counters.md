# Phase UL-11 — Three life counters with real states

Section S4 of `planning/UiLayeredWidgetsPLAN.md`. Depends on S2 (layers/states
plumbing, landed) and S3 (editor wiring, landed). Builds alongside UL-9/UL-10
(hit resolver + click routing) but touches a disjoint code region — see §3.

## 1. Behavioral spec

- **D10** (`planning/UiLayeredWidgetsPLAN.md:125-129`): "The three life counters
  are three id'd widgets, not one repeated draw. `life_1`/`life_2`/`life_3` join
  `hud.py`'s `ids` dict as ordinary holders, each carrying its own layer stack,
  so the designer positions and skins them individually. `lives_text`/
  `icon_lives` stay (a numeric readout is still useful and removing an id
  breaks the on-disk contract)."
- Plan phase text (`planning/UiLayeredWidgetsPLAN.md:556-590`): three
  individually placeable, individually skinnable counters. State 1 = alive
  (looping animation), State 2 = transition (the death animation, plays once),
  State 3 = dead (static), resolved from `RunState.base_lives` plus the
  existing life-lost signal. **Scope note**: this phase builds the death STATE
  only — the screen where the counters fly to centre and scale up on loss is
  explicitly out of scope (`planning/UiLayeredWidgetsPLAN.md:619-631`, "The
  life-loss centre screen" row).
- Today's lives readout: `Hud._icon_lives` (`game/ui/hud.py:294-295`) — a
  single static-skinned panel — and `Hud._lives_text`
  (`game/ui/hud.py:265-267`), a numeric label (`submit_label(...,
  count=st.base_lives)` at `game/ui/hud.py:551`). Both are id'd in
  `_layout_readouts`'s second `ids.update(...)` pass
  (`game/ui/hud.py:391-405`, keys `lives_text`/`icon_lives` at
  `game/ui/hud.py:398,404`). **Both stay exactly as-is** — UL-11 adds three
  NEW ids beside them, it does not touch or replace these two lines.
- Life count source: `RunState.base_lives` (`game/core/game_state.py:25`),
  decremented in `Session.on_base_hit` (`game/core/session.py:629`,
  `st.base_lives -= 1`), guarded by the tutorial free-loss waiver
  (`game/core/session.py:626-629`) — a waived hit changes nothing UL-11 cares
  about, because `base_lives` does not move.
- The existing life-lost ledger: `RunState.life_lost_events`
  (`game/core/game_state.py:122`, comment `game/core/game_state.py:114-121`)
  — "one entry (the round number) appended by `Session.on_base_hit` at the
  moment a life is actually CHARGED... at most one entry per round can ever
  exist by construction" (`game/core/session.py:634`,
  `st.life_lost_events.append(st.round_num)`). It is drained by
  `Effects.spawn_life_lost_events` (`game/ui/effects.py:1437-1448`, clears the
  list at line 1447) into the "YOU / LOST 1 LIFE" banner's fade timer.
- **Load-bearing finding — a frame-ordering hazard that rules out reading this
  ledger from `Hud` directly.** `game/main.py:1765` calls
  `gp["floaters"].spawn_boss_events(session.state)` (which internally calls
  `spawn_life_lost_events`, `game/ui/effects.py:1429`, and clears
  `state.life_lost_events` at line 1447) **before** `game/main.py:1799` calls
  `gp["hud"].update(...)`. Both run once per frame, in that fixed order. If
  `Hud` waited to read `state.life_lost_events` inside its own `update()`, the
  ledger would ALREADY be empty on the exact frame the loss happened — the one
  frame that matters. §2 below resolves this without touching `main.py`'s call
  order (out of file scope, and reordering floaters' frame risks other floater
  behaviour this phase has no mandate to touch).
- Per-state appearance machinery already exists (S2, D9): `ScreenSkinning.
  state_of(self, widget)` (`game/ui/skinning.py:169-182`) resolves a widget's
  state by calling `widget._state()` if the attribute is callable, else
  `"idle"`. `ScreenSkinning.submit_layers(self, renderer, screen_id, ids, band,
  state_of)` (`game/ui/skinning.py:230-258`) calls `state_of(widget)` **per
  widget**, so different widgets in the same `ids` dict can answer differently
  through this one seam. The schema's `states` object keys are pinned to
  `idle`/`hover`/`pressed`/`disabled` (`docs/handoffs/section-S2.md:12-14`) —
  UL-11 does **not** touch the schema, so life state must ride those four
  tokens, not invent new ones (see §2 mapping).
- `Hud.submit()` already calls `self.skinning.submit_layers(renderer,
  self.screen_id, self.ids, "under"/"over", self.skinning.state_of)` twice
  (`game/ui/hud.py:488-489` and the mirrored `"over"` call later in the same
  method, `game/ui/hud.py:637` per the S2 handoff's file map) — **these two
  call sites already cover every id in `self.ids`**, including the three new
  ones once they're added to the dict. No new `submit_layers` call is needed.

## 2. Architecture plan

### 2.1 New holders + ids

In `Hud.__init__` (near `self._icon_lives`, `game/ui/hud.py:294-295`), add
three holders:

```python
self._life_1 = SimpleNamespace(rect=(0, 0, 0, 0), skin="ui_icon_lives",
                               visible=True)
self._life_2 = SimpleNamespace(rect=(0, 0, 0, 0), skin="ui_icon_lives",
                               visible=True)
self._life_3 = SimpleNamespace(rect=(0, 0, 0, 0), skin="ui_icon_lives",
                               visible=True)
```

Three separate named attributes, not a list — matches every other holder in
this file (`_icon_love`/`_icon_xp`/`_icon_lives` are three separate attrs, not
a loop). Default `skin` reuses the existing `ui_icon_lives` art so an
unauthored screen still shows *something* recognisable — a designer authors a
`layers` override later (UL-12 documents how) to give each state its own
sprite/animation. This default draw is a plain `submit_panel(...)` call in
`submit()` beside the existing `icon_lives` block (`game/ui/hud.py:547-550`),
same pattern, one per life holder, gated on `is_visible`.

Lay the three out beside `icon_lives` (inside `_layout_readouts`, after
`self._icon_lives.rect = ...` at `game/ui/hud.py:366`) — e.g. a small row to
the right of the existing lives icon+text, spacing on the same `_ICON_SIZE`/
`_ICON_GAP` constants already used there. Exact pixel placement is the coder's
call (no visual spec was given beyond "beside the existing icon_lives");
whatever is chosen becomes the new baked default in `screen_defaults.json`
(sanctioned, §2.3).

Add to the SAME `ids.update({...})` call at `game/ui/hud.py:391-405` (do not
open a second `ids.update`):

```python
"life_1": ("panel", self._life_1),
"life_2": ("panel", self._life_2),
"life_3": ("panel", self._life_3),
```

### 2.2 State resolution — bespoke resolver, reusing the D9 SEAM not the D9 VOCABULARY

**Decision: bespoke small resolver, not `Button`'s hover/press vocabulary —
but wired through the exact same seam `state_of` already uses.**
`ScreenSkinning.state_of` doesn't need to know anything about life counters at
all: it already resolves ANY widget carrying a callable `_state` attribute by
calling it (`game/ui/skinning.py:181-182`). Giving each life-counter holder
its own `_state` callable makes `state_of`/`submit_layers` treat it exactly
like a `Button` for resolution purposes, with zero changes to `skinning.py`.
This is the "reuse the machinery" half of D9's intent without pretending life
states ARE button states — because they aren't: alive/transition/dead has no
hover or hold-while-mouse-down concept, so forcing `Button._state()`'s
idle/hover/pressed/disabled semantics onto it would be a lie the schema then
has to carry forever.

**Token mapping onto the pinned four-key vocabulary** (the schema stays
untouched, so life state must ride existing keys):
- `"idle"` → alive, the loop state (State 1)
- `"pressed"` → transition, plays once (State 2) — chosen over `"hover"`
  because pressed already reads as "a momentary, non-hover state" in every
  other consumer of this vocabulary
- `"disabled"` → dead, static (State 3) — chosen because "disabled" already
  means "permanently inert" everywhere else this vocabulary is used
- `"hover"` is never produced by life counters; a designer CAN still author a
  `states.hover` patch (schema allows it) but nothing ever selects it — same
  "unreachable but schema-valid" situation S2 already documented for
  non-Button `idle`-only widgets (`docs/handoffs/section-S2.md:22`).

**Resolving `base_lives` deltas instead of draining the shared ledger** (this
is what the §1 frame-ordering finding forces): give `Hud` its own tiny
per-life state machine, driven off `st.base_lives` alone, which `Hud.update()`
already reads every frame before `spawn_life_lost_events` would matter to it.
No second ledger is added — `life_lost_events` keeps exactly its one existing
consumer (`Effects`); `Hud` never reads or clears it. `base_lives` IS "the
run's life-lost signal" the plan text names (`planning/UiLayeredWidgetsPLAN.md
:569`, "resolves its own state from `RunState.base_lives` plus the existing
`life_lost_events` ledger") — and since a loss is *always* exactly a 1-step
`base_lives` decrement (guarded identically to the ledger append, same `if`
block, `game/core/session.py:626-634`), a `base_lives` delta detects the same
event the ledger records, one frame earlier and without the drain race.

In `Hud.__init__`: `self._prev_base_lives = None`, `self._life_transition_idx
= None` (1-based: which life, if any, is mid-transition),
`self._life_transition_age = 0.0`. Module constant near the top of the file
(style precedent: `_LIGHTNING_READY` etc., `game/ui/hud.py:34-35`):

```python
_LIFE_TRANSITION_MS = 600  # placeholder duration; tune once art exists
```

(A hardcoded module constant, not a new `data/balancing/ui.json` key —
`ui.FX.boss_announce`'s timings are the closer analog, but adding a schema key
there is out of this phase's file scope per §3. Flagged as an open item for a
follow-up if the designer wants this tunable from `data/`.)

In `Hud.update(self, dt, mx, my, session, panel, mouse_down=False)`
(`game/ui/hud.py:408`), after `st = session.state` is bound: age any
in-flight transition (`self._life_transition_age += dt` when
`self._life_transition_idx is not None`, clear the index once age exceeds
`_LIFE_TRANSITION_MS / 1000.0`), then compare `st.base_lives` against
`self._prev_base_lives`: on the first `update()` call
(`self._prev_base_lives is None`) just seed it (no transition — matches "no
transition ever recorded" for a run that starts already below full lives,
which is a `dead`-and-static life from frame 1, not a `dead`-after-transition
one). On a drop, set `self._life_transition_idx = st.base_lives + 1` (the
life number that just died) and `self._life_transition_age = 0.0`. Always end
by `self._prev_base_lives = st.base_lives`.

A small per-index resolver (module-level function or a `Hud` method, e.g.
`_life_state_token(self, idx)`):

```python
def _life_state_token(self, idx):
    if idx == self._life_transition_idx:
        return "pressed"          # State 2: transition, playing once
    return "idle" if idx <= self._prev_base_lives else "disabled"
```

Wire it onto each holder once, in `__init__` or `layout()` (bind, don't
recompute per frame): `self._life_1._state = lambda: self._life_state_token(1)`
(and `2`/`3` likewise) — a bound closure over `self`, matching how `Button`
carries its own `_state` method. Because `_life_transition_idx`/
`_prev_base_lives` are read live off `self` inside the closure, the lambda
stays correct across frames without re-binding.

### 2.3 `tools/export_ui_layouts.py` + the sanctioned regeneration

Add three rows to `_DISPLAY_NAMES["hud"]` beside the existing
`"lives_text"`/`"icon_lives"` entries (`tools/export_ui_layouts.py:206,211`):
`"life_1": "Life 1"`, `"life_2": "Life 2"`, `"life_3": "Life 3"` (exact display
strings the coder's call, follow the `"Lives icon"` casing precedent). Add
matching rows to `_PARENTS["hud"]` beside `"icon_lives": "readout_panel"`
(`tools/export_ui_layouts.py:249-250`) if the chosen layout keeps them inside
`readout_panel`'s visual group — otherwise omit and let derived-parent logic
apply (see the comment block starting `tools/export_ui_layouts.py:321`).

Then **regenerate** `data/ui/screen_defaults.json` and
`data/ui/screen_previews.json` by running whatever the exporter's own
regeneration entry point is (grep `tools/export_ui_layouts.py` for its
`__main__`/CLI invocation, or the process `tools/tests/test_ui_skinning.py`'s
own header comment at `tools/tests/test_ui_skinning.py:134-215` documents for
"regenerated a Nth time" — those comments are the log of exactly this kind of
change). **This is the ONE sanctioned exception to D5 golden parity in the
whole S4 section** — every other phase (UL-9, UL-10, UL-12) must leave
`screen_defaults.json`/`screen_previews.json` byte-identical; only UL-11
changes them, because it is deliberately adding new default-geometry widgets.
State this in the PR body so a reviewer doesn't flag the diff as a D5
violation.

### 2.4 Test baseline

`tools/tests/test_ui_skinning.py`'s `hud` baseline (`SCREEN_EXPECT["hud"]` at
`tools/tests/test_ui_skinning.py:371` onward, built via `Hud(VIEW_W,
VIEW_H)` + `hud._layout_readouts()` at `tools/tests/test_ui_skinning.py:729-
733`) will need three new expected primitives once `life_1`/`life_2`/`life_3`
draw. **Regenerate it the same way every prior "regenerated a Nth time" entry
in that file's header comment was produced** (run the test, capture actual
output, paste it in as the new expected list) — never hand-relax the pin by
loosening an assertion or deleting a check.

## 3. File scope + shared-file contract

**Modified:**
- `game/ui/hud.py` — UL-11 owns: the three new holders in `__init__` (near
  `game/ui/hud.py:294-295`), their rects in `_layout_readouts` (near
  `game/ui/hud.py:366-369`), their `ids` entries in the single
  `ids.update({...})` call (`game/ui/hud.py:391-405`), their default
  `submit_panel` draw in `submit()` (near `game/ui/hud.py:547-551`), the new
  `_life_transition_*`/`_prev_base_lives` state in `__init__` and their
  update in `Hud.update()` (`game/ui/hud.py:408` onward), and the new
  `_life_state_token` resolver. **UL-10 (dispatched separately, same
  section) touches this file's `hit()` method** (`game/ui/hud.py:454-478`) to
  consult `hit_layer(...)` first — a DIFFERENT, non-overlapping region of the
  file. UL-11 must not touch `Hud.hit()`; UL-10 must not touch `ids`/
  `_layout_readouts`/`update`'s life-state block. If both land on the same
  branch, this is a clean merge (disjoint hunks); if a conflict shows up
  anyway, it means one phase strayed outside its region — fix by moving the
  stray edit back, not by resolving in place.
- `tools/export_ui_layouts.py` — `_DISPLAY_NAMES["hud"]` and
  `_PARENTS["hud"]` rows only (§2.3). Do not touch other screens' entries.
- `data/ui/screen_defaults.json`, `data/ui/screen_previews.json` —
  regenerated output only, never hand-edited (§2.3). **No other UL phase in S4
  may touch these two files** — if a diff to them shows up in UL-9/UL-10/
  UL-12's PR, that is a scope leak.
- `tools/tests/test_ui_skinning.py` — the `hud` baseline entry only
  (`tools/tests/test_ui_skinning.py:371` onward), regenerated (§2.4).

**Explicitly out of scope for UL-11** (owned by other S4 phases or later):
- `engine/ui_layers.py`, `data/schemas/ui_screen.schema.json` — UL-9's.
- `game/ui/skinning.py`, `game/main.py`'s click routing, `editor/panels/
  screen_details.py` — UL-10's. (The frame-ordering finding in §1 is about
  `game/main.py:1765`/`1799` — UL-11 does NOT reorder or edit these lines; it
  routes around the hazard entirely by not depending on `life_lost_events`.)
- `game/ui/effects.py` — untouched; `spawn_life_lost_events` keeps its one
  existing consumer (the banner) unchanged.
- `game/ui/CLAUDE.md`, `data/CLAUDE.md`, `docs/ui-layers-for-designers.md` —
  UL-12's.

## 4. Exit gate

```
py tools/smoke.py
py -m pytest tools/tests/test_life_counters.py tools/tests/test_ui_skinning.py -q
```

New file `tools/tests/test_life_counters.py` (follow the existing `Hud`
fixture pattern in `tools/tests/test_ui_skinning.py:729-733` /
`tools/tests/test_hud_panel.py`'s style — build a `Hud`, drive `st.base_lives`
and call `hud.update(dt, ...)` across frames):
- Full health (`base_lives == 3`, never dropped): all three life tokens
  resolve `"idle"`.
- One frame after `base_lives` drops from 3 to 2 (simulate via a fake
  `session`/`state` object, `hud.update(dt, ...)` called once with the new
  value): life 3's token is `"pressed"` (transition), lives 1/2 stay `"idle"`.
- After enough elapsed `dt` to exceed `_LIFE_TRANSITION_MS`: life 3's token
  settles to `"disabled"` and stays there on further frames (transition does
  not re-trigger).
- A run that starts already below full lives (`base_lives == 1` on the very
  first `update()` call, no prior drop observed) resolves lives 2/3 straight
  to `"disabled"` with no `"pressed"` transition ever recorded.

**Quick Test (in game):** `py game/main.py`, let an enemy reach the hole (or
use whatever debug hook already exists to force a base hit), and confirm life
counter 3 plays its transition once and then holds a dead frame while
counters 1 and 2 keep looping their idle animation. (Run by the orchestrator
or the user, not the coder.)

## Open questions for the orchestrator / user

1. **Exact pixel layout** of the three new counters relative to
   `icon_lives`/`lives_text` was not specified beyond "beside the existing
   icon_lives" (plan text, `planning/UiLayeredWidgetsPLAN.md:567-568`) — left
   to the coder's judgement, becomes the new baked default.
2. **`_LIFE_TRANSITION_MS` is a placeholder hardcoded value** (600ms) with no
   art to time it against yet — flagged as a follow-up if the designer wants
   it tunable from `data/balancing/ui.json` (out of this phase's file scope).
3. Display strings for `_DISPLAY_NAMES["hud"]["life_1/2/3"]` ("Life 1" / "Life
   2" / "Life 3" suggested) — cosmetic, coder's call, not gated by any test.
