# Phase SD-6 — UI triggers, per-button override, volume sliders (game + data)

Plan: `planning/SoundEditorPLAN.md` §"Phase SD-6" (lines 396-431), decisions
D5 (per-button click override) and D6 (Master/Music/SFX sliders, ambient on the
SFX bus).

**Depends on**: SD-1 (the `ui.Sounds` subtree + slot schema) and SD-2 (the
`engine/audio/` package — SD-2 converts today's `engine/audio.py` MODULE into a
package while preserving the legacy surface `play_music` / `stop_music` /
`set_volume`). **Do not re-implement either, and do not edit `engine/**` in this
phase.**

**SD-2's pinned API — import ONLY `engine.audio`, never a submodule path.**
Every call returns without raising:

- `engine.audio.set_master_volume(v) -> None`
- `engine.audio.set_bus_volume(bus, v) -> None` — buses are exactly
  `("music", "sfx")`. Both of these **already fan out to a live music track**,
  so a slider is ONE call; build no listener registry.
- `engine.audio.master_volume() -> float` / `engine.audio.bus_volume(bus) -> float`
  — read current values back (slider init).
- `engine.audio.bank.effective_volume(clip, bus_volume=1.0, master=1.0) -> float`
  implements `master × bus × clip.volume`, clamped to [0,1]. **Do not
  re-implement it.**

**`engine.audio.set_volume` is a LEGACY raw `pygame.mixer.music` passthrough**
(pinned by `tools/tests/test_audio.py:33,43`) — it is NOT the volume registry.
Never wire a slider to it.

All citations re-read in the `SoundEditor` worktree on 2026-08-18 (**verified**).
Two plan citations have drifted and are corrected here: `pygame.init()` is
`game/main.py:747` (plan says 588) and the hardcoded boot track is
`game/main.py:999` (plan says 785).

---

## 1. Behavioral spec

### 1.1 Button click — global slot + per-widget override

Today no button makes any sound. `Button` (`game/ui/widgets.py:617`) is a pure
click target: `hover` (`:660`), `hit` (`:670`), `submit` (`:696`).

**`Button.hit()` must NOT be the sound seam.** It is called as a *probe*, not
only on real clicks:

- `game/main.py:1904` — `gp["hud"].hit(px, py) is not None` inside the
  `MOUSEBUTTONDOWN` "am I over UI?" test.
- `game/main.py:1344,1349,1353` — `_tutorial_allows_panel_click` probes
  `confirm_btn.hit` / card `btn.hit` / `action_btn.hit` before routing.
- `game/ui/skinning.py:16-17` states main.py makes **two `Hud.hit()` calls per
  click** by design.

A hook inside `Button.hit` would therefore fire on hover-adjacent probes and
double-fire on the HUD. So the sound is emitted **at the routed click sites**
only.

**Behaviour to build:**

