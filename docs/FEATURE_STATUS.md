# Feature Status — How To Be Human

Where every planned feature stands in the build. One row per feature, three
columns for the three things that finish independently: the **logic** that makes
it work, the **art** that makes it visible, and the **audio**.

Companion docs: [`PRODUCTION_BOARD.md`](PRODUCTION_BOARD.md) (the full card-level
board) · [`production-board.svg`](production-board.svg) (the visual).

## Status key

**Logic and audio**

| | Meaning |
|---|---|
| **Shipped** | Implemented and wired into the running game |
| **Partial** | Works, but not to the planned depth |
| **Not started** | Nothing in code, nothing in data |

**Art** — a slot having a spritesheet bound is not the same as that art being
finished. A single still frame imported into a slot renders fine and looks done
from the outside, so art is graded by what is actually in the sheet:

| | Meaning |
|---|---|
| **Shipped** | Full animation set — every state the category declares |
| **Idle only** | Animated, but idle is the only state. No attack, death, hurt, place or upgrade |
| **Placeholder** | A single static frame standing in for the whole sheet |
| **Needs rework** | Art exists but is superseded — to be redrawn or reimported |
| **Not started** | No sheet bound |

## Read this first

**Audio is a project-wide gap.** `engine/audio.py` provides music playback only —
`play_music`, `stop_music`, `set_volume`. There is no sound-effect API, and
`data/audio/` holds a single track. Every per-feature sound (placement, attack,
damage, death, repair, upgrade) is **Not started** regardless of how finished the
rest of that feature is. This is one system to build, not forty.

**Art is earlier than slot counts suggest.** 210 of 242 slots have something
bound, but by frame content: **25 slots have a complete animation set, 69 are
idle-only, 116 are a single static frame, 25 are empty.** Two building families
carry nearly all the finished animation work.

**Effects are shared, not bespoke.** `game/ui/effects.py` runs 10 procedural
effect kinds off 10 triggers in `data/balancing/vfx.json`. Every building gets
placement, damage and death effects from the shared triggers; none has its own.

---

## Buildings

| Feature | Logic | Art | Audio | Art detail |
|---|---|---|---|---|
| Stone Thrower | Shipped | **Shipped** | Not started | Full set across all three tiers — 6 rows, 90 frames |
| Flute Player | Shipped | **Shipped** | Not started | The most complete art in the game — 9 rows, 153 frames, all three tiers |
| Meditator | Shipped | Idle only | Not started | 7-frame idle, all three tiers. No attack/death/hurt |
| Sun Scorcher | Shipped | Idle only | Not started | T1 has a 10-frame idle; Radiant Beam and Laser Beam are placeholders |
| AOE Mortar | Shipped | Idle only | Not started | T1 has a 10-frame idle; Maw Catapult and Maw Cannon are placeholders |
| Storm Priest | Shipped | Idle only | Not started | 2-frame idle across all three tiers — barely animated |
| Blocker | Shipped | Idle only | Not started | 10-frame idle |
| Wall Builder | Shipped | Idle only | Not started | 2-frame idle. Wall pieces and bottom overlays are separate slots |
| Base Building (the hole) | Shipped | Placeholder | Not started | Single frame per level across all 10 upgrade levels |
| Painter | Shipped | Placeholder | Not started | All three tiers static — Cave Painter, Maestro, Art Factory |
| Speed Booster | Shipped | Placeholder | Not started | All three tiers static |
| Damage Booster | Shipped | Placeholder | Not started | All three tiers static |
| Health Booster | Shipped | Placeholder | Not started | All three tiers static |

Buildings hold 92 slots: **18 full, 26 idle-only, 48 static**. Defenders and
Musicians account for every fully-animated building in the game.

## Enemies & combat

Every enemy and boss is flagged for an art rework, so the art column reads
**Needs rework** throughout. The detail column records what is there now.

| Feature | Logic | Art | Audio | Art detail |
|---|---|---|---|---|
| Normal Soldier | Shipped | Needs rework | Not started | Currently the best enemy art — 4 rows, 32 frames, eras 1–4 |
| Small Raider | Shipped | Needs rework | Not started | Single static frame in all four eras |
| Siege Cannon | Shipped | Needs rework | Not started | Single static frame in all four eras |
| Boss | Shipped | Needs rework | Not started | Era 0 animated (3 rows, 18 frames); eras 1–3 static; era 4 has no slot |
| Formation | Shipped | Not started | Not started | No sprite slots exist for any era |
| Kidnap | Shipped | Not started | Not started | The `kidnap` animation row is declared but never imported |
| Corpses | Shipped | Needs rework | Not started | Rides on enemy death frames |
| Pathfinding | Shipped | — | — | Weighted routing, dynamic goal finding, late-round damage reduction |

