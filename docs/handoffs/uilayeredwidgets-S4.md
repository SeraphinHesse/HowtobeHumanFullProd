# Section S4 handoff — Clickable layers and life counters

Plan: `planning/UiLayeredWidgetsPLAN.md`, Section S4 (phases UL-9, UL-10,
UL-11, UL-12). Branch `ul-section-S4`, merged to
`plan-uilayeredwidgets-umbrella`. **This closes the plan: 12/12 phases.**

> **Why this file was written late, and by whom.** S4's orchestrator hit the
> weekly API limit mid-section. UL-9/UL-10/UL-11 had already landed and merged;
> what never happened was the section-level review, this handoff, and UL-12
> (whose coder was killed mid-edit, its partial pass rescued on
> `ul-phase-UL-12-docs` @ `a74ed70` and merged in here). The main session
> finished all three. Two decisions S4 was required to make and record were
> found already IMPLEMENTED in UL-10's landed code but written down nowhere as
> decisions — they are recovered in §2 below, from the code as merged.

## 1. What S4 publishes

| Phase | Landed | Where |
|---|---|---|
| UL-9 | `clickable` + `target` on a layer entry; `engine.ui_layers.hit` | `data/schemas/ui_screen.schema.json`, `engine/ui_layers.py` |
| UL-10 | `ScreenSkinning.hit_layer`; 13 wired click paths; reserved-token routing; editor Clickable/Target rows + warning; S3's two deferred wirings | `game/ui/skinning.py`, `game/main.py`, 11 menu screens + `hud.py` + `building_ui.py`, `editor/panels/screen_details.py`, `editor/main.py` |
| UL-11 | `hud.life_1`/`life_2`/`life_3` as id'd holders with alive/dying/dead states | `game/ui/hud.py`, `tools/export_ui_layouts.py`, regenerated goldens |
| UL-12 | `docs/ui-layers-for-designers.md` + the four package docs | `docs/`, `game/ui/CLAUDE.md`, `data/CLAUDE.md`, `editor/panels/CLAUDE.md`, `engine/render/CLAUDE.md` |

**Interface contracts** (the things a later phase must not break):

- `engine.ui_layers.hit(layers, owner_rect, mx, my, state="idle")` — pure,
  topmost-first (`over` z-descending → owner → `under` z-descending). Returns
  `{"kind": "layer", "id", "target"}` with RAW authored values, `{"kind":
  "owner"}`, or `None`. It resolves nothing and validates nothing: routing is
  the caller's job.
- `ScreenSkinning.hit_layer(ids, widgets_spec, mx, my, state_of, actions=None)`
  — pure; maps a hit onto the SAME action value the screen's own `hit()` would
  return. `actions` is that screen's own action table reversed, never a copy.
- `RESERVED_TARGETS = ("close_window", "back", "noop")` lives in
  `game/ui/skinning.py` and is **restated, not imported**, in
  `editor/panels/screen_details.py` — `editor/` may never import `game/`.
- `hud.life_N` holders carry their own `_state` callable, which is the same
  seam `ScreenSkinning.state_of` already dispatches through for a `Button`. No
  schema change; life states ride the pinned four-token vocabulary as
  `alive→idle`, `dying→pressed`, `dead→disabled`.

## 2. The two decisions S4 owed, recovered from the landed code

The plan's §5 open-items named these as decisions UL-10 **had to** make. Both
were made and implemented; neither was recorded as a decision anywhere. They
are ratified here as-implemented — no code was changed to close this gap.

### Decision S4-A — a dead/unroutable target SWALLOWS the click

**Ruling: swallow. It does not fall through.** Implemented as `hit_layer`'s
"Ruling 1", `game/ui/skinning.py` — a `target` matching neither a reserved
token nor a widget id in this screen's `actions` table returns `"noop"`, not
`None`.

**Why.** `None` means "no layer was hit", so the click would land on the widget
UNDER the layer. A typo'd target would then behave *exactly* as if the layer
had never been made clickable — silently unmaking what the designer configured,
with no symptom to notice. The plan's risk bullet named this as the worse of
the two failures. A swallowed click reads honestly as "this decal does
nothing", which is the same thing `noop` already means, so the failure mode and
the intentional mode are one behaviour instead of two.

**Consequence to accept.** An unroutable target ships as a dead spot on the
screen that also blocks the control behind it. The editor's amber inspector
warning (D7 amended) is the only guard, which is why it must stay visible where
the designer works and why `docs/ui-layers-for-designers.md` spells out what
amber means in plain language.

