# Phase TU-5 — Game: registry-driven cutscene playback

Depends on TU-1 (`data/video/cutscenes.json` + `data/schemas/cutscenes.schema.json`
— assumed to already exist per the dispatch: `intro -> cutscene.mp4` len 44.2,
`first_end_turn -> placeholder video, audio null`). This brief assumes the
registry is a JSON **object keyed by id** (`{"intro": {...}, "first_end_turn":
{...}}`), each entry carrying `video` (path relative to `data_dir`), `audio`
(nullable, same shape), `length` (seconds, nullable), `trigger` (enum). **If
TU-1 landed a different shape (e.g. a list of `{id, ...}` objects), adjust
`load_cutscene_registry` in step 1 below to normalize into that
id-keyed dict — nothing downstream depends on the on-disk shape, only on the
in-memory mapping.**

## 1. Behavioral spec

**Current intro cutscene (the exact code this phase generalizes):**
- Built at boot, hardcoded path + length from balancing, not the registry:
  `game/main.py:232-236` —
  `VideoSource(data_dir / "video" / "cutscene.mp4", ui_balance["Menu"]["cutscene_length"], target_size=(view_w, view_h))`;
  `start = GameState.CUTSCENE if video.enabled else GameState.MAIN_MENU`.
- Input: `game/main.py:521-524` — on `GameState.CUTSCENE`, any `KEYDOWN` or
  `MOUSEBUTTONDOWN` calls `video.skip()`, and the event is otherwise swallowed
  (`continue`).
- Sim: `game/main.py:628-632` — `video.update(dt)`; when `video.done`,
  `video.release()` then `shell.to_main_menu()`.
- Render: `game/main.py:735-743` — `video.frame_surface()` blitted at `(0, 0)`
  if not `None`, a `"press any key to skip"` `HudText` submitted, then
  `renderer.flush(window)`.
- `ui_balance["Menu"]["cutscene_length"]` is `44.2` at
  `data/balancing/ui.json:24` (schema `data/schemas/ui.schema.json:129-137`) —
  the same number TU-1's registry `intro` entry carries. Once the intro reads
  its length from the registry this balancing key becomes dead weight (see
  §3 open item).

