# Phase UL-12 — Docs and designer handover

Section S4, plan `planning/UiLayeredWidgetsPLAN.md` lines 592-616. **This phase
runs LAST in S4, alone, after UL-9, UL-10 and UL-11 have all merged into
`ul-section-S4`.** It documents what those three phases actually built (plus
what S1/S2/S3 already built, some of which the docs never caught up on) — it
does not design anything new.

## 1. Behavioral spec — what each file must say, and where the facts come from

Everything below is sourced from the three landed section handoffs
(`docs/handoffs/section-S1.md`, `section-S2.md`, `section-S3.md`, read in full
for this brief) plus the plan doc's Decisions (`planning/UiLayeredWidgetsPLAN.md`
lines 50-129, D1-D10, **D7 as amended** lines 94-113) and Section S4 block
(lines 467-616). UL-9/UL-10/UL-11 are **not landed yet** as of this brief being
written — the coder executing UL-12 must read their actual landed diffs/briefs
on `ul-section-S4` at implementation time (`docs/briefs/phase-UL-9-*.md`,
`phase-UL-10-*.md`, `phase-UL-11-*.md`, and `git log`/`git diff` against
`ul-section-S4`) for the parts marked **[FROM UL-9/10/11 — confirm at
implementation]** below; do not invent behavior for those.