### Decision S4-B — clickable layers join the LINT, not the hard floor

**Ruling: the non-blocking under-16px lint only, never `TestButtonMinSize`'s
hard ≥12px floor.** Implemented as `_clickable_layers()` in
`tools/tests/test_ui_min_targets.py`, feeding
`test_report_small_click_targets` alongside the button roster. Layers report
from 0px up and are resolved in the `idle` state only — a state patch that
shrinks a layer on `pressed` is not a click-target problem.

**Why.** A clickable layer is usually decorative art retargeted onto a button
that already passed the hard floor, so the floor is already satisfied by the
real control; failing the build on the decoration would pressure a designer
into the one fix `game/ui/CLAUDE.md` explicitly forbids — mass-resizing
controls to silence a lint. The lint still surfaces a genuinely tiny standalone
click target for an eyeball pass.

## 3. Section review

Run by the main session after the fact (read-only, against
`git diff 050fa8b..41e10ce`, briefs, and the S1/S2/S3 handoffs).
**No findings that block landing.** Clean bills on: purity/D8 (both resolvers
mutate nothing; `test_ui_layer_click.py::TestHudHitIsPure` snapshots `Hud`
across two identical `hit()` calls), fall-through (all 13 wired sites place the
consult correctly relative to their guards; `hit_layer` fast-exits on a falsy
`widgets_spec`, which is every shipped screen today), the retarget contract
(every screen passes its real table; mutating branches correctly excluded),
D7-amended (open schema pattern, warning never gates the write, no
`editor/`→`game/` import), and D5 golden parity (the only deltas in
`screen_defaults.json`, `screen_previews.json` and the `hud` baseline are the
three new life holders).

Two LOW observations, both accepted and now documented in `game/ui/CLAUDE.md`:

1. Only one life transition is tracked at a time — two losses inside the 600 ms
   window truncate the first counter's death animation. Cosmetic; the resolved
   state is never wrong.
2. No test pins a life being RESTORED. The code handles it correctly and
   symmetrically (`idx <= lives`); left uncovered per the minimal-testing
   policy.

## 4. Known gaps and follow-ups (none blocking)

- **No phase in S4 has been through the full gate.** Neither has any of S1–S3.
  `py tools/testgate.py check` has never run against this work; it belongs to
  `/commitpushpr` stage 5, run by the user after `Development` merges down. CI
  on `Development` has also been failing for reasons predating this plan, so a
  red result there is not automatically S4's.
- `_LIFE_TRANSITION_MS = 600` is a hardcoded module constant in `hud.py`, not a
  `data/balancing/ui.json` tunable. Deliberate: there is no death animation art
  to time it against yet. Promote it when there is.
- `game/ui/widgets.py::configure_palette`'s docstring still says it fails loud
  on an unknown key "same as `configure_fonts`". True of `configure_palette`,
  no longer true of `configure_fonts` (UL-2/D6 opened it to extras). A one-line
  docstring fix, left alone here because UL-12 is a docs phase and touching
  `game/` risked the golden pin for no gain.
- Three screens are deliberately NOT wired for clickable layers —
  `levelup.py` (returns a dict), `enemy_intro.py` (returns a bool),
  `boss_cutscene.py` (`"A"`/`"B"` goes straight to
  `session.resolve_boss_cutscene`). Wiring one means giving it a safe host
  branch first; an action STRING from any of them is a contract violation at
  the host.
- The band limitation (D4) is unchanged and permanent without a redesign: an
  `under` layer sits behind the whole screen. A third band or a per-widget
  submission seam is a design change, not a bug fix.

## 5. Quick Tests for the user

- **UL-10** — make a Munchkin layer on `hud.btn_pause` clickable, retarget it
  at `btn_end_turn`; `py game/main.py`, click the Munchkin, confirm the turn
  ends while clicking the rest of the pause button still pauses.
- **UL-10 dead target** — set a layer's target to a name that does not exist.
  Confirm the editor shows the amber warning, the file still saves, and in game
  the click does nothing *and* does not reach the button underneath.
- **UL-11** — `py game/main.py`, let an enemy reach the hole; counter 3 plays
  its transition once then holds the dead frame while 1 and 2 keep looping.
- **UL-12** — hand `docs/ui-layers-for-designers.md`, and only that file, to
  someone who has not read the plan. From it alone they should add a layer,
  give it a hover colour, and understand why an `under` layer sits behind the
  whole screen.