**`engine.video.VideoSource`** (`engine/video.py:65-166`, cited in
`engine/CLAUDE.md`) — `VideoSource(path, length, target_size=None)`. `.enabled`
(cv2 present + file exists + capture opens), `.done`, `.update(dt)` (advances
clock, reads one frame, sets `done` at length cap or stream end — never
raises), `.frame_surface()` (BGR→RGB, optional resize, `None` until a frame is
read), `.skip()` (idempotent, sets `done`), `.release()` (idempotent, frees the
capture). Graceful skip (missing cv2 / missing file / capture won't open) sets
`enabled=False`, `done=True` immediately in `__init__` — this is the ONE
mechanism TU-5's "missing video" test relies on; do not reimplement it.

**`engine.audio`** (`engine/audio.py:1-41`) — `play_music(path, loop=True,
volume=None)` and `stop_music()`, both `pygame.mixer.music` wrappers that
swallow every exception (silent no-op with no device / SDL dummy / bad file).
There is only ONE music channel (`pygame.mixer.music`) — starting a companion
cutscene track replaces whatever background music (`play_music` call at
`game/main.py:250`) was already playing; nothing restores it afterward (see
Risk in the plan doc — no drift/resume correction in scope).

**`game/core/session.py` `end_turn()`** (`game/core/session.py:228-254`):
```
228  def end_turn(self):
...
234      st = self.state
235      if st.state != GameState.GAMEPLAY or st.phase != GamePhase.BUILDING:
236          return
237      self.tilemap.set_round(st.round_num)  # 10I: damage-weight round gate
238      self.spawner.begin_round(
239          st.round_num, self.tilemap, self.enemies_balance,
240          rng=self.rng, registry=self.registry)
...
253      st.phase = GamePhase.ENEMY
254      self._wipe_pending = False
```
`round_num` starts at 1 and is only ever incremented by `run_payday`
(`game/core/game_state.py:9-10`, `game/core/CLAUDE.md` "Round loop") — it can
never be `1` again after the first `end_turn()` of a run, which is what makes
"exactly once per run, never on round 2+" a **free property of a `round_num ==
1` guard** — no extra "already fired" flag needed.

**Existing modal-freeze precedent to mirror** (`Session.frozen`,
`game/core/session.py:89-93`): `LEVELUP`/`BOSS_CUTSCENE` freeze the world by
gating `pre_sim`'s `scene.update`/`resolve_combat`/`post_sim` block
(`game/main.py:643-668`, the `if session.state.state == GAMEPLAY and not
session.frozen:` guard). TU-5 needs the same freeze shape for the
`first_end_turn` cutscene but **without** adding a new `GamePhase` (that enum
lives in `game/core/phases.py`, out of this phase's file scope and shared with
TU-6/TU-7) — so the freeze is a **host-local flag** (`gp["cutscene"]`), not a
session phase.

**Registry precedent** (`pending_boss_cutscene`,
`game/core/game_state.py:73-83`, `session.py:359-381`): a nullable dict field
on `RunState`, set by core, read + cleared by the host/session at the
consuming site. TU-5's `pending_cutscene` copies this shape exactly.

## 2. Architecture plan

**New module `game/ui/cutscene_player.py`** — generalizes the intro loop into
a reusable class plus a registry loader:

```python
def load_cutscene_registry(data_dir):
    """data_io.load_validated(data_dir/"video"/"cutscenes.json",
    data_dir/"schemas"/"cutscenes.schema.json") -> {id: entry} dict.
    Adjust here (not at call sites) if TU-1's on-disk shape differs."""

class CutscenePlayer:
    """Wraps VideoSource + the entry's optional companion audio. One instance
    per registry entry; reusable for both the intro slot and first_end_turn."""
    def __init__(self, data_dir, entry, target_size):
        video_path = data_dir / entry["video"] if entry.get("video") else ""
        self._video = VideoSource(video_path, entry.get("length"),
                                   target_size=target_size)
        self._audio_path = (data_dir / entry["audio"]
                             if entry.get("audio") else None)

    @property
    def enabled(self): return self._video.enabled     # graceful-skip mirror
    @property
    def done(self): return self._video.done

    def start(self):
        """Call once, when playback begins. Starts the companion track (if
        any) via engine.audio.play_music(path, loop=False) — a no-op under
        SDL dummy / no device (engine/audio.py contract)."""

    def update(self, dt): self._video.update(dt)
    def frame_surface(self): return self._video.frame_surface()

    def skip(self):
        """Click/key skip — mirrors VideoSource.skip() + stop_music()."""

    def release(self):
        """Mirrors VideoSource.release(); also stop_music() defensively."""
```

No new pygame surface is created that VideoSource doesn't already own; no new
cv2 touch point. `enabled`/`done` are pure pass-throughs so the "missing video
→ graceful skip" contract is inherited, not reimplemented.

**Host wiring (`game/main.py`)** — two independent call sites, because the
intro is a **pre-gameplay shell state** and `first_end_turn` is an **in-
gameplay overlay**, and they must NOT be unified into one state machine (the
shell has no concept of "cutscene during a live round"):

1. **Boot**: build one `CutscenePlayer` per registry entry
   (`cutscenes: dict[str, CutscenePlayer]`), migrating the intro's hardcoded
   path/length to read `cutscenes["intro"]`.
2. **Intro** keeps using the existing `GameState.CUTSCENE` shell state
   (input/sim/render call sites unchanged in shape — just point at
   `cutscenes["intro"]` instead of the standalone `video` object).
3. **`first_end_turn`**: `Session.end_turn()` sets `state.pending_cutscene =
   {"id": "first_end_turn"}` on round 1, before `spawner.begin_round()`
   (still calls it — the wave IS queued; the host visually withholds it by
   freezing `pre_sim` while `gp["cutscene"]` is active, so the player never
   sees it start). The host consumes `pending_cutscene` at the top of the
   `_WORLD_STATES` sim branch, freezes the sim for as long as
   `gp["cutscene"]` is set, and draws the video as a full-screen overlay
   painted AFTER the (frozen, but still-submitted) world frame — this avoids
   reindenting the ~90-line existing sim/render bodies (see §3 for the exact
   guard placement).

**Why freeze via a host dict key, not a new `GamePhase`**: `phases.py` is
outside this phase's file scope (§3's shared-file table) and TU-6/TU-7 may
touch phase transitions too; a purely host-local `gp["cutscene"]` flag +
`RunState.pending_cutscene` (a request, not a phase) keeps TU-5 self-contained
and mirrors the `income_events`-style "core fills, host/UI drains" ledger
convention already used for `pending_boss_cutscene`, `xp_events`, etc.

