# System Diagram — Design Brief

**For:** a graphic designer (human or AI) who has **never seen this project.**
**Deliverable:** one hero diagram, *"How To Be Human — System Map"*.
**You do not need to read any code.** Everything you need is in this file.

> **The one-sentence goal.** A newcomer should look at this diagram for 30 seconds
> and be able to say: *"There are four layers. Data is the foundation. Two
> applications sit on top of a shared engine. They never talk to each other."*
>
> If a viewer can say that, the diagram works. Everything else is detail.

---

## Table of contents

1. [Brief-me-first: what this project is](#1-brief-me-first-what-this-project-is)
2. [What the diagram must communicate](#2-what-the-diagram-must-communicate)
3. [Canvas, grid and export](#3-canvas-grid-and-export)
4. [The visual language](#4-the-visual-language)
5. [Colour palette](#5-colour-palette)
6. [Typography](#6-typography)
7. [Geometry, strokes and spacing](#7-geometry-strokes-and-spacing)
8. [Layout map (with coordinates)](#8-layout-map-with-coordinates)
9. [Node inventory — exact copy](#9-node-inventory--exact-copy)
10. [Edge inventory — exact copy](#10-edge-inventory--exact-copy)
11. [The forbidden-link barrier](#11-the-forbidden-link-barrier)
12. [Callout cards](#12-callout-cards)
13. [The legend rail](#13-the-legend-rail)
14. [Title block and footer](#14-title-block-and-footer)
15. [Rules, do's and don'ts](#15-rules-dos-and-donts)
16. [Accessibility requirements](#16-accessibility-requirements)
17. [Acceptance checklist](#17-acceptance-checklist)
18. [Appendix — optional companion diagrams](#18-appendix--optional-companion-diagrams)

---

## 1. Brief-me-first: what this project is

Read this once. It is all the domain knowledge you need, and it is enough to make
every label you draw correct.

**The product** is a video game called **How To Be Human** — an isometric tower
defence game. The player spends a currency called **love** to unlock tiles on a
grid and place musicians and defenders that protect a place called **"the hole"**
from waves of enemies. The enemies represent society's pressures. It's melancholy
and hand-made in tone, not sci-fi.

**The codebase has four parts**, and the whole point of the diagram is to show how
they stack:

| Part | Folder | Plain-English description |
|---|---|---|
| **The game** | `game/` | The thing players run. Opens a window, runs the rounds, draws the world. |
| **The editor** | `editor/` | An in-house tool the designers run. It is the *only* way a human is supposed to change anything about the game — balance numbers, maps, artwork, menu layouts. |
| **The engine** | `engine/` | A small shared library both of the above are built on. Coordinates, drawing, animation, physics. It knows nothing about *this* game specifically. |
| **The data** | `data/` | Plain text files (JSON) holding every number, every map, every artwork binding. **Nothing is hard-coded in the programs.** |

**Five facts that the diagram exists to make obvious.** Every design decision below
serves one of these:

1. **Data is the foundation, and everything is validated.** Every file has a
   schema. Nothing can be written to `data/` without passing it.
2. **The engine is shared.** Both applications sit on top of the same one, which
   is why the editor can show a truthful preview of what the game will draw.
3. **The game and the editor never import each other.** This is a hard
   architectural rule, and it is the single most distinctive thing about this
   codebase. It deserves its own visual mark.
4. **The editor still *launches* the game** — but as a completely separate
   process, not as part of itself. This is a different kind of relationship from
   "imports", and must look different.
5. **Two kinds of author exist:** human designers (who work through the editor)
   and AI agents (who edit files directly, but only through the same validation
   gate). Both are shown.

**Things you do NOT need to depict:** individual classes, function names, the round
loop, combat rules, or anything about how the game plays. This is a *structural*
diagram, not a gameplay one.

**Tone.** Precise, calm, technical-editorial. Think a well-set reference page or a
good infrastructure poster — **not** a startup marketing graphic. No gradients, no
drop shadows, no glow, no 3-D, no isometric styling of the boxes themselves (the
*game* is isometric; the *diagram* is flat and orthogonal — do not confuse the
two).

---

## 2. What the diagram must communicate

Ranked. If space forces a compromise, protect the higher rank.

| # | Message | Carried by |
|---|---|---|
| 1 | There are **four stacked layers**, in a fixed order. | The horizontal band structure. |
| 2 | **Data is the bottom, and it is gated by schemas.** | The band position + the schema gate bar drawn across the top of the data band. |
| 3 | **Game and editor are peers that never touch.** | Two equal-weight side-by-side boxes + the ⊘ barrier between them. |
| 4 | **Both stand on the same engine.** | Two heavy arrows converging into one engine box. |
| 5 | **The editor launches the game as a separate process.** | A visually distinct dashed arc with a ▶ badge. |
| 6 | **Humans author through the editor; agents author through validation.** | The top band and its two downward paths. |
| 7 | Each layer contains a handful of named parts. | The chips inside each package box. |
| 8 | Everything is verified by an automated gate. | The bottom verification band. |

---

## 3. Canvas, grid and export

**Primary artboard.** `2400 × 1720 px` at 1×. Landscape.
Design at 1×; every coordinate in §8 is a 1× pixel value.

| Setting | Value |
|---|---|
| Background | solid `#FAF8F4` (see palette). **Not** pure white. |
| Outer margin | 100 px on all four sides |
| Diagram column | `x = 100 → 1900` (width 1800) |
| Legend rail | `x = 1980 → 2300` (width 320) |
| Rail divider | 1 px `hairline` vertical rule at `x = 1940`, `y = 260 → 1560` |
| Base spacing unit | **8 px.** Every gap, padding and offset is a multiple of 8. |
| Column grid (inside the diagram column) | 12 columns, 128 px wide, 24 px gutter → `12×128 + 11×24 = 1800` ✔ |
| Package-box track | all four package boxes span `x = 160 → 1840`, or a half of it. Nothing else aligns to the column edge. |

**Required exports.**

| File | Spec |
|---|---|
| `system-map.pdf` | vector, 1× dimensions, all text as live text (not outlined) |
| `system-map.svg` | vector, live text, IDs on layers matching §9's node IDs |
| `system-map@2x.png` | 4800 × 3440, 96 dpi |
| `system-map@1x.png` | 2400 × 1720 |
| `system-map-dark.pdf` + `@2x.png` | the dark variant (see §5.4) |

**Layer/group naming in the source file** — use these exact names so the file is
navigable: `00-background` · `01-bands` · `02-nodes` · `03-edges` · `04-barrier` ·
`05-callouts` · `06-legend` · `07-titleblock` · `08-footer`.

---

## 4. The visual language

Three encodings, each carrying exactly one meaning. **Never overload one.**

### 4.1 Shape = *what kind of thing it is*

| Shape | Means | Used for |
|---|---|---|
| **Rounded rectangle, 16 px radius, 2.5 px stroke** | a **package** — a top-level part of the system | The Game, The Editor, The Engine, The Data |
| **Rounded rectangle, 8 px radius, 1.5 px stroke, tinted fill** | a **subsystem chip** — a named part inside a package | `coords`, `render`, `balancing/`, `viewport`, … |
| **Full-round pill (stadium), no stroke, solid fill** | an **actor** — a person or agent, not code | Designer, AI Agent |
| **Horizontal bar with a notched left edge, 8 px radius** | a **gate** — everything must pass through it | `data/schemas/` |
| **Small square chip, 4 px radius** | a **tool** — a script that runs and reports | `smoke.py`, `testgate.py`, `build.py`, `CI` |
| **Card, 10 px radius, paper fill, 1 px hairline** | a **callout** — an annotation, not part of the system | the three callout cards |

### 4.2 Colour = *which layer it belongs to*

One hue per band. Fully specified in §5. **Colour never carries a second meaning**
— it does not indicate importance, status, or direction.

The **one exception** is the signal red `#D93025`, which is reserved *exclusively*
for the "these two must never connect" barrier. Red appears nowhere else in the
diagram. That reservation is what makes it read instantly.

### 4.3 Line = *what kind of relationship it is*

| Line | Means | Spec |
|---|---|---|
| **Heavy solid, 3 px** | *the dependency spine* — "is built on" | solid triangle arrowhead 14×10 |
| **Solid, 2 px** | "reads" / "uses" | solid triangle arrowhead 12×9 |
| **Dotted, 2 px, dash `3 5`** | "writes to" — an authoring action | solid triangle arrowhead 12×9 |
| **Dashed, 2.5 px, dash `10 6`** | "launches as a separate process" | open chevron arrowhead, not filled |
| **Dashed, 3 px, dash `8 8`, colour `#D93025`** | **forbidden** — never used as a connector, only as the barrier | no arrowhead; carries the ⊘ badge |
| **Hairline, 1 px, dash `2 4`, Ink-45** | a callout leader line | small 4 px dot at the target end, no arrowhead |

⚠️ **Arrows always point in the direction of the dependency**, i.e. *from* the
thing that needs something *to* the thing it needs. Every arrow in this diagram
therefore points **downward or sideways**, never upward — with exactly one
exception (E9, the process launch, which arcs). Keep that consistency: it is a big
part of why the diagram reads fast.

---

## 5. Colour palette

All values are final. Do not substitute, do not "brand-align", do not add a sixth
hue.

### 5.1 Neutrals

| Token | Hex | Use |
|---|---|---|
| `paper` | `#FAF8F4` | canvas background, label plates behind edge labels, callout card fill |
| `ink` | `#14161A` | **all primary text**, node titles, chip labels, arrowheads |
| `ink-70` | `#4A5058` | captions, edge labels, callout body text |
| `ink-45` | `#8A9099` | band labels, footnotes, leader lines |
| `hairline` | `#DED8CE` | 1 px rules, band separators, callout card borders |

### 5.2 Layer hues

Each layer gets three values: a **stroke** (outlines, edges leaving that layer), a
**fill** (the pale tint inside boxes and chips), and a **chip** (the saturated
swatch used in the legend and for the band label tag).

| Layer | Stroke | Fill | Chip | Notes |
|---|---|---|---|---|
| **Authors** (people) | `#6B6257` | `#F1ECE3` | `#8C8072` | Deliberately the least saturated — people should not out-shout the system. |
| **The Game** | `#10606B` | `#DFF0F1` | `#1B8794` | Teal. |
| **The Editor** | `#5B3A8C` | `#EFE8F8` | `#7A54B5` | Violet. Sits beside teal — 82° of hue separation, so they stay distinct. |
| **The Engine** | `#27497F` | `#E4EBF7` | `#3D68B2` | Slate blue. Give the Engine box the **palest fill** of the four packages — it is a substrate, not a headline. |
| **The Data** | `#9A6208` | `#FCF0D8` | `#DB9B1E` | Amber. The warmest and most saturated: data is the foundation and should feel like the ground of the image. |
| **Verification** | `#2F6B4F` | `#E4F1E9` | `#43946B` | Green. Small band, small chips. |

### 5.3 Accent

| Token | Hex | Use — **and nothing else** |
|---|---|---|
| `signal` | `#D93025` | The forbidden barrier line and its ⊘ badge. |

### 5.4 Dark variant

Produce a second version, same geometry, same type, only these substitutions:

| Light token | Dark value |
|---|---|
| `paper` | `#14161A` |
| `ink` | `#F3F0EA` |
| `ink-70` | `#B4B8BE` |
| `ink-45` | `#7C828A` |
| `hairline` | `#2C3037` |
| every layer **fill** | that layer's stroke colour at **14 % opacity** over the dark paper |
| every layer **stroke** | that layer's **chip** colour, lightened 12 % |
| `signal` | `#FF6B5E` |

Do not restyle anything else for dark mode. Same layout, same type sizes.

---

## 6. Typography

### 6.1 Families

| Role | Family | Fallback stack |
|---|---|---|
| **Primary UI/label** | **Inter** (variable) | Söhne · Neue Haas Grotesk Display · Helvetica Neue · Arial |
| **Code / file paths** | **JetBrains Mono** | IBM Plex Mono · SF Mono · Consolas · Menlo |
| **Wordmark only** | **Pixel Emulator** | *(fall back to Inter 800 if unavailable)* |

**About Pixel Emulator:** it is the actual in-game font of How To Be Human — a
pixel/bitmap face. It carries the product's identity, so it appears **once**, in the
title block, at **≥ 44 px**. Use it nowhere else. It is illegible below ~24 px and
will wreck the diagram if applied to labels. If it is unavailable, use Inter 800 and
add 0.02em tracking; do **not** substitute another pixel font.

### 6.2 Scale

All sizes are 1× px on the 2400 × 1720 artboard.

| Element | Family / weight | Size / line-height | Colour | Case & tracking |
|---|---|---|---|---|
| Wordmark | Pixel Emulator | 56 / 60 | `ink` | as typed |
| Diagram title | Inter 700 | 34 / 40 | `ink` | as typed |
| Diagram subtitle | Inter 400 | 20 / 30 | `ink-70` | as typed |
| **Band label** | Inter 700 | 15 / 15 | `ink-45` | **UPPERCASE**, tracking `+0.16em` |
| **Node title** | Inter 600 | 26 / 30 | `ink` | as typed |
| **Node path** | JetBrains Mono 400 | 16 / 20 | that layer's **stroke** | as typed |
| **Chip label** | Inter 500 | 18 / 22 | `ink` | as typed |
| **Chip caption** | Inter 400 | 14 / 19 | `ink-70` | sentence case |
| **Edge label** | Inter 500 | 15 / 19 | `ink-70` | sentence case |
| Legend section heading | Inter 700 | 14 / 14 | `ink-45` | UPPERCASE, tracking `+0.14em` |
| Legend item | Inter 400 | 14 / 20 | `ink` | as typed |
| Callout title | Inter 600 | 17 / 22 | `ink` | as typed |
| Callout body | Inter 400 | 14 / 20 | `ink-70` | as typed |
| Footer / footnote | Inter 400 | 12 / 17 | `ink-45` | as typed |

⚠️ **All text is `ink`, `ink-70` or `ink-45` — never a layer colour**, with the
single exception of the mono **node path** line. This guarantees every word passes
contrast, and it keeps colour meaning "which layer", not "which word matters".

⚠️ **Edge labels sit on a `paper` plate** — a filled rectangle in the background
colour, 6 px padding, no stroke, no radius — so the line never runs through the
type. This is not optional; unplated edge labels are the single most common way a
diagram like this becomes unreadable.

---

## 7. Geometry, strokes and spacing

| Property | Value |
|---|---|
| Corner radius — package box | 16 px |
| Corner radius — chip | 8 px |
| Corner radius — tool chip | 4 px |
| Corner radius — callout card | 10 px |
| Corner radius — actor pill | fully rounded (h/2) |
| Stroke — package box | 2.5 px, that layer's `stroke` |
| Stroke — chip | 1.5 px, that layer's `stroke` at 60 % opacity |
| Stroke — callout card | 1 px `hairline` |
| Padding inside a package box | 24 px all round; 56 px at the top to clear the title + path lines |
| Gap between chips | 16 px |
| Gap between bands | 40 px |
| Band background | that layer's `fill` at **35 % opacity**, full-bleed across the diagram column, radius 12 px |
| Band label position | 12 px above the band's top edge, left-aligned to `x = 100` |
| Arrowhead — solid | filled triangle, 14 × 10 px (spine) / 12 × 9 px (normal) |
| Arrowhead — process launch | open chevron, 2.5 px stroke, 16 px wide, 45° |
| Shadows | **none** |
| Gradients | **none** |
| Opacity on strokes/text | **none** (only band backgrounds and chip strokes use opacity) |

**Corner routing.** Edges are orthogonal (right-angle) with **12 px rounded
corners**, except E9 (the process launch), which is a smooth arc. No diagonal
straight lines, no bezier wiggles.

---

## 8. Layout map (with coordinates)

The whole diagram, to scale, as ASCII. Coordinates below are exact.

```
 x:100                                                        1900  1940 1980   2300
  ┌──────────────────────────────────────────────────────────────┐  │ ┌──────────┐
  │ HOW TO BE HUMAN / System Map / subtitle       stack · stats   │  │ │          │  y:100–220
  ├──────────────────────────────────────────────────────────────┤  │ │  LAYERS  │
  │ AUTHORS                                                      │  │ │  ▪▪▪▪▪▪  │
  │        ( Designer )                    ( AI Agent )          │  │ │          │  y:260–380
  ├──────────────────────────────────────────────────────────────┤  │ │  RELAT-  │
  │ APPLICATIONS                                                 │  │ │  IONSHIPS│
  │   ┌──────────────────┐   ⊘   ┌──────────────────┐            │  │ │  ━━▶ ┈┈▶ │
  │   │  The Game        │ never │  The Editor      │            │  │ │          │
  │   │  game/           │import │  editor/         │            │  │ │  SHAPES  │
  │   │  [2 × 3 chips]   │ each  │  [2 × 3 chips]   │            │  │ │  ▢ ▭ ◗ ◍ │  y:420–840
  │   └──────────────────┘ other └──────────────────┘            │  │ │          │
  │              ╰────── Play ▶ (arc) ──────╯                    │  │ │  THREE   │
  ├──────────────────────────────────────────────────────────────┤  │ │  RULES   │
  │ ENGINE                                                       │  │ │  1 2 3   │
  │   ┌──────────────────────────────────────────────────┐       │  │ │          │
  │   │  The Engine  engine/    [6 chips in one row]     │       │  │ ├──────────┤
  │   └──────────────────────────────────────────────────┘       │  │ │ C1 card  │  y:880–1100
  ├──────────────────────────────────────────────────────────────┤  │ ├──────────┤
  │ DATA                                                         │  │ │ C2 card  │
  │   ┌──────────────────────────────────────────────────┐       │  │ ├──────────┤
  │   │  The Data  data/                                 │       │  │ │ C3 card  │
  │   │  ◗▰▰▰ data/schemas/ — every write passes here ▰▰▰│       │  │ │          │  y:1140–1420
  │   │  [6 chips in one row]                            │       │  │ │          │
  │   └──────────────────────────────────────────────────┘       │  │ │          │
  ├──────────────────────────────────────────────────────────────┤  │ │          │
  │ VERIFICATION   [smoke] [testgate] [build] [CI]               │  │ │          │  y:1460–1560
  └──────────────────────────────────────────────────────────────┘  │ └──────────┘
  ──────────────────────────────────────────────────────────────────────────────    y:1592
  footer                                                                v1 · date   y:1608
```

### 8.1 Band rectangles

All bands span `x = 100 → 1900` (width 1800).

| Band | Label | y | h | bottom |
|---|---|---:|---:|---:|
| A | `AUTHORS` | 260 | 120 | 380 |
| B | `APPLICATIONS` | 420 | 420 | 840 |
| C | `ENGINE` | 880 | 220 | 1100 |
| D | `DATA` | 1140 | 280 | 1420 |
| E | `VERIFICATION` | 1460 | 100 | 1560 |

Band gaps are 40 px throughout. The band label tag sits 12 px above its band's top
edge, left-aligned to `x = 100`.

### 8.2 Node rectangles

| ID | Node | x | y | w | h | right | bottom |
|---|---|---:|---:|---:|---:|---:|---:|
| N1 | Designer (pill) | 380 | 290 | 340 | 60 | 720 | 350 |
| N2 | AI Agent (pill) | 1280 | 290 | 340 | 60 | 1620 | 350 |
| N3 | The Game (package) | 160 | 444 | 780 | 372 | 940 | 816 |
| N4 | The Editor (package) | 1060 | 444 | 780 | 372 | 1840 | 816 |
| N5 | The Engine (package) | 160 | 904 | 1680 | 172 | 1840 | 1076 |
| N6 | The Data (package) | 160 | 1164 | 1680 | 234 | 1840 | 1398 |
| N6g | Schema gate bar *(inside N6)* | 184 | 1230 | 1632 | 44 | 1816 | 1274 |
| N7 | `tools/smoke.py` | 160 | 1484 | 402 | 52 | 562 | 1536 |
| N8 | `tools/testgate.py` | 586 | 1484 | 402 | 52 | 988 | 1536 |
| N9 | `tools/build.py` | 1012 | 1484 | 402 | 52 | 1414 | 1536 |
| N10 | `GitHub Actions` | 1438 | 1484 | 402 | 52 | 1840 | 1536 |

Actor-pill captions (N1, N2) are centred under their pill, cap height starting at
`y = 362`.

### 8.3 Package headers

**N3 and N4** (stacked, left-aligned at the box's 24 px inset):

| Line | Top y | Height |
|---|---:|---:|
| Node title | 468 | 30 |
| Node path (mono) | 498 | 20 |
| Sub-caption | 518 | 19 |

**N5** — title and path stacked on the left starting at `y = 928` (title 30, path
20); the sub-caption is **right-aligned on the title's baseline**, ending at
`x = 1816`, to save vertical space.

**N6** — title and path on **one line** at `y = 1188` (title Inter 600 26 px, path
mono 16 px baseline-aligned immediately to its right with a 12 px gap); the
sub-caption is right-aligned on the same baseline, ending at `x = 1816`.

### 8.4 Chip grids

**N3 (The Game)** — 2 columns × 3 rows. Chip `358 × 68`, gaps 16.

- x: `184`, `558`
- y: `553`, `637`, `721` (bottom edge of the last row = 789)

**N4 (The Editor)** — identical grid, shifted right by 900.

- x: `1084`, `1458`
- y: `553`, `637`, `721`

**N5 (The Engine)** — 6 chips in one row. Chip `258 × 62`, gap 16, `y = 990`.

- x: `184`, `458`, `732`, `1006`, `1280`, `1554` (last ends at 1812; absorb the
  remaining 4 px at the right)

**N6 (The Data)** — 6 chips in one row, **below** the gate bar. Chip `258 × 84`,
gap 16, `y = 1290` (bottom 1374).

- x: same six values as N5

---

## 9. Node inventory — exact copy

**Set every string below verbatim.** Do not paraphrase, do not "improve" the
wording, do not translate. The `path` line is always set in mono.

### Band A — Authors

| ID | Label (Inter 500, 18px, on `authors.chip` fill, white text) |
|---|---|
| **N1** | `Designer` |
| **N2** | `AI Agent (Claude Code)` |

Each pill carries a **caption below it**, centred, chip caption style:

- N1 caption: `Never opens a JSON file by hand.`
- N2 caption: `Edits files directly — but only schema-valid writes.`

### Band B — Applications

#### N3 — The Game

- **Title:** `The Game`
- **Path:** `game/`
- **Sub-caption** (chip caption style, directly under the path):
  `The thing players run. One entry point: py game/main.py`

Six chips:

| Chip label | Chip caption |
|---|---|
| `main.py` | `Window, frame loop, input routing. The only entry point.` |
| `core` | `The round machine, payday, XP and progression.` |
| `map` | `Tiles, zones, tile unlocking, pathfinding.` |
| `buildings` | `Twelve building types and how they upgrade.` |
| `enemies` | `Five enemy types, wave spawning, combat resolution.` |
| `ui` | `HUD, the build panel, menus and effects.` |

#### N4 — The Editor

- **Title:** `The Editor`
- **Path:** `editor/`
- **Sub-caption:** `The designer's only interface. Run from source: py editor/main.py`

Six chips:

| Chip label | Chip caption |
|---|---|
| `selector` | `The tree. Exactly one node is selected — that drives everything.` |
| `viewport` | `Draws through the engine. Map editing, entity and screen preview.` |
| `balancing` | `A form generated from the schema. Invalid input is impossible.` |
| `asset import` | `Slice a spritesheet into animation rows and bind it to a slot.` |
| `run controls` | `Play, Build, Playbuild — always separate processes.` |
| `agent dispatch` | `"Summon a Drunken Robot" — hands a task brief to an AI agent.` |

### Band C — The Engine

- **Title:** `The Engine`
- **Path:** `engine/`
- **Sub-caption:** `Shared foundation. Carries exactly this game's workload — and knows nothing about the game itself.`

Six chips (single row, left to right in this order):

| Chip label | Chip caption |
|---|---|
| `coords` | `The only place isometric maths happens.` |
| `core` | `Game objects, components, the scene.` |
| `physics` | `Movement, spatial queries, tile occupancy.` |
| `assets` | `Slots, spritesheets, animation timing.` |
| `render` | `One drawing pipeline. Sort, then blit.` |
| `vfx` | `Particles, sparks, decals.` |

### Band D — The Data

- **Title:** `The Data`
- **Path:** `data/`
- **Sub-caption:** `The single source of truth. Every value in the game lives here — none of it is hard-coded.`

**N6g — the schema gate bar** spans the full inner width, above the chips.
Style it as the "gate" shape (§4.1): a bar in `data.chip` at 22 % opacity with a
`data.stroke` 2 px outline and a small **notch** cut into its left edge (a 16 px
inward triangle at mid-height), so it visually reads as a checkpoint.

- **Bar label** (Inter 600, 18 px, `ink`, left aligned with 20 px inset):
  `data/schemas/ — 22 JSON Schemas`
- **Bar sub-label** (Inter 400, 14 px, `ink-70`, right aligned, 20 px inset):
  `Every write is validated before it touches the disk.`

Six chips below the bar:

| Chip label | Chip caption |
|---|---|
| `balancing/` | `Six domains: buildings, enemies, map, ui, core, vfx.` |
| `maps/` | `Terrain grids, decoration, the hole's position.` |
| `sprites/` | `The asset manifest plus every imported spritesheet.` |
| `ui/` | `Screen layouts, fonts, palette, all on-screen text.` |
| `slots.json` | `The registry of every asset slot that exists.` |
| `tutorial/ · video/` | `The guided-tutorial script and the cutscene registry.` |

### Band E — Verification

Four tool chips, evenly spaced. Style: `verification` fill, 1.5 px
`verification.stroke`, label Inter 500 16 px, caption 13 px.

| Chip label | Chip caption |
|---|---|
| `tools/smoke.py` | `Validates every data file, then boots the game headless.` |
| `tools/testgate.py` | `The whole test suite. The bar is zero failures.` |
| `tools/build.py` | `Packages the Windows executable.` |
| `GitHub Actions` | `Runs the gate on every pull request.` |

---

## 10. Edge inventory — exact copy

Nine edges. **E1–E8 are required.** E9 is required and is the visually special one.

| ID | From → To | Line style (§4.3) | Colour | Label (plated) |
|---|---|---|---|---|
| **E1** | N1 Designer → N4 The Editor (top edge) | solid 2 px | `authors.stroke` | `authors through` |
| **E2** | N4 The Editor (top edge, right side) → N2 AI Agent | solid 2 px | `editor.stroke` | `dispatches a task` |
| **E3** | N2 AI Agent → N6 The Data (schema gate bar, right end) | dotted 2 px | `authors.stroke` | `writes — schema-valid only` |
| **E4** | N3 The Game (bottom edge) → N5 The Engine (top edge) | **heavy solid 3 px** | `game.stroke` | `built on` |
| **E5** | N4 The Editor (bottom edge) → N5 The Engine (top edge) | **heavy solid 3 px** | `editor.stroke` | `built on` |
| **E6** | N5 The Engine (bottom edge, centre) → N6 The Data (schema gate bar, centre) | solid 2 px | `engine.stroke` | `reads + writes, validated` |
| **E7** | N3 The Game (left edge) → N6 The Data (left edge) | solid 2 px | `game.stroke` | `reads at boot — refuses to start on bad data` |
| **E8** | N4 The Editor (right edge) → N6 The Data (right edge) | dotted 2 px | `editor.stroke` | `reads and writes` |
| **E9** | N4 The Editor (bottom-left area) ⟶ N3 The Game (bottom-right area) | **dashed 2.5 px, `10 6`**, open chevron head | `editor.stroke` | `Play ▶ launches it as a separate process` |

### Routing notes — exact tracks

| Edge | Path (right-angle turns, 12 px corner radius) |
|---|---|
| **E1** | `(500, 350)` ↓ to `(500, 410)` → right to `(1200, 410)` ↓ into N4's top edge at `(1200, 444)` |
| **E2** | up from N4's top edge at `(1500, 444)` ↑ to `(1500, 410)` → right to `(1560, 410)` ↑ into N2's bottom edge at `(1560, 350)` |
| **E3** | from N2's bottom edge at `(1420, 350)` ↓ to `(1420, 392)` → right to `(1876, 392)` ↓ all the way to `(1876, 1152)` → left to `(1700, 1152)` ↓ into the **gate bar's top edge** at `(1700, 1230)` |
| **E4** | `(550, 816)` ↓ `(550, 904)` — perfectly vertical, heavy |
| **E5** | `(1450, 816)` ↓ `(1450, 904)` — perfectly vertical, heavy |
| **E6** | `(1000, 1076)` ↓ into the gate bar's top edge at `(1000, 1230)` |
| **E7** | from N3's left edge at `(160, 740)` → left to `(124, 740)` ↓ to `(124, 1300)` → right into N6's left edge at `(160, 1300)` |
| **E8** | from N4's right edge at `(1840, 740)` → right to `(1852, 740)` ↓ to `(1852, 1300)` → left into N6's right edge at `(1840, 1300)` |
| **E9** | a smooth symmetric arc from N4's bottom edge at `(1160, 816)`, low point `(1000, 858)`, rising into N3's bottom edge at `(840, 816)` |

Additional notes:

- **E1 and E2 must stay at least 48 px apart horizontally** where they run in
  band A's gap, so they read as two separate journeys rather than one loop.
- **E4 / E5 are the visual spine** — two short, thick, perfectly vertical strokes.
  Their labels sit to the outside: E4's to the left of its line, E5's to the right.
- **E3 does not break at band boundaries.** It runs continuously down the outer
  track at `x = 1876`.
- ⚠️ **Exactly one crossing exists in the whole diagram:** E3's horizontal segment
  at `y = 1152` crosses E8's vertical at `x = 1852`. Draw a **10 px arc hop** on
  **E3** at that point. Any *additional* crossing means something has been routed
  wrong — re-route rather than accept it.
- **E9 is the only curve.** It sits in the 40 px gap between bands B and C, dipping
  18 px below band B's bottom edge. It spans `x = 840 → 1160`, so it has clear air
  from the E4/E5 spines at `x = 550` and `x = 1450`. Its label is centred on the
  arc's low point, on a `paper` plate.

---

## 11. The forbidden-link barrier

This is the diagram's signature element. Give it real weight.

**Position.** In the 120 px channel between N3 (right edge 940) and N4 (left edge
1060), centred at `x = 1000`, spanning `y = 480 → 780`.

**Construction:**

1. A vertical dashed line, 3 px, dash `8 8`, colour `signal` `#D93025`, from
   `(1000, 480)` to `(1000, 780)`.
2. Centred on it at `y = 630`, a **circular badge**: 56 px diameter, fill `paper`,
   3 px `signal` stroke, containing a **⊘** glyph (a circle with a 45° slash) in
   `signal`, 2.5 px stroke, 28 px diameter.
3. A two-line label **centred on the channel**, directly below the badge, starting
   at `y = 674`, max width 116 px (it must not overrun into either package box):
   - Line 1 — Inter 700, 15 px, `signal`, centred, uppercase, tracking `+0.06em`:
     `NEVER IMPORT EACH OTHER`
   - Line 2 — Inter 400, 13 px, `ink-70`, centred:
     `A hard rule. It is what lets the editor preview truthfully.`

   If the channel proves too narrow to set those two lines legibly, move **only the
   label** (not the line or the badge) into the band-B gutter directly below the
   channel, at `y = 800`, and centre it on `x = 1000`. The line and badge stay put.

**A deliberate visual rhyme, worth preserving.** The barrier (`x = 1000`,
y 480–780), the low point of E9's Play arc (`x = 1000`, `y = 858`) and E6's
engine→data line (`x = 1000`, y 1076–1230) all sit on the same central vertical
axis, separated by clear gaps. Read top to bottom this says: *they may not import
each other — but one can still launch the other — and everything lands on the same
validated data.* Keep all three on `x = 1000`; the colour and line-style differences
are what keep them from reading as one continuous line.

⚠️ Do **not** put arrowheads on the barrier. It is not a connection; it is the
absence of one.

⚠️ Do **not** use `signal` red anywhere else in the artwork — not for emphasis, not
for a heading, not for a legend accent. Its whole power is that it appears once.

---

## 12. Callout cards

Three cards. They are **annotations, not system parts** — hence the neutral `paper`
fill and 1 px `hairline` border (§4.1).

**They live in the legend rail**, stacked below the four legend sections, so the
diagram column stays uncluttered. Each connects to its target with a hairline
dotted leader (1 px, dash `2 4`, `ink-45`) that leaves the card's **left edge**,
crosses the rail divider, and ends in a 4 px filled `ink-45` dot on its target.

Card size `320 × 132`, at `x = 1980`. Padding 18 px. Title + 2–3 body lines.

| ID | y | Leader ends on | Title | Body |
|---|---:|---|---|---|
| **C1** | 1040 | the `render` chip in N5, at `(1409, 1021)` | `One render path` | `The editor's viewport and the game's window draw through the same pipeline. What a designer sees is what ships.` |
| **C2** | 1200 | the gate bar's right end, at `(1816, 1252)` | `Nothing gets in unvalidated` | `Every write to data/ goes through one schema-checking writer — whether a designer, the editor or an AI agent made it.` |
| **C3** | 1360 | the `tools/testgate.py` chip, at `(988, 1510)` | `The bar is zero` | `There is no tolerated-failure baseline. The suite is green, or the work is not done.` |

Leaders run orthogonally (out left, then turn) with 12 px corners, exactly like the
edges — but at hairline weight and with **no arrowhead**, so they can never be
mistaken for a relationship.

If space runs short, **C1 is the one to protect** — it explains the single most
important consequence of the architecture. C3 may be dropped.

---

## 13. The legend rail

A single column at `x = 1980 → 2300`, top-aligned to `y = 260`, separated from the
diagram column by the 1 px `hairline` rule at `x = 1940` (`y = 260 → 1560`).

The rail holds **four legend sections then the three callout cards** from §12:

| Block | y (top) | Approx. height |
|---|---:|---:|
| `LAYERS` | 260 | 190 |
| `RELATIONSHIPS` | 470 | 180 |
| `SHAPES` | 670 | 150 |
| `THREE RULES` | 840 | 180 |
| Callout **C1** | 1040 | 132 |
| Callout **C2** | 1200 | 132 |
| Callout **C3** | 1360 | 132 |

(The heights are targets, not constraints — set the type properly and let the
blocks land where they land, keeping 20 px between sections and 28 px between
cards. Nothing may extend below `y = 1560`.)

Four sections, in this order, each preceded by its heading and 20 px of space:

### 13.1 `LAYERS`

Six rows. Each row: a `20 × 20` rounded (4 px) swatch in that layer's **chip**
colour, 12 px gap, then the label in legend-item style.

```
▪ Authors        people and agents
▪ The Game       game/
▪ The Editor     editor/
▪ The Engine     engine/
▪ The Data       data/
▪ Verification   tools/ and CI
```

(The second column is `ink-45`, 12 px, and right-aligned within the rail.)

### 13.2 `RELATIONSHIPS`

Five rows. Each shows a 56 px sample of the line at actual spec, then the label.

```
━━━▶   built on            (heavy solid)
──▶    reads / uses        (solid)
┈┈▶    writes              (dotted)
╌╌❯    launches a process  (dashed, open head)
╌⊘╌    must never connect  (signal red, no head)
```

### 13.3 `SHAPES`

Four rows, each a small drawn sample at ~40 % scale.

```
▢  package     a top-level part of the system
▭  chip        a named part inside a package
◗  gate        everything must pass through it
◍  actor       a person or an agent, not code
```

### 13.4 `THREE RULES`

A short numbered list, legend-item style, no swatches. Set the numerals in
Inter 700 `ink-45`.

```
1   Data is the only source of truth.
    No gameplay value is written in code.

2   The engine is shared; the applications are peers.
    Neither application may import the other.

3   Humans author through the editor.
    Agents author through the same validation gate.
```

---

## 14. Title block and footer

### 14.1 Title block — `x 100 → 1900`, `y 100 → 220`

Three lines, left aligned at `x = 100`:

| Line | Style | Copy |
|---|---|---|
| 1 | Wordmark, Pixel Emulator 56 px, `ink` | `HOW TO BE HUMAN` |
| 2 | Inter 700, 34 px, `ink` | `System Map` |
| 3 | Inter 400, 20 px, `ink-70` | `An isometric tower-defence game, its in-house editor, the engine they share, and the validated data both read.` |

Right-aligned in the same block, at `x = 1900`, baseline-aligned to line 2, set in
JetBrains Mono 400, 14 px, `ink-45`, right aligned, two lines:

```
Python 3.11 · pygame-ce · PySide6
Four layers · ~33k lines · 79 data files
```

### 14.2 Footer — full width `x 100 → 2300`

A 1 px `hairline` rule at `y = 1592`, then one line of footnote-style text with its
cap height starting at `y = 1608`, left aligned at `x = 100`:

```
Structural overview only — this diagram does not describe gameplay. Full detail: docs/TDD.md · Requirements: SPEC.md
```

Right-aligned on the same baseline, a version stamp the design agent should fill in:

```
v1 · <date>
```

---

## 15. Rules, do's and don'ts

### Do

- **Align everything to the 8 px unit.** If a value in this brief is not a multiple
  of 8, that is deliberate (an optical adjustment) — keep it.
- **Keep the four package boxes visually equal in weight.** The Game and the Editor
  are *peers*. If one looks more important, the diagram lies.
- **Let the Data band feel like ground.** It is the widest, warmest and lowest
  element. That is the point.
- **Plate every edge label.** (§6.2)
- **Keep all connectors orthogonal** except E9.
- **Set the mono path lines** (`game/`, `editor/`, `engine/`, `data/`) — they are
  what makes the diagram cross-referenceable against the repository.

### Don't

- ❌ **No drop shadows, glows, gradients, bevels, or 3-D.** Flat, printed-page
  aesthetic throughout.
- ❌ **Do not make the diagram isometric.** The *game* is isometric; the diagram is
  a flat orthogonal stack. Making the boxes isometric would be a pun that costs
  legibility.
- ❌ **Do not add a sixth hue**, and do not use `signal` red for anything but the
  barrier.
- ❌ **Do not add icons inside the chips.** Text only. Icons for abstractions like
  "coords" or "balancing" invariably become decorative noise.
- ❌ **Do not add arrows that point upward** (E9's arc is the one exception, and it
  is deliberately styled as a different *kind* of relationship).
- ❌ **Do not invent new nodes, labels or connections.** If something in this brief
  seems to be missing, flag it rather than filling the gap — the structure here is
  load-bearing and the wording has been checked against the codebase.
- ❌ **Do not shorten the chip captions** to fit. If a caption does not fit, widen
  the chip or reduce the caption's size to 13 px — but keep the words.
- ❌ **Do not use the Pixel Emulator font anywhere except the wordmark.**

---

## 16. Accessibility requirements

These are pass/fail, not preferences.

1. **All text meets WCAG AA on its own background.** This is automatic if you obey
   §6.2's rule that text is only ever `ink` / `ink-70` / `ink-45` (or the mono path
   line, which sits on a pale fill and has been checked).
2. **Colour is never the only signal.** Every node carries a text label and its
   package path; every relationship type has a distinct *line style*, not just a
   distinct colour. A viewer with full colour-blindness must still be able to read
   the whole diagram.
3. **The barrier is legible without red** — the ⊘ badge plus the words
   `NEVER IMPORT EACH OTHER` carry the meaning on their own.
4. **Minimum type size is 12 px at 1×.** Nothing smaller, anywhere, including the
   footer.
5. **Minimum stroke weight is 1 px at 1×.** No hairlines below that.
6. **The SVG export must have live text and meaningful layer/element IDs** (§3), so
   the diagram is machine-readable and screen-reader-inspectable.
7. **The diagram must survive being printed A3 greyscale.** Test this: convert to
   greyscale and confirm the four bands are still distinguishable by their fill
   *values* — if two bands render at the same grey, lighten one band's fill opacity
   by 8 %.

---

## 17. Acceptance checklist

Tick every line before delivering.

**Structure**
- [ ] Five bands present, in order: Authors, Applications, Engine, Data, Verification.
- [ ] Every node from §9 exists, with its exact label, path and caption text.
- [ ] Every edge E1–E9 exists, with the correct style, direction and label.
- [ ] The ⊘ barrier sits between the Game and the Editor with both label lines.
- [ ] Callouts C1 and C2 present (C3 optional).
- [ ] Legend rail has all four sections.
- [ ] Title block and footer present, with the version stamp filled in.

**Craft**
- [ ] Exactly one line crossing in the whole diagram (E3 over E8), drawn as a hop.
- [ ] Every edge label sits on a `paper` plate.
- [ ] All connectors orthogonal with 12 px rounded corners, except E9's arc.
- [ ] No shadows, gradients, glows or 3-D anywhere.
- [ ] Everything on the 8 px grid.
- [ ] The Game and the Editor boxes are identical in size and stroke weight.

**Colour & type**
- [ ] Exactly six layer hues plus the neutrals; no seventh colour.
- [ ] `#D93025` appears **only** on the barrier.
- [ ] All text is `ink` / `ink-70` / `ink-45`, except mono path lines.
- [ ] Pixel Emulator used once, in the wordmark, at ≥ 44 px.
- [ ] Nothing below 12 px.

**Accessibility**
- [ ] Greyscale print test passes — four bands still distinguishable.
- [ ] Colour-blind test passes — every relationship readable by line style alone.
- [ ] SVG has live text and the layer IDs from §3.

**Delivery**
- [ ] All six export files produced (§3), light and dark.
- [ ] Source file layers named per §3.

---

## 18. Appendix — optional companion diagrams

**Only start these once the hero diagram is signed off.** They reuse the same
palette, type scale and line language exactly — they are the same family, not a
new one.

### Companion 1 — "One frame" (a horizontal timeline)

A single left-to-right band, `2400 × 500`, showing what happens in one frame of the
running game. Five stages as equal-width segments, using the **Game** teal:

| Stage | Label | Caption |
|---|---|---|
| 1 | `Input` | `Mouse and keyboard become camera moves and clicks.` |
| 2 | `Simulate` | `Spawn the wave, move everything, resolve combat, settle the round.` |
| 3 | `Submit` | `Every visible thing is described as a draw request.` |
| 4 | `Sort & draw` | `Requests are depth-sorted into five layers, then blitted.` |
| 5 | `Flip` | `The finished frame goes to the screen.` |

Below the band, a thin annotation rail naming the five draw layers in order —
`ground · terrain · entities · deco · overlay` — plus a separate `HUD` block drawn
slightly detached, with the note `drawn last, in screen space, never depth-sorted`.

### Companion 2 — "The round" (a state machine)

A cycle diagram, `1600 × 1200`, five states in a ring using the **Game** teal, with
two conditional side-states in the **Editor** violet to distinguish "sometimes"
from "always":

```
BUILDING ──(End Turn)──▶ ENEMY ──(wave cleared / hole breached)──▶ ROUND END
    ▲                                                                 │
    │                                        ┌────────────────────────┤
    │                                        ▼                        ▼
    │                              BOSS CUTSCENE (sometimes)   LEVEL UP (sometimes)
    │                                        └────────────┬───────────┘
    └──────────────────────────── INCOME ◀────────────────┘
```

Node captions:

| State | Caption |
|---|---|
| `BUILDING` | `The player places, upgrades and unlocks. No timer.` |
| `ENEMY` | `The wave walks in. Playable at 1×, 1.5×, 2× or paused.` |
| `ROUND END` | `A short beat before settlement.` |
| `BOSS CUTSCENE` | `Every few rounds: a story choice with a lasting bonus.` |
| `LEVEL UP` | `When XP crosses the threshold: pick one of three rewards.` |
| `INCOME` | `Payday. Love arrives and buildings are rebuilt.` |

Annotate the boss/level-up branch with the note:
`If both are pending, the boss cutscene runs first.`

---

*End of brief. Questions or ambiguities: flag them rather than resolving them —
the structure described here is load-bearing and has been checked against the
codebase.*