- Clicking any button on the three shell menu screens — main menu, settings,
  pause — plays `ui.Sounds.button_click` (SD-1's slot) on the **sfx** bus.
- If that button's id carries a `sound` value in the screen's override doc
  (`data/ui/screens/<screen>.json` → `widgets.<id>.sound`), **that clip plays
  instead** of `button_click`, for that one button only.
  `ScreenSkinning.apply` already setattrs every override key onto the widget
  object (`game/ui/skinning.py:230-247`, generic loop; `_SPEC_TO_ATTR:61` maps
  only `font`→`font_key`, everything else lands 1:1 — this is exactly how
  `skin`, `tint` and `text_id` got wired for free). So `btn.sound` exists on the
  widget the moment the schema allows the key; no plumbing is needed.
- A disabled button, an invisible button (`is_visible`, `game/ui/skinning.py:71`)
  or a click on empty space plays nothing.
- Clicks routed through `hit_layer` (`game/ui/skinning.py:86`, the retargeting
  layer path) are **out of scope** — see §4 open items.

**Per-widget `sound` value shape**: a **clip reference string**, the same shape
as SD-1's `sound_clip.file` — a path relative to `data/audio/`, e.g.
`"imported/click_heavy.ogg"`. The seam wraps it as a one-clip slot
`{"clips": [{"file": <ref>, "volume": 1.0, "start": 0.0, "end": 0.0}],
"loop": false, "pick": "random"}` and plays it on the sfx bus. Empty string =
"no override, use `button_click`".

**DECIDED (orchestrator, 2026-08-18)** — this shape is settled. The
alternative (a *key into* `ui.Sounds`, the `skin`/`text_id` family precedent) is
off the table: SD-1 confirms `ui.Sounds` stays CLOSED to exactly `button_click`
and `not_enough_love`, so a key reference could only ever name those two.

### 1.2 Not enough love

`ui.Sounds.not_enough_love` plays whenever the player is refused a purchase for
cost reasons. The existing visual feedback is `Button.start_flash`
(`game/ui/widgets.py:678`) with `T("building.flash.not_enough_love")`, at eight
sites in `game/ui/building_ui.py`: `:2134, 2193, 2280, 2323, 2345, 2386, 2422`
and the conditional at `:2467` (which picks between
`building.flash.painter_tile_used` and `building.flash.not_enough_love`).
The flash duration comes from `ui_balance["Timing"]["not_enough_love_duration"]`
(`game/ui/building_ui.py:958`, `data/balancing/ui.json:72`).

**Do not** hook `start_flash` generically — it also carries
`building.action.not_adjacent` (`:2131`) and `building.flash.painter_tile_used`
(`:2466`), which are not this sound. Only the seven unconditional
not-enough-love sites plus the not-enough-love branch of `:2467` fire it.

### 1.3 Master / Music / SFX sliders

Today: `SessionSettings.volume: float = 0.8  # inert (no audio system)`
(`game/ui/settings.py:71`), one bar drawn at `game/ui/settings.py:250-256`
(`_slider_rect`, computed at `:141-142`), labelled `settings.master_audio` with
the note `settings.no_audio` = `"(no audio yet)"`
(`game/ui/settings.py:115-116`, `data/ui/strings.json:144-145`). Nothing reads
`.volume` anywhere else — **measured**: the only reader in `game/`, `tools/`,
`editor/` is `game/ui/settings.py:255`.

**Behaviour to build:** three rows — Master, Music, SFX — each a label plus a
click-to-set bar. Clicking inside a bar sets that value to
`(mx - bar_x) / bar_w`, clamped to `0.0..1.0`; the screen's `hit()` returns the
new action string `"set_volume"`, which the shell passes up as an intent and
`game/main.py` turns into (a) engine bus writes and (b) a persisted write.
**Drag is out of scope** (the shell delivers discrete clicks, not a drag
stream) — click-to-set only, stated in §4.

**Effective volume = `master × bus × clip.volume`** (plan §2.2). SD-6 does not
compute that product: `engine.audio.bank.effective_volume` already does, and
SD-2's setters already fan out to a live music track. SD-6's whole contract is
"the right three numbers reach the right three setters":

- Master slider → `engine.audio.set_master_volume(v)` (applies to both buses).
- Music slider  → `engine.audio.set_bus_volume("music", v)`.
- SFX slider    → `engine.audio.set_bus_volume("sfx", v)` — everything else,
  **including ambient** (D6).

Three calls, no per-track bookkeeping.

Quick-test-visible consequence: Music at 0 stops music while SFX keeps playing;
Master at 0 silences both.

---

## 2. Architecture plan

Four pieces. Three are new files; the fourth is the small set of edits that
consume them.

### 2.1 `game/ui/sound.py` (new, pure) — the UI sound seam

`game/ui` is **pygame-free** and a source-scan `TestPurity` enforces it
(`game/ui/CLAUDE.md:7-11`). `engine.audio` imports pygame, so this module must
**never** import it. Instead it takes a host-injected sink — the exact pattern
already used one file over for the skin hit test
(`game/ui/widgets.py:29-38`, `set_skin_hit_test`, injected from
`game/main.py:832`).

```
_sink = None          # fn(slot_dict, bus) -> None ; None = silent (default)
_sounds = {}          # the ui.Sounds subtree, or {}

set_sink(fn)                  # host injection
configure(ui_sounds)          # ui_balance["Sounds"]
play_slot(name, bus="sfx")    # _sounds.get(name); empty/missing -> no-op
play_click(widget=None)       # widget.sound override -> one-clip slot,
                              # else play_slot("button_click")
play_not_enough_love()        # play_slot("not_enough_love")
```

Every entry point is a **no-op when `_sink` is None or the slot is
empty/missing** — that is what keeps `tools/smoke.py`, every headless test and
every bare screen construction silent and crash-free.

The sink receives a *slot*, not a clip: clip picking and playback belong to
SD-2/SD-4 and live behind the injected adapter in `game/main.py`, which is the
only module allowed to touch `engine.audio` (or SD-4's `gp["sfx"]`) here.
**`gp["sfx"]` is SD-4's game-side `GameSounds` dispatcher, not the raw module**
— consume it, add no bootstrap of your own. If it exposes a "play this slot"
entry point, the adapter is a one-line forward to it.

**`gp["sfx"]` is LIVE from boot and survives teardown** (orchestrator decision,
2026-08-18): SD-4 constructs `GameSounds` right after `engine.audio.init(...)`
at `game/main.py:747` and deliberately leaves `"sfx"` OUT of the
`teardown_gameplay()` tuple at `:1171-1173`. Main-menu, settings and pause
clicks are therefore **audible from the first frame** — nothing about UI sound
is deferred to a later phase, and no wording in this brief should be read as
saying the shell is silent until a run starts.

**The adapter must resolve `gp["sfx"]` LATE — at call time, inside the lambda,
never captured as a value at `:832`.** `:832` may still execute before SD-4's
construction site (SD-4 binds balancing first, and the `gp = {...}` literal is
`:1019`), and a value captured there would be `None` forever: every shell click
would silently no-op with no error to find. Write
`lambda slot, bus: gp["sfx"] and gp["sfx"].play_slot(slot, bus)` (or the
equivalent late lookup), **not** `sink = gp["sfx"].play_slot`. This one line is
the difference between working and silently dead.

### 2.2 `widgets.click(btn, mx, my)` (new helper in `game/ui/widgets.py`)

```
def click(btn, mx, my):
    """True when btn consumed this click; emits the click sound exactly once.
    The routed-click twin of the probe-only `btn.hit`."""
```
Body: `if is_visible-safe hit -> sound.play_click(btn); return True`.
`game/ui/widgets.py` already imports from `.skinning` (`:24`) — importing
`.sound` from `widgets` would be a cycle risk, so **`sound.py` imports nothing
from `widgets`** and `widgets` imports `sound` (leaf module, stdlib only).

Converted call sites (routed clicks only, never probes):

- `game/ui/settings.py` `hit()` (`:196-224`) — back, controls, the two display
  arrows, the three FX toggles.
- `game/ui/main_menu.py` and `game/ui/pause.py` `hit()` bodies — the buttons the
  shell routes through `Shell._main_menu_click` (`game/ui/shell.py:205`) and
  `Shell._pause_click` (`game/ui/shell.py:283`). `Shell._settings_click`
  (`game/ui/shell.py:246`) needs **no edit** — the emission happens inside the
  screen's own `hit()`, which is the only place the *button object* (and hence
  its `sound` attribute) is in hand. This is a deliberate deviation from the
  plan's file list, which named `shell.py` for the seam.

### 2.3 Settings screen: three rows

In `game/ui/settings.py`:

- `SessionSettings`: `volume: float = 0.8` at `:71` becomes
  `master_volume / music_volume / sfx_volume`, all `0.8`. (Safe: one reader,
  `:255`, rewritten in the same edit.) These stay **session** fields; the
  persisted document is loaded by the host and pushed in at boot (§3.4).
- `layout()` (`:127-171`): keep `self._slider_y = y + 4` and lay three rows at a
  12px step (248 / 260 / 272 at the shipped 640×360 geometry), each row =
  a left label at `(cx - 130, row_y - 3)` and a bar `(cx - 45, row_y, 90, 6)`.
  Derive the step from `layout_h("sm")` if it exceeds 12 — `game/ui/CLAUDE.md`'s
  "a text ROW STEP is font-scale, never a literal" rule.
- `back_btn` / `controls_btn` move from `y + 35` to `y + 52` to clear the third
  row (`279 → 296`; `296 + 23 = 319 < 360`). **`data/ui/screens/settings.json`
  authors `btn_back` and an authored rect WINS over code**
  (`ScreenSkinning.apply`), so that doc moves in lockstep or BACK sits on top of
  the SFX bar in game.

  > **DECIDED (orchestrator + user, 2026-08-18) — THE DESIGNER-DOC DIFF.**
  > `data/ui/screens/settings.json` → `widgets.btn_back.rect`:
  > **before `[270, 279, 100, 23]` → after `[270, 296, 100, 23]`.**
  > y only; x/w/h unchanged; `skin: "ui_button_panel"` unchanged; no other
  > widget in that doc is touched. Written through
  > `engine.data_io.write_validated` against `ui_screen.schema.json` — never by
  > hand. This is the ONE authored-content change SD-6 makes.
- `ids` (`:154-171`): keep `audio_label` (now the Master row's label), **drop**
  `audio_note`, add `label_music_volume`, `label_sfx_volume`,
  `bar_master_volume`, `bar_music_volume`, `bar_sfx_volume`. The bars register
  with kind **`"bar"`**, not `"button"` — `tools/tests/test_ui_min_targets.py`
  asserts a 12px floor on `kind == "button"` only, and a 6px-tall track is not a
  button.
- `hit()` (`:196-224`): before the existing branches, test the three bar rects;
  on a hit set the value from `(mx - sx) / sw`, clamp, and return
  `"set_volume"`. `Shell._settings_click` (`game/ui/shell.py:246-281`) gains one
  branch: `if action == "set_volume": return "set_volume"` — the same
  pass-through shape `"set_display_mode"` already has at `:277-278`.
- `submit()` (`:250-256`): three bars instead of one, `settings.no_audio` no
  longer drawn.

### 2.4 `game/core/audio_settings.py` (new) — persistence

Volumes are a **per-machine preference**, not content, so they do **not** live
in `data/` — the settled precedent is `game/core/highscores.py`, whose document
lives at `<repo>/scores/highscores.json` (`:47-49`, gitignored at
`.gitignore:38`) while its **schema stays in `data/schemas/`** (`:82`,
`data_io.write_validated(doc, path, _schema_path(data_dir))`).

Mirror it exactly:

```
default_path(repo_root) -> Path(repo_root) / "settings" / "audio.json"
load(path, data_dir)    -> {"master": .., "music": .., "sfx": ..}
                           missing/corrupt file -> defaults, silently
save(doc, path, data_dir) -> data_io.write_validated(doc, path,
                             data_dir / "schemas" / "audio_settings.schema.json")
```

`.gitignore` gains `settings/`.

---

## 3. File scope + shared-file contract

### 3.1 New files

| File | Contents |
|---|---|
| `game/ui/sound.py` | the pure seam of §2.1 |
| `game/core/audio_settings.py` | load/save of §2.4 |
| `data/schemas/audio_settings.schema.json` | the persisted doc's schema |
| `tools/tests/test_sound_triggers_ui.py` | §4 tests |

### 3.2 `data/schemas/` — EXACTLY two files touched

1. **`data/schemas/ui_screen.schema.json`** — one new property on the
   per-widget override object. Insert alphabetically between `skin` (`:479`)
   and `states` (`:482`), inside
   `properties.widgets.patternProperties.^[a-z][a-z0-9_]*$.properties`
   (opens at `:78`, closes at `:716`):

   ```json
   "sound": {
     "description": "Optional per-button click sound: a clip path relative to data/audio/ (the same shape as a sound_slot clip's `file`). Absent or empty = this button plays ui.Sounds.button_click like every other. game/ui/skinning.py's generic setattr loop threads it onto the widget as `.sound`.",
     "type": "string"
   }
   ```

   Constraints honoured: a single **typed** node, no `oneOf`, no `$ref`
   (`data/CLAUDE.md:410-412,438-455`). The object has **no `required` list**
   (the only two `required` blocks in the file are `:15` and `:33`, both inside
   `background`), so the key is optional by construction and **every existing
   `data/ui/screens/*.json` stays byte-identical**. `additionalProperties:
   false` at `:77` is why the schema edit is required at all.
   Mirror the same edit into the pinned fixture copy
   `tools/tests/fixtures/data/schemas/ui_screen.schema.json`.

2. **`data/schemas/audio_settings.schema.json`** (new) — `type: "object"`,
   `additionalProperties: false`, `required: ["master", "music", "sfx"]`, each a
   `{"type": "number", "minimum": 0, "maximum": 1, "description": ...}`. A
   schema with no document under `data/` is fine — `highscores.schema.json` is
   the standing precedent (`tools/tests/test_smoke_pairing.py` pairs content to
   schemas, not the reverse).

Nothing else under `data/schemas/` is touched **except** the strings additions
in §3.3, which are schema edits to `strings.schema.json` — count them as the
third file if you prefer; they are additive only.

### 3.3 Modified files (game + data), with the reconciliation each carries

| File | Change |
|---|---|
| `game/ui/widgets.py` | `set_click_sound`-free: add `click(btn, mx, my)` (§2.2) next to `contains:176`; do NOT touch `Button.hit:670` |
| `game/ui/settings.py` | §2.3 — `:71`, `:112-116`, `:127-171`, `:196-224`, `:250-256` |
| `game/ui/main_menu.py`, `game/ui/pause.py` | route their `hit()` button tests through `widgets.click` |
| `game/ui/shell.py` | ONE branch in `_settings_click` (`:246-281`) for `"set_volume"` |
| `game/ui/building_ui.py` | `sound.play_not_enough_love()` at the 7 unconditional sites + the not-enough-love branch of `:2467` |
| `game/ui/strings.py` | `:169-170` block — add the two new ids to the fallback dict |
| `data/ui/strings.json` | add `settings.music_audio`, `settings.sfx_audio` (keep `settings.master_audio:144`; **keep** `settings.no_audio:145` defined but unrendered — removing it would mean deleting from `strings.schema.json`'s `required` list at `:756` and from four pinned copies, cost with no benefit) |
| `data/schemas/strings.schema.json` | the two new ids in `properties` (near `:575`) and in the `required` list (near `:755`) |
| `data/ui/screens/settings.json` | **DECIDED** — `widgets.btn_back.rect` `[270, 279, 100, 23]` → `[270, 296, 100, 23]` (y only). Write through `engine.data_io.write_validated` against `ui_screen.schema.json`, never by hand. The only authored-content edit in this phase |
| `data/ui/screen_defaults.json`, `data/ui/screen_previews.json` | regenerate: `py tools/export_ui_layouts.py` |
| `tools/export_ui_layouts.py` | `:127-135` settings id→description map: drop `audio_note`, add the five new ids |
| `tools/tests/test_strings_data.py` | `:150-175` pinned dict — add the two ids |
| `tools/tests/fixtures/data/ui/strings.json`, `.../schemas/strings.schema.json`, `.../schemas/ui_screen.schema.json`, `.../ui/screen_defaults.json` | mirror the live edits; `tools/tests/test_fixture_guard.py` is the reason these copies exist |

**Generated-but-committed**: `screen_defaults.json` / `screen_previews.json` are
diffed against a fresh regeneration by
`tools/tests/test_ui_layout_export.py` — skip the regeneration and that test
goes red.

### 3.4 `game/main.py` — SHARED with SD-4 and SD-7. Three anchors, all additive

SD-4 owns the audio bootstrap (`engine.audio.init(data_dir)` + the boot-time
`GameSounds` at `:747`, and `gp["sfx"]`); SD-7 owns the boot-track deletion.
**SD-6 consumes; it adds no bootstrap of its own.** If SD-4 has not landed, add
nothing and leave the sink uninstalled — every seam degrades to silence by
construction (§2.1), so SD-6 still passes its gate.

**Confirmed disjoint line sets** (orchestrator, 2026-08-18) — keep it that way:
SD-4 owns `:68, :117, :747, :1019-1029, :1089, :1118, :1171-1173, :1476-1478,
:1627, :1664, :2202, :2300`; SD-7 owns `:67, :998-999, :1141, :1154, :2025,
:2026-2031, :2039-2052, :2223-2226, :2252-2255, :2259-2262`; SD-6 owns
`:832, :968-970, :1210-1214` and nothing else.

**Do not change**: the legacy `play_music` / `stop_music` / `set_volume` return
`None` (pinned by `tools/tests/test_audio.py:23-44`). Only SD-2's new calls
return `bool`.

| # | Anchor (current line) | Addition |
|---|---|---|
| A | `game/main.py:832` — `widgets.set_skin_hit_test(assets.hit_opaque)` | immediately after: `sound.set_sink(<adapter that looks `gp["sfx"]` up LATE, at call time — see §2.1>)` and `sound.configure(ui_balance["Sounds"])`. The adapter is the ONLY place `engine.audio` / `gp["sfx"]` is referenced for UI sound. |
| B | `game/main.py:968-970` — the `shell = Shell(...)` construction (verified: `:968` is `shell = Shell(view_w, view_h, ui_balance, start_state=start,`) | immediately after: load `audio_settings.default_path(REPO)`, copy the three values onto `shell.settings`, and make the three SD-2 calls (`set_master_volume`, `set_bus_volume("music", …)`, `set_bus_volume("sfx", …)`). Mirrors the `shell.set_highscores(...)` seeding at `:977`. |
| C | `game/main.py:1210-1214` — `elif intent == "set_display_mode":` | a sibling `elif intent == "set_volume":` branch: the same three SD-2 calls, then `audio_settings.save(...)`. |

Ordering: A (`:832`) and B (`:968`) both come *after* SD-4's
`pygame.init():747` bootstrap point — no conflict. But **do not infer that
`gp["sfx"]` is already bound at `:832`**: SD-4's `gp = {...}` registry literal
is `:1019`, i.e. AFTER both, which is exactly why the sink resolves it lazily
(§2.1). SD-4 also keeps `"sfx"` out of the `teardown_gameplay()` tuple at
`:1171-1173`, so the dispatcher survives a return to the main menu and menu
clicks stay audible for the whole process. SD-7's deletion target is `:999`
(`play_music(data_dir / "audio" / "Bass_and_drum_Duo.wav", loop=True)`), between
B and C and touched by neither. **No SD-6 anchor overlaps an SD-4 or SD-7 line.**

If the orchestrator would rather SD-6 not touch `game/main.py` at all: anchors A
and B can be handed to SD-4 as a two-line addendum, and C is the only one that
must be SD-6's (it is the intent this phase invents). Say so before dispatch.

### 3.5 Out of scope

`engine/**` (SD-2's), the editor's screen-editor UI for authoring the `sound`
value (a designer sets it via the editor's existing per-widget override
editing — a clip picker there is SD-3 territory), the HUD / building-panel /
in-game modal buttons (their `hit()` is probe-called — §4), and music slot
selection (SD-7).

---

## 4. Exit gate + Quick Test

### Tests to write (bare minimum — 7 cases in one file)

`tools/tests/test_sound_triggers_ui.py`, using a fake sink
(`sound.set_sink(lambda slot, bus: calls.append((slot, bus)))`) and, for the
data cases, `TempDataCase` (`tools/tests/temp_data.py`) — **never** live
`data/`, never a write into `data/`:

1. `widgets.click` on a `Button` with no `sound` → the sink got
   `ui.Sounds.button_click` on bus `"sfx"`.
2. The same button with `btn.sound = "imported/x.ogg"` → the sink got a one-clip
   slot naming that file, **not** `button_click`.
3. No sink installed (module default) and a missing slot → no call, no raise.
4. `sound.play_not_enough_love()` fires the `not_enough_love` slot.
5. `SettingsScreen.hit` at the left edge / midpoint of the master bar sets
   `0.0` / `~0.5` and returns `"set_volume"`; `Shell._settings_click` passes
   `"set_volume"` through as an intent. (Assert the screen/shell values only —
   `engine.audio`'s setters are SD-2's tests, not yours.)
6. `audio_settings.save` → `load` round-trips in a tmpdir; a value of `1.5`
   fails validation.
7. In the temp data copy: every `data/ui/screens/*.json` still validates against
   the edited `ui_screen.schema.json`; a widget spec with `"sound": "a.ogg"`
   validates; `"sound": 5` fails.

Do not add coverage beyond these seven.

### Exit gate (run exactly these)

```
py tools/smoke.py
py -m pytest tools/tests/test_sound_triggers_ui.py -q
py -m pytest tools/tests/test_ui_skinning.py -q
py -m pytest tools/tests/test_ui_layout_export.py -q
py -m pytest tools/tests/test_ui_min_targets.py -q
py -m pytest tools/tests/test_strings_data.py -q
py -m pytest tools/tests/test_shell.py -q
```

**This list deliberately OVERRIDES the plan doc's gate**
(`planning/SoundEditorPLAN.md:427-428`), by orchestrator decision 2026-08-18 —
it is a correction, not an omission. The plan named
`tools/tests/test_ui_screens.py`, which **does not exist** (verified); the
screen-override tests are `test_ui_skinning.py`. The layout/strings files are
here because §3.3 regenerates or repins them.

Nothing else. Do **not** run `py tools/testgate.py check`, `--affected`, or a
tier sweep (`-m core` / `-m editor` / `-m meta`) — the `test_guard.py` hook
denies all of those from a subagent, and the single full gate is the main
session's step at handoff (root `CLAUDE.md` §"Test Suite Policy" is the
authority).

### Quick Test (in game — the orchestrator or user runs this)

`py game/main.py` →
1. Hover, then click, main-menu buttons — one click sound per click, none on
   hover, none on a click that lands on empty background.
2. Settings → three rows read Master / Music / SFX, BACK and CONTROLS sit clear
   of the SFX bar.
3. Click the Music bar at its far left → music stops, button clicks still audible.
4. Click the SFX bar at its far left → button clicks go silent, then click it
   back to ~full.
5. Click Master at far left → everything silent; restore.
6. BACK → start a run → try to place a building you cannot afford: the
   NOT ENOUGH LOVE flash is accompanied by the not-enough-love sound, at the
   current SFX × Master volume.
7. Quit and relaunch → the three slider positions are the ones you left
   (`<repo>/settings/audio.json`).

---

## Settled decisions + the one remaining item

**Settled by the orchestrator (with the user) on 2026-08-18 — do not re-open:**

1. **Per-widget `sound` = a clip path relative to `data/audio/`** (§1.1).
   `ui.Sounds` stays closed to `button_click` + `not_enough_love`.
2. **`data/ui/screens/settings.json` `widgets.btn_back.rect` moves
   `[270, 279, 100, 23]` → `[270, 296, 100, 23]`** (§2.3), through
   `write_validated`. User-approved.
3. **The §4 test list replaces the plan doc's gate** — `test_ui_screens.py`
   does not exist.
4. **`gp["sfx"]` is boot-time and teardown-surviving**, so menu clicks are
   audible from the first frame; the sink still resolves it lazily (§2.1).

**Remaining item (orchestrator's call, not a blocker):**

- **`game/main.py` anchors A and B** could be folded into SD-4's diff (§3.4);
  anchor C must stay SD-6's, since `"set_volume"` is the intent this phase
  invents.

**Carried to the final report as a pre-existing find — DO NOT FIX:** `SettingsScreen`'s docstring (`game/ui/settings.py:16`)
   promises a `"save_display_default"` action, but `hit()` (`:196-224`) never
   tests `self.default_btn` and no `game/main.py` branch handles that intent —
   the SET DEFAULT button is dead. **Out of scope by orchestrator decision** —
   left flagged here only because SD-6 edits the same two methods.
