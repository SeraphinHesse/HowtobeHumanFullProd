# Phases TU-1 – TU-7 — orchestrator coordination

Written after all 7 planner briefs landed (`docs/briefs/phase-tu-1-foundations.md`
through `phase-tu-7-scripted-loss-stone-chain.md`). This doc is the reconciled
merge order + shared-file contract the orchestrator uses to sequence Wave 2
(coders); it does not replace any brief, only resolves the cross-brief
disagreements/gaps each brief itself flagged.

## Merge order (batches, not one flat parallel wave)

The plan's own dependency graph (§3, "TU-2/TU-3/TU-4 depend only on TU-1... TU-6
on TU-1(+TU-2)... TU-7 on TU-5+TU-6") plus two REAL file-collision findings from
the planners (below) mean Wave 2 runs as dependency-respecting batches, each
batch's coders branching off the umbrella **after** the previous batch is merged
in — not all 7 coders forking off the pre-TU-1 umbrella simultaneously.

1. **Batch A — TU-1** (solo). Merge, gate.
2. **Batch B — TU-2, TU-3, TU-5** (parallel worktrees off the post-TU-1
   umbrella; no file overlap between any pair of these three). Merge order
   within the batch: TU-2, then TU-3, then TU-5 (arbitrary — pick this order
   so TU-3's `editor/panels/CLAUDE.md`/`editor/main.py` anchors, which TU-4
   depends on, land before Batch C). Gate after each merge.
3. **Batch C — TU-4** (solo, off the umbrella now containing TU-1+TU-2+TU-3+
   TU-5 — TU-4's brief requires TU-3's `editor/panels/selector.py` +
   `editor/main.py` lines to exist as real anchors, not placeholders). Merge,
   gate.
4. **Batch D — TU-6** (solo, off the umbrella through TU-4 — needs TU-2's
   painted test map for its live Quick Test, and TU-5's `game/main.py`
   changes already landed so TU-6's own `game/main.py` edits target real
   current line numbers, not TU-5's brief's pre-TU-5 numbers). Merge, gate.
5. **Batch E — TU-7** (solo, off the umbrella through TU-6 — needs the
   director/session API TU-6 actually shipped). Merge, run the **one and
   only full** `py tools/testgate.py check`, then PR.

## Resolved cross-brief findings

1. **`data/slots.json` registry groups (TU-1 vs TU-2 disagreement) — RESOLVED
   in favor of TU-2's finding.** TU-1's original brief claimed no
   `data/slots.json` entry was needed for the tutorial markers (correct that
   they're never a *sprite* — verified `map_file.schema.json:222-223`'s
   `start_area` const note). TU-2's brief found (verified
   `editor/panels/palette.py:226-244`) that `start_area`/`camera_start` each
   still carry a real `core` registry **group**, purely so the palette brush
   button has a slot key to arm/resolve an icon for. **TU-1's brief has been
   corrected** (see its §1 "Correction" note and new §3 `data/slots.json`
   bullet) to add `core → "Tutorial Flute"` / `core → "Tutorial Stone"`
   groups. TU-2's brief needs no change — its own §0 already offered this as
   the preferred resolution ("Either TU-1 must add these two registry groups,
   or TU-2 adds them itself") and its §3 already states "if TU-1 lands with
   them, this phase touches nothing here."

2. **`tools/smoke.py` directory-exception question — RESOLVED: no functional
   change.** TU-1's brief established both new files' stems already equal
   their schema's stem, so the existing stem-pairing `else` branch resolves
   them with zero code change. Confirmed acceptable — do not add the
   alternative symmetric `elif` branches TU-1's brief also offered as a legal
   alternative; one approach only, and TU-1's test must assert against
   whichever was picked (the no-op path).

3. **`editor/panels/selector.py` / `editor/main.py` sequencing (TU-3 → TU-4) —
   CONFIRMED, no further action needed.** Both briefs independently found and
   already resolved this: TU-3's Cutscenes leaf lands first (`_CUTSCENES_ROLE
   = UserRole+6`), TU-4's Tutorial leaf lands second and anchors "immediately
   after TU-3's lines" (`_TUTORIAL_ROLE = UserRole+7`). Batch C (TU-4) is
   dispatched only after Batch B's TU-3 merge, so TU-4's coder reads TU-3's
   REAL landed lines rather than the brief's placeholder anchors.

4. **`game/core/session.py` `end_turn()` (TU-5 vs TU-6) — CONFIRMED
   non-overlapping, no reconciliation edit needed.** TU-6 inserts its
   `tutorial_gate` check immediately after the existing early-return guard,
   before `set_round(...)`. TU-5 inserts its `pending_cutscene` request
   immediately before `spawner.begin_round(...)`, i.e. strictly below TU-6's
   insertion. The two hunks do not touch the same lines. Batch B (TU-5) still
   merges before Batch D (TU-6) per the dependency graph (TU-6 needs TU-2
   anyway), so TU-6's coder sees TU-5's real diff and can confirm the
   adjacency by reading the file rather than trusting either brief's stale
   line numbers.

5. **`game/main.py` (TU-5 and TU-6 both touch extensively) — handled by merge
   order, not a textual-contract note.** Unlike the `session.py` case, TU-5's
   edits (boot construction, `gp` dict, input dispatch, the `_WORLD_STATES`
   sim top, the render-overlay insertion after `renderer.flush`) and TU-6's
   edits (`build_gameplay`, `handle_world_click`, the two
   `panel.handle_click()` call sites, the tile-click site, two more
   render-overlay insertions) are too close together to specify safe blind
   parallel anchors. TU-5 already left a `# TU-6: input whitelist goes here`
   marker comment for exactly this reason. Batch D dispatches TU-6 only after
   Batch B's TU-5 merge — TU-6's coder reads the actual post-TU-5
   `game/main.py`, not the brief's line numbers, and inserts relative to real
   surrounding code (the briefs' cited line numbers are directional, not
   load-bearing).

6. **`engine/CLAUDE.md` (TU-1 + TU-6) — CONFIRMED non-overlapping.** TU-1
   appends one sentence to the existing `tilemap.py` bullet. TU-6 appends a
   whole new `tutorial.py` bullet after `video_playback.py`, before "## Hard
   rules". Different anchors; safe in either merge order (TU-1 lands first
   regardless, per the batch order above).

