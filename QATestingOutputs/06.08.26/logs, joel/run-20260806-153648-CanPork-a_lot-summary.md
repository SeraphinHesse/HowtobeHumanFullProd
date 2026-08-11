# Debug run summary — run-20260806-153648-CanPork-a_lot

Player: Can Pork (a_lot)

## Outcome

- outcome: **game_over**
- rounds recorded: **9** (round 1 -> 9)
- love: 0 -> **43**
- lives left: **1**
- village level: **2** (xp 44)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 224 |
| income (potential, nothing lost) | 297 |
| **income lost to buildings dying** | **73** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 0 |
| upkeep potential | 0 |
| upkeep unpaid because buildings died | 0 |
| net (actual) | 224 |
| net (potential) | 297 |
| damage dealt (building-credited) | 5565 |
| damage dealt (lightning, no shooter) | 0 |
| damage taken by buildings (HP) | 2898 |
| lives lost | 2 |
| enemies spawned | 96 |
| kills | 76 |
| leaks (base breaches) | 2 |
| kidnaps | 11 |
| buildings placed | 9 |
| love spent on buildings | 105 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 1 | 14 | 14 | 0 | 0 | 0 |
| 2 | 19 | 19 | 0 | 0 | 0 |
| 3 | 23 | 23 | 0 | 0 | 0 |
| 4 | 23 | 23 | 0 | 0 | 0 |
| 5 | 28 | 33 | 5 | 0 | 1 |
| 6 | 32 | 41 | 9 | 0 | 1 |
| 7 | 30 | 48 | 18 | 0 | 2 |
| 8 | 16 | 48 | 32 | 0 | 4 |
| 9 | 39 | 48 | 9 | 0 | 3 |

Net effect of losing buildings: **73 love** (73 income lost, 0 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 14 | 0 | 14 | 14 |
| 2 | 4 | 19 | 0 | 19 | 23 |
| 3 | 1 | 23 | 0 | 23 | 24 |
| 4 | 4 | 23 | 0 | 23 | 27 |
| 5 | 0 | 28 | 0 | 28 | 28 |
| 6 | 3 | 32 | 0 | 32 | 35 |
| 7 | 4 | 30 | 0 | 30 | 34 |
| 8 | 9 | 16 | 0 | 16 | 25 |
| 9 | 4 | 39 | 0 | 39 | 43 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 5565 | 100.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| economic | 1776 | 61.3% |
| blocker | 1002 | 34.6% |
| defence | 120 | 4.1% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 105 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep** — none recorded.

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 7 | 1 | 1 | 2 | 16 | 11 | 791 |
| 8 | 1 | 1 | 1 | 19 | 9 | 756 |