Enemies hold 23 slots: **7 full, 11 static, 5 with no slot at all.**

## Map

| Feature | Logic | Art | Audio | Art detail |
|---|---|---|---|---|
| Tile Map | Shipped | Idle only | Not started | Buildable/combat/spawning tiles animate (16 frames); 2 background tiles and the engine slot are empty |
| Tile Conditions | Shipped | Idle only | Not started | Mountain, Pond and Forest animate at 18 frames. All four Grass variants and every spawning variant are empty — 8 of 28 slots |
| Tile Unlocking | Shipped | Idle only | Not started | Unlock animation present; adjacency-locked with rising cost |
| Decoration | Shipped | Placeholder | Not started | 52 slots, 43 static. Rocks, bushes and trees are all single-frame |
| **Seasons** | **Not started** | **Not started** | **Not started** | Nothing exists: no season state, no seasonal tiles, no change transition, no seasonal music |

## Progression

| Feature | Logic | Art | Audio | Notes |
|---|---|---|---|---|
| Waves | Shipped | — | Not started | Phase loop, spawn ramping, scale tiers every N levels |
| Currency (love) | Shipped | Placeholder | Not started | Income and payday work; the love icon is a single frame |
| Levelup & XP | Shipped | Placeholder | Not started | XP thresholds with growth, reward screen. XP icon single frame |
| Lightning Strike | Shipped | Not started | Not started | Player active ability, 3 levels of cooldown / damage / radius. Drawn procedurally — no VFX slot bound |
| Boss Bonuses | Shipped | Placeholder | Not started | Story choice with a lasting bonus after a boss round |
| Tutorial | Shipped | Not started | Not started | Director, tooltips and forced click targets all work; both tutorial marker slots are empty |
| Cutscenes | Shipped | Partial | Partial | Player and registry work; 2 of 6 planned videos exist |

## UI

All UI art is scheduled for reimport, so the art column reads **Needs reimport**
throughout. Buttons currently carry four state rows (idle, hover, pressed,
disabled) at one frame each; panels and icons are single frames.

| Feature | Logic | Art | Audio | Notes |
|---|---|---|---|---|
| HUD | Shipped | Needs reimport | Not started | Readout panel, income tooltip, phase and wave indicators |
| Upgrade Menu | Shipped | Needs reimport | Not started | Build and upgrade screens |
| Main Menu | Shipped | Needs reimport | Not started | Background slot is empty |
| Pause Menu | Shipped | Needs reimport | Not started | |
| Settings Menu | Shipped | Needs reimport | Not started | |
| Credits | Shipped | Needs reimport | Not started | |
| Game Over | Shipped | Needs reimport | Not started | |
| Game Log | Shipped | Needs reimport | — | In-run event log |
| Cheat Menu | Shipped | Needs reimport | — | Development tool |
| Name Entry | Shipped | Needs reimport | Not started | |

## Effects

| Feature | Logic | Art | Audio | Notes |
|---|---|---|---|---|
| Procedural VFX | Shipped | Not started | Not started | 10 effect kinds, 10 triggers, fully data-driven. All 8 VFX sprite slots are empty — everything currently draws procedurally |

---

## Where the work is

**42 features tracked. 41 have working logic.** The build is far ahead of its art
and audio, and that is where the remaining effort sits.

1. **Audio.** One missing system — a sound-effect layer over `engine/audio.py` —
   accounts for the largest single block of unfinished work. Until it exists, no
   feature is done.

2. **Animation depth.** Only 25 of 235 slots carry a full animation set. 116 are
   a single static frame. The pattern is consistent: first tier of a family gets
   an idle, later tiers get a still. Worst affected: all three Boosters, Painter,
   Base Building, and every enemy except the Normal Soldier.

3. **Enemy and boss rework.** All enemy art is being redrawn. Formation has no
   slots at all, Boss era 4 has no slot, and the `kidnap` animation was never
   imported.

4. **UI reimport.** Every screen's art is being reimported. The Main Menu
   background slot is empty.

5. **Seasons.** The only feature with nothing built at all.

6. **Cutscene video.** Four of six films outstanding.

7. **Empty slots worth closing.** 25 slots have nothing bound: all 8 VFX, all 4
   Grass tile conditions, every tile-condition spawning variant, both tutorial
   markers, camera start and start area.
