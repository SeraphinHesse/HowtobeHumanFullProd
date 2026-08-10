# Debug run summary — run-20260806-152824-CanPork-a_lot

Player: Can Pork (a_lot)

## Outcome

- outcome: **game_over**
- rounds recorded: **9** (round 1 -> 9)
- love: 5 -> **23**
- lives left: **1**
- village level: **2** (xp 42)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 173 |
| income (potential, nothing lost) | 265 |
| **income lost to buildings dying** | **92** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 0 |
| upkeep potential | 0 |
| upkeep unpaid because buildings died | 0 |
| net (actual) | 173 |
| net (potential) | 265 |
| damage dealt (building-credited) | 5166 |
| damage dealt (lightning, no shooter) | 0 |
| damage taken by buildings (HP) | 1610 |
| lives lost | 2 |
| enemies spawned | 96 |
| kills | 80 |
| leaks (base breaches) | 2 |
| kidnaps | 8 |
| buildings placed | 7 |
| love spent on buildings | 70 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 1 | 10 | 10 | 0 | 0 | 0 |
| 2 | 15 | 15 | 0 | 0 | 0 |
| 3 | 20 | 20 | 0 | 0 | 0 |
| 4 | 28 | 33 | 5 | 0 | 1 |
| 5 | 33 | 33 | 0 | 0 | 0 |
| 6 | 19 | 33 | 14 | 0 | 1 |
| 7 | 16 | 35 | 19 | 0 | 2 |
| 8 | 16 | 43 | 27 | 0 | 2 |
| 9 | 16 | 43 | 27 | 0 | 2 |

Net effect of losing buildings: **92 love** (92 income lost, 0 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 1 | 5 | 10 | 0 | 10 | 15 |
| 2 | 5 | 15 | 0 | 15 | 20 |
| 3 | 3 | 20 | 0 | 20 | 23 |
| 4 | 3 | 28 | 0 | 28 | 31 |
| 5 | 4 | 33 | 0 | 33 | 37 |
| 6 | 6 | 19 | 0 | 19 | 25 |
| 7 | 0 | 16 | 0 | 16 | 16 |
| 8 | 1 | 16 | 0 | 16 | 17 |
| 9 | 7 | 16 | 0 | 16 | 23 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 5166 | 100.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| economic | 1520 | 94.4% |
| defence | 90 | 5.6% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 70 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep** — none recorded.

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 8 | 1 | 1 | 2 | 19 | 12 | 882 |
| 9 | 1 | 1 | 1 | 22 | 17 | 1295 |