### A. `game/ui/CLAUDE.md`
Already carries a "Per-widget `layers` (UL-4)" block and a "Per-state
appearance, layer and owner (UL-5)" block (verified: `game/ui/CLAUDE.md:1140-1177`
approx, exact numbers will have shifted — locate by searching for `UL-4` /
`UL-5` headers). What is MISSING and must be added:
- **The two submission bands and D4's consequence**, stated as fact for a
  reader who has never seen the plan: `submit()` calls the layer submitter once
  near the top (`under`) and once at the end (`over`) per screen (confirmed
  general pattern, S2 handoff line 19: "All 14 screens' `submit()`... call
  `submit_layers(..., "under", ...)` near the top and `submit_layers(...,
  "over", ...)` as the last statement"). State explicitly: **an `under` layer
  sits behind EVERYTHING on that screen, not just behind its own owner** — this
  is a real authoring limitation with only two bands, not a bug (D4, plan lines
  76-79; reaffirmed S2 handoff line 24, S3 handoff line 25).
  - Reuse the exact tooltip text S3 put in the editor (S3 handoff line 19,
    `editor/panels/screen_details.py`'s D4 tooltip) verbatim as the doc's
    plain-English framing: *"Under layers sit behind EVERYTHING on this
    screen, not just behind their owner widget. Use Over for backgrounds
    between stacked panels."*
- **Per-state resolution, presence-not-truthiness (D9, plan line 120-124)**:
  the four-state vocabulary is `idle`/`hover`/`pressed`/`disabled`, the SAME
  one `Button._state()` and the art manifest already use — no new vocabulary.
  Fallback rule (S2 handoff line 15): `states[state]` if that key is PRESENT
  (an explicit `{}` counts, does not fall through) else `states["idle"]` if
  present, else no patch. Cross-reference the existing UL-5 block rather than
  duplicating it if that block already states this correctly — verify by
  reading it first.
- **The life counters (D10, plan lines 125-129)** — `life_1`/`life_2`/`life_3`
  join `hud.py`'s `ids` as ordinary holders, each with its own layer stack;
  `lives_text`/`icon_lives` are unchanged and stay. **[FROM UL-11 — confirm at
  implementation]**: exact state names/count for alive/transition/dead, how
  state is fed (plan says "from the run's life-lost signal", reusing
  `game/ui/effects.py`'s existing drain of `life_lost_events`, plan lines
  569-571 — do not add a second signal), and whether the transition state has
  a documented duration.
- **[FROM UL-9/UL-10 — confirm at implementation]**: the click-routing
  contract, D7 as amended (plan lines 94-113):
  - A clickable layer either retargets an existing widget id in the same
    screen (fires that widget's own action) or names one of the three
    reserved tokens `close_window` / `back` / `noop`.
    `noop` explicitly swallows the click (a decorative layer that must not
    let the click fall through to the widget behind it).
  - An unroutable `target` (neither a widget id present on the screen nor one
    of the three tokens) is a schema-VALID, WARN-not-fail condition — the
    warning lives in the editor inspector (UL-10), not the schema. Document
    this permissiveness explicitly so a designer understands why a typo saves
    without erroring.
  - The RUNTIME behavior of a dead/unroutable target must be pulled from
    UL-10's actual landed diff/brief, not guessed — the plan's open-items
    section (lines 639-644) flagged this as an explicit decision UL-10 had to
    make ("swallow the click, or fall through... falling through silently is
    the worse failure"). State whichever UL-10 actually implemented, and cite
    the file:line in UL-10's diff.
  - `engine.ui_layers.hit(...)` is pure and topmost-first (D8, plan lines
    114-119) — document why: `Hud.hit()` is called twice per click (arm probe
    on MOUSEBUTTONDOWN, real handler on MOUSEBUTTONUP) and a resolver that
    mutated state would double-fire.

### B. `data/CLAUDE.md`
- **Fix the stale widget-key list at `data/CLAUDE.md:735`** (verified stale by
  S1 handoff line 25-26, S1 deliberately left it untouched to avoid colliding
  with S2's concurrent `layers` edit — this phase is the explicit payer of
  that debt). Current text (measured, line 735):
  ```
  `widgets: {<id>: {rect?, skin?, font?, color?, text_color?, label?,
  visible?}}` overrides any named widget's properties.
  ```
  Per S1 handoff (`align` added before `color`) and S2 handoff line 10 ("full
  key list now: `color, font, label, layers, parent, rect, skin, states,
  text_color, text_id, tint, visible`"), the corrected list must include
  `align, layers, parent, states` in addition to what's already there. **Do
  not hand-type the final list** — at implementation time, read
  `data/schemas/ui_screen.schema.json`'s per-widget override object directly
  and enumerate its actual current `properties` keys (UL-9 adds nothing new
  to the WIDGET-level object, only to the layer entry, but confirm this by
  reading the schema rather than assuming).
- **Document the `layers` key itself** in the same "UI screen data" section,
  near the widget-key list: it's an array of layer entries (S2 handoff line
  11), each optional-keyed dict, `additionalProperties: false`, with a
  `states` sub-object per S2 handoff line 12-15. List the layer-entry keys
  from S2 handoff line 11 (`id, offset, z, band, slot, text_id, label, font,
  align, color, states, text_color, tint, visible`) plus **[FROM UL-9 —
  confirm at implementation]** `clickable` (bool) and `target` (string,
  id-shaped, not a closed enum — D7 amended, plan lines 507-512) once that
  phase's actual schema diff is readable. State the offset semantics (D2: an
  OFFSET from the owner's post-override rect, `[dx,dy,w,h]`, `0` w/h means
  "match the owner's").
- **Document the opened `fonts.json` custom-preset pattern (D6, S1)**: the
  seven shipped presets stay required and pinned; `fonts.schema.json` now
  allows extra `^[a-z][a-z0-9_]*$` keys via `patternProperties` (S1 handoff
  lines 13-14); a custom preset's `_LAYOUT_H` is derived once inside
  `configure_fonts` and stored, never measured live per call site (pinned-
  height invariant — SysFont measures ±1px differently per platform, plan
  lines 90-93).

### C. `editor/panels/CLAUDE.md`
Already carries "Widget layers in the outliner (UL-6)" and "Layers in the
viewport (UL-7)" and the UL-8 per-state inspector sections (verified:
`editor/panels/CLAUDE.md` around lines 1135-1266, search for `UL-6`/`UL-7`/
`UL-8` headers — exact numbers will have shifted after UL-9/10 land). What is
MISSING and must be added, **[FROM UL-10 — confirm at implementation]**:
- The Clickable checkbox + target picker in `screen_details.py` (widget ids in
  this screen + the reserved enum `close_window`/`back`/`noop` — plan line
  540) and the inline dead-target warning (the ONLY guard against a typo per
  plan lines 639-644 — document exactly what the warning looks like/where it
  renders, from UL-10's actual diff).
- The two editor-wiring items S3 explicitly deferred to UL-10 (S3 handoff
  lines 23-24, plan lines 479-482): `viewport.layer_selected` connected so a
  viewport click selects the layer in the inspector, and the inspector's
  `layer_state_combo` linked to the viewport's floating preview-state
  dropdown. Confirm both actually landed in UL-10 before documenting them as
  done — if UL-10 only did one, say so precisely.
- The `isinstance(role, tuple)` discriminator for layer vs widget tree nodes
  is ALREADY documented (S3 handoff line 11, `editor/panels/CLAUDE.md`'s
  UL-6 block) — do not duplicate, just verify it's still accurate.
- The override-free-preview note from UL-7 (`screen_previews.json` never
  bakes layers in, S3 handoff / plan — already documented per grep evidence
  above, verify and leave as-is unless UL-9/10 changed it).

### D. New `docs/ui-layers-for-designers.md`
A short walkthrough in **designer language, not agent language** — no schema
key names as the primary explanation, no file:line citations, no "D7"/"D4"
decision-ID jargon. Must cover, in this order:
1. What a layer is (a small extra piece of art/text/color pinned to an
   existing screen element) and where to add one in the editor (outliner →
   select the widget → Add layer, per S3 handoff's UL-6 Quick Test).
2. Giving it a hover colour (the state selector; explain in plain terms that
   different states — idle/hover/pressed/disabled — can look different, and
   how to switch which one you're editing).
3. The "Under vs Over" gotcha in plain language — translate the D4 tooltip
   text (S3 handoff line 19) without saying "band": something like "layers
   placed Under sit behind the WHOLE screen, not just behind the thing they're
   attached to — if you need something to sit between two panels, use Over
   instead."
4. Making a layer clickable and pointing it at a target: **[FROM UL-9/10 —
   confirm at implementation]** explain the three special destinations
   (close the window, go back, do nothing) in plain language and how
   retargeting an existing button works, plus what the warning icon/message
   means if you type a target that doesn't exist yet ("the layer will save,
   but it won't do anything until you either create that button or fix the
   name — watch for the warning").
5. Keep it under ~60 lines; this is a walkthrough, not a reference.

## 2. Architecture plan — exact insertion points

All four files are read-then-append/patch, no restructuring of surrounding
content. Locate exact line numbers via `Grep` for the anchor headers below
at implementation time — **UL-9/UL-10/UL-11 land between this brief being
written and this phase executing, so all quoted line numbers here are
approximate/pre-UL-9 and WILL have shifted.**

- `game/ui/CLAUDE.md`:
  - Insert the bands/D4-consequence + D9 cross-reference into the existing
    "Per-widget `layers` (UL-4)" / "Per-state appearance... (UL-5)" blocks
    (anchor: search `UL-4)**` and `UL-5)**`, currently ~lines 1140-1177) —
    extend in place rather than adding a new top-level section, since the
    bands are a property of the same submission mechanism those blocks
    already describe.
  - Add a new subsection for the life counters (D10) and one for click
    routing (D7 amended, D8) either directly after the UL-5 block or as new
    `## `-level sections near it — match the existing heading style in that
    file (`##` sections like "HUD submission order: panel -> button -> text"
    at line 134).
- `data/CLAUDE.md`:
  - Patch the widget-key list in place at (currently) line 735.
  - Add the `layers` key documentation and layer-entry key list immediately
    after the widget-key list, before the `screen_defaults.json` paragraph
    (currently starts line 737) — insert between, don't append at file end.
  - Add the `fonts.json` custom-preset paragraph in whatever section already
    documents `data/ui/fonts.json` (search for "fonts.json" / "fonts.schema"
    to find it; if no such section exists yet, add one near the other
    `data/ui/*.json` entries).
- `editor/panels/CLAUDE.md`:
  - Add the Clickable/target-picker/warning documentation as a new
    subsection directly after the existing "UL-8 — the per-layer, per-state
    inspector" block (anchor: search `### UL-8`, currently starts ~line 1221)
    — natural reading order is outliner → viewport → per-state inspector →
    clickability, matching phase order UL-6→UL-7→UL-8→UL-10.
  - Update the "Open findings" bullets already present in that file (from
    S3's leftovers, S3 handoff lines 23-24) to state resolved/landed instead
    of open, if UL-10 in fact wired them.
- `docs/ui-layers-for-designers.md`: new file, no insertion point — write
  it whole per the spec in section 1.D above.

## 3. File scope + shared-file contract

**No concurrency risk.** This phase is explicitly sequenced LAST within S4,
running alone after UL-9, UL-10, and UL-11 have all merged into
`ul-section-S4` (plan line 496, section Purpose line 469: "The two pieces
that need everything above to exist first"). There is no other phase running
in parallel against these four files during UL-12's execution.

Files touched, exclusively by this phase:
- Modified: `game/ui/CLAUDE.md` — locate the `UL-4`/`UL-5` headers and the
  `## HUD submission order` header (line 134 pre-UL-9) fresh at
  implementation time via Grep; do not trust this brief's line numbers.
- Modified: `data/CLAUDE.md` — locate the widget-key list (line 735
  pre-UL-9, **measured** in this brief against the current tree) and the
  `screen_defaults.json` paragraph that follows it (line 737 pre-UL-9) fresh
  at implementation time.
- Modified: `editor/panels/CLAUDE.md` — locate the `### UL-8` header
  (line 1221 pre-UL-9, **measured** in this brief) fresh at implementation
  time.
- New: `docs/ui-layers-for-designers.md`.

Since this phase runs alone, there is no shared-file contract to negotiate
with a sibling phase — the only discipline required is: read each file fresh
(these four have all been edited by UL-9/UL-10/UL-11 by the time this phase
starts) before editing, and never guess at UL-9/UL-10/UL-11's actual
behavior — read their landed diffs (`git log ul-section-S4`, and
`docs/briefs/phase-UL-9-*.md`/`UL-10-*.md`/`UL-11-*.md` if those brief files
exist on the branch) for every fact tagged **[FROM UL-9/10/11]** above.

## 4. Exit gate

```
py tools/smoke.py
py -m pytest tools/tests/test_ui_layers.py -q
```
Also check whether `tools/tests/test_meta_docs.py` exists at implementation
time (it does **not** exist as of this brief being written — **measured**,
`Glob tools/tests/test_meta_docs.py` returned no results). If it exists by
the time UL-12 executes, add it to the pytest invocation above:
```
py -m pytest tools/tests/test_ui_layers.py tools/tests/test_meta_docs.py -q
```
If it still does not exist, note that in the phase's completion report and
run only the `test_ui_layers.py` command — do not create a new test file for
docs-only changes (this is a docs phase, not a code phase; no new coverage is
scoped here).

**Quick Test** (run by the orchestrator/user, not the coder): hand
`docs/ui-layers-for-designers.md` — and ONLY that file, not the plan, not the
package docs — to a reader who has not seen `UiLayeredWidgetsPLAN.md`. They
should be able to, from the doc alone: open the editor, add a layer to an
existing widget, give it a hover colour, and understand why an `under` layer
they add will sit behind the whole screen rather than just its owner. If they
get stuck or need to ask a question the doc doesn't answer, the doc failed
its brief.