## 3. File scope + shared-file contract

**New files (TU-5 owns outright):**
- `game/ui/cutscene_player.py` — `CutscenePlayer` + `load_cutscene_registry`
  (per §2).
- `tools/tests/test_cutscene_player.py` — headless (SDL dummy), mirrors
  `tools/tests/test_video_source.py`'s shape: registry load, missing-video
  graceful skip, `start()`/`skip()` audio calls are no-ops under SDL dummy.
- `tools/tests/test_cutscene_session.py` (or extend `test_phase_loop.py` —
  implementer's call, but a new file avoids growing an already-large test
  module) — `end_turn()` round-1 `pending_cutscene` request semantics (headless,
  no pygame), using the `synth`/`build_board`/fixture pattern from
  `tools/tests/test_phase_loop.py:1-52`.
- Register both new test modules in `conftest.py`'s `TIERS` table as `"core"`
  (precedent: `"test_video_source": "core"` at `conftest.py:124`) — **required**,
  an unregistered module is a hard error (`test_tiers.py`).

**Modified — `game/core/game_state.py`** (owned by TU-5 alone in this phase;
TU-6/TU-7 do not touch `RunState` per the plan's file lists):
- Add one field beside `pending_boss_cutscene` (`game/core/game_state.py:82`,
  in the `# -- Boss (10G) --` block is the wrong neighborhood — add a NEW
  small block right after `enemy_death_events` at line 90, before the
  `# -- 10H: lightning...` comment at line 92):
  ```python
  # -- TU-5: registry-driven cutscene request -----------------------------
  # {"id": <registry key>} queued by Session.end_turn() on round 1, BEFORE
  # spawner.begin_round(); consumed (set back to None) by the host once it
  # starts playing the matching CutscenePlayer. Never serialized.
  pending_cutscene: object = None
  ```

**Modified — `game/core/session.py`** (`end_turn()`, lines 228-254). **TU-5's
edit is a single self-contained insertion, not a rewrite of surrounding
lines**, so TU-6 (whose plan note says it touches `end_turn`'s
skip/allow-gating) and TU-7 (which touches `on_base_hit`, a different method)
can land without textual collision:
- Insert **between line 236 (`self.tilemap.set_round(...)`) and line 237's
  blank-line-then-comment, i.e. immediately BEFORE line 238's
  `self.spawner.begin_round(` call**:
  ```python
      if st.round_num == 1:
          st.pending_cutscene = {"id": "first_end_turn"}
      self.spawner.begin_round(
  ```
  (Only the new `if` block is added; `self.spawner.begin_round(` itself is
  unchanged, just now has two new lines directly above it.) This is the exact
  ordering the plan requires ("before spawner.begin_round()"); `round_num == 1`
  is the free "exactly once, never round 2+" guard argued in §1.
- **Reserve for TU-6/TU-7**: if TU-6 needs to gate `end_turn()` on the
  director's `allows("end_turn")`, that check belongs at the TOP of the
  method (before line 234's `st = self.state`), not inside this insertion —
  keep the cutscene-request line and any future allow-gate line on visually
  separate hunks.

**Modified — `game/main.py`.** This is the file most likely to collide with
TU-6 (input whitelist around `panel.handle_click()`, director event hooks) and
possibly TU-7. TU-5's edits, in file order:

1. **Import** (`game/main.py:58`) — replace
   `from engine.video import VideoSource` with
   `from game.ui.cutscene_player import CutscenePlayer, load_cutscene_registry`
   (VideoSource is no longer touched directly by `main.py`; `CutscenePlayer`
   wraps it). Precedent for a standalone `game.ui.<module>` import line:
   `game/main.py:75` (`from game.ui.skinning import ScreenSkinning`).
2. **Boot construction** — replace `game/main.py:232-236` (the `video =
   VideoSource(...)` block) with:
   ```python
   cutscene_registry = load_cutscene_registry(data_dir)
   cutscenes = {
       cid: CutscenePlayer(data_dir, entry, target_size=(view_w, view_h))
       for cid, entry in cutscene_registry.items()
   }
   intro_player = cutscenes.get("intro")
   start = (GameState.CUTSCENE if intro_player and intro_player.enabled
            else GameState.MAIN_MENU)
   ```
   Every later reference to the bare `video` name in the CUTSCENE-state call
   sites (`main.py:521-524`, `628-632`, `735-743`) becomes `intro_player`.
3. **`gp` dict literal** (`game/main.py:270-274`) — add one new key,
   `"cutscene": None,` (the active in-gameplay `CutscenePlayer`, `None` when
   none is playing). Also reset it in `teardown_gameplay()`
   (`game/main.py:314-322`'s loop over `gp` keys) — add `"cutscene"` to that
   tuple so a quit-to-menu mid-cutscene doesn't leak a stale player into the
   next run.
4. **Input** — insert immediately BEFORE the `# GAMEPLAY / GAME_OVER: the live
   world is present` comment at `game/main.py:531` (i.e., right after the
   menu-states `continue` at line 530), a new block that consumes ALL
   `KEYDOWN`/`MOUSEBUTTONDOWN` while an in-gameplay cutscene is active,
   mirroring the CUTSCENE branch at lines 521-524:
   ```python
   if gp["cutscene"] is not None:
       if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
           gp["cutscene"].skip()
       continue
   # GAMEPLAY / GAME_OVER: the live world is present
   ```
   **Leave a `# TU-6: input whitelist goes here` marker comment** immediately
   after this block so TU-6 has an obvious, non-overlapping anchor for its own
   allow-list gate (which per the plan sits around `panel.handle_click()`,
   further down at `main.py:424`, a DIFFERENT location — no collision, but the
   marker avoids the two phases guessing the same line).
5. **Sim** — at the top of `elif st in _WORLD_STATES:` (`game/main.py:633`,
   right after `world = gp["world"]` / `session = world.session` at lines
   634-635), insert the request-consume + freeze guard, then wrap the
   EXISTING body (lines 636-727, the `sim_dt = ...` combat-speed calc through
   the final `gp["game_over"].update(dt, ...)` call) under a new `if
   gp["cutscene"] is None:` — i.e., add one guard line before 636 and indent
   636-727 one level; no other line changes:
   ```python
   elif st in _WORLD_STATES:
       world = gp["world"]
       session = world.session
       if gp["cutscene"] is None and session.state.pending_cutscene:
           requested = cutscenes.get(
               session.state.pending_cutscene.get("id"))
           session.state.pending_cutscene = None
           if requested is not None and requested.enabled:
               requested.start()
               gp["cutscene"] = requested
       if gp["cutscene"] is not None:
           gp["cutscene"].update(dt)
           if gp["cutscene"].done:
               gp["cutscene"].release()
               gp["cutscene"] = None
       if gp["cutscene"] is None:
           # Combat speed (10F) scales the ENEMY-phase sim ONLY — ...
           sim_dt = (dt * session.combat_speed
                     if session.state.phase == GamePhase.ENEMY else dt)
           ... [lines 636-727 UNCHANGED, indented one level]
   ```
   This is the ONE place TU-5 freezes the round; `session.state.pending_cutscene`
   already handles "graceful skip when video absent" — if `requested.enabled`
   is `False` (missing file/cv2), `gp["cutscene"]` is never set, so the very
   next line (`if gp["cutscene"] is None:`) runs the normal sim on the SAME
   frame — the round genuinely never pauses, satisfying "missing video →
   graceful skip and the round still starts" with no extra branch.
6. **Render** — do NOT touch the large `elif st in _WORLD_STATES or st ==
   GameState.PAUSED:` render body (`main.py:744-839`). Instead insert an
   overlay block immediately AFTER the world's own `renderer.flush(window)`
   call at `game/main.py:835` and BEFORE the `# -- 10G boss: undo the shake
   pan --` comment at line 836:
   ```python
   if gp["cutscene"] is not None:
       surf = gp["cutscene"].frame_surface()
       if surf is not None:
           window.blit(surf, (0, 0))
       renderer.submit_hud(HudText(
           "press any key to skip", (view_w // 2, view_h - 40),
           "md", (210, 210, 210), align="center"))
       renderer.flush(window)
   ```
   The world frame is fully drawn and flushed first (frozen, so it's a still
   image), then the video paints over it full-screen — visually
   indistinguishable from a modal cutscene, zero reindentation of the
   existing render body.

**Modified — `game/CLAUDE.md`** (or `game/ui/CLAUDE.md`, since the new module
lives in `game/ui/` — implementer's call, but `game/ui/CLAUDE.md` is the
better fit since it documents `BossCutscene`/`Shell` in that same file). Add a
new subsection **after** the existing cutscene-adjacent content — in
`game/ui/CLAUDE.md`, add `## Cutscenes (Phase TU-5)` at the END of the file
(append-only, so TU-6/TU-7 additions to the same doc for the tutorial director
/ message box land as separate subsections without touching this one).
Content: `CutscenePlayer` + `load_cutscene_registry` location, the two trigger
call sites (intro shell state vs. `pending_cutscene` host-freeze overlay), and
the "only one `pygame.mixer.music` channel" caveat.

**Open item flagged, not resolved, by this brief**: `ui_balance["Menu"]
["cutscene_length"]` (`data/balancing/ui.json:24`,
`data/schemas/ui.schema.json:129-137`) becomes unused once the intro reads its
length from the registry. Deleting it is a `data/balancing/*` edit (in
game's file scope per `game/CLAUDE.md`) but is NOT required for TU-5's exit
gate — flag it in the phase's report; orchestrator/user decides whether to
clean it up now or leave it as harmless dead weight.

## 4. Exit gate + Quick Test

**Automated:**
```bash
py tools/smoke.py              # data validation + 5-frame headless boot
py tools/testgate.py check     # GATE PASS required — zero tolerated failures
```
New/extended tests (headless, `SDL_VIDEODRIVER=dummy`/`SDL_AUDIODRIVER=dummy`
already set by every existing test module in this style):
- `load_cutscene_registry` returns the two known ids with the expected keys.
- `Session.end_turn()` on a fresh `RunState` (round 1) sets
  `state.pending_cutscene == {"id": "first_end_turn"}`; calling `end_turn()`
  again after `run_payday` has advanced `round_num` to 2+ never sets it (stays
  `None`).
- `CutscenePlayer` built from an entry pointing at a non-existent file:
  `.enabled is False`, `.done is True` immediately (mirrors
  `test_video_source.py`'s `test_missing_file_done_immediately`); the round
  (in a `game/main.py`-shaped drive, or at minimum the `gp["cutscene"] is
  None` branch logic) proceeds normally the same frame.
- `CutscenePlayer.start()`/`.skip()` call `play_music`/`stop_music` and do not
  raise under SDL dummy (already guaranteed by `engine/audio.py`'s
  exception-swallowing contract — the test just proves TU-5's wiring doesn't
  bypass it, e.g. by calling `pygame.mixer.music` directly instead of through
  `engine.audio`).

**Live Quick Test:**
```bash
py game/main.py
```
1. Watch the intro cutscene play from the registry-sourced path/length (or,
   if run on a machine without cv2, confirm it skips straight to MAIN_MENU as
   before — unchanged behavior).
2. Start a new game, place nothing, press **End Turn**.
3. Confirm the `first_end_turn` cutscene plays full-screen over the (frozen)
   board — with audio if a companion file is set in the registry for that
   entry — and a "press any key to skip" prompt is visible.
4. Click (or press any key) to skip the cutscene.
5. Confirm enemies begin spawning/walking only AFTER the skip — not during
   the video.
6. End a later round's turn (round 2+) and confirm the cutscene does NOT
   replay.