7. **`game/CLAUDE.md` (TU-5, TU-6, and TU-7 all touch it) — no textual
   contract given by TU-7's brief yet** (TU-7 was written before TU-5/TU-6
   existed). Since Batch E (TU-7) runs after Batches B/D have already merged
   TU-5's and TU-6's `game/CLAUDE.md` subsections, TU-7's coder must append
   its own new subsection after both, not guess at a stale anchor — flag this
   explicitly in TU-7's coder dispatch.

8. **TU-7's inferred director/session API** (its brief was written before
   TU-5/TU-6 existed, so `allows()`, an event-feed method, and the
   `Session.tutorial_gate`/`tutorial_director` wiring were inferred from plan
   prose, not real code). Now that TU-6's brief exists with concrete method
   names (`TutorialDirector.allows`, `allows_end_turn`, `on_tile_clicked`,
   `on_card_selected`, `on_building_placed`, `on_message_dismissed`, `skip`,
   `message_visible`/`message_text`/`skippable`; `Session.tutorial_gate`
   callable hook), **TU-7's coder must bind to these real names**, not the
   brief's placeholder guesses — flag this explicitly in TU-7's coder
   dispatch, and re-read TU-6's actual landed `director.py` (not just its
   brief) before writing TU-7's `on_base_hit` free-loss hook.

## Testing posture for every coder (applies to all 7 phases)

Every coder must keep testing minimal and matched to what the house rules
already prescribe — no extra manual verification passes beyond the gate:
- `py tools/smoke.py` + `py tools/testgate.py check --affected` while
  iterating. **Never** a manual `pytest` sanity run before that (redundant
  with `--affected`), and **never** the full `testgate.py check` mid-task —
  that runs exactly once, either at TU-7's hand-back (per its brief, the
  plan's designated full-gate phase) or, for phases TU-1 through TU-6, only
  if a coder is explicitly told this is the final phase of its batch AND the
  orchestrator's overall Wave-4 gate hasn't already covered it. In practice:
  TU-1 through TU-6 coders run `--affected` only; TU-7's coder runs the full
  `check` once as its own exit gate (already stated in its brief); the
  orchestrator's Wave-4 full gate on the finished umbrella is the true final
  check regardless.
- Write only the tests each brief's "Tests" section actually calls for — no
  speculative extra coverage, no re-testing what a prior phase's tests
  already pinned.
