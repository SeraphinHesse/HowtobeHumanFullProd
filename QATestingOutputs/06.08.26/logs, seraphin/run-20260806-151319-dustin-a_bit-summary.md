# Debug run summary — run-20260806-151319-dustin-a_bit

Player: dustin (a_bit)

## Outcome

- outcome: **game_over**
- rounds recorded: **18** (round 1 -> 18)
- love: 5 -> **77**
- lives left: **1**
- village level: **6** (xp 83)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 936 |
| income (potential, nothing lost) | 1032 |
| **income lost to buildings dying** | **96** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 79 |
| upkeep potential | 127 |
| upkeep unpaid because buildings died | 48 |
| net (actual) | 857 |
| net (potential) | 905 |
| damage dealt (building-credited) | 45969 |
| damage dealt (lightning, no shooter) | 0 |
| damage taken by buildings (HP) | 9523 |
| lives lost | 2 |
| enemies spawned | 451 |
| kills | 436 |
| leaks (base breaches) | 2 |
| kidnaps | 24 |
| buildings placed | 21 |
| love spent on buildings | 334 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 1 | 10 | 10 | 0 | 0 | 0 |
| 2 | 19 | 19 | 0 | 0 | 0 |
| 3 | 19 | 19 | 0 | 0 | 0 |
| 4 | 19 | 19 | 0 | 0 | 0 |
| 5 | 24 | 24 | 0 | 0 | 1 |
| 6 | 36 | 36 | 0 | 0 | 0 |
| 7 | 46 | 46 | 0 | 0 | 1 |
| 8 | 46 | 46 | 0 | 3 | 2 |
| 9 | 56 | 56 | 0 | 3 | 1 |
| 10 | 35 | 74 | 39 | 5 | 7 |
| 11 | 74 | 74 | 0 | 5 | 2 |
| 12 | 74 | 74 | 0 | 0 | 1 |
| 13 | 76 | 76 | 0 | 0 | 1 |
| 14 | 59 | 85 | 26 | 4 | 4 |
| 15 | 89 | 89 | 0 | 11 | 4 |
| 16 | 78 | 91 | 13 | 2 | 3 |
| 17 | 78 | 96 | 18 | 6 | 4 |
| 18 | 98 | 98 | 0 | 9 | 3 |

Net effect of losing buildings: **48 love** (96 income lost, 48 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 1 | 5 | 10 | 0 | 10 | 15 |
| 2 | 0 | 19 | 0 | 19 | 19 |
| 3 | 2 | 19 | 0 | 19 | 21 |
| 4 | 4 | 19 | 0 | 19 | 23 |
| 5 | 3 | 24 | 0 | 24 | 27 |
| 6 | 2 | 36 | 0 | 36 | 38 |
| 7 | 3 | 46 | 0 | 46 | 49 |
| 8 | 3 | 46 | 0 | 46 | 49 |
| 9 | 3 | 56 | 0 | 56 | 59 |
| 10 | 9 | 35 | 0 | 35 | 44 |
| 11 | 9 | 74 | 0 | 74 | 83 |
| 12 | 3 | 74 | 7 | 67 | 70 |
| 13 | 0 | 76 | 7 | 69 | 69 |
| 14 | 4 | 59 | 7 | 52 | 56 |
| 15 | 15 | 89 | 2 | 87 | 102 |
| 16 | 13 | 78 | 16 | 62 | 75 |
| 17 | 3 | 78 | 19 | 59 | 62 |
| 18 | 0 | 98 | 21 | 77 | 77 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 36254 | 78.9% |
| aoe_defence | 9715 | 21.1% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| defence | 5397 | 56.7% |
| economic | 2694 | 28.3% |
| aoe_defence | 1392 | 14.6% |
| wall_builder | 40 | 0.4% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 294 |
| research | 40 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep**

| building type | love | share |
|---|---:|---:|
| aoe_defence | 52 | 65.8% |
| defence | 20 | 25.3% |
| wall_builder | 6 | 7.6% |
| boost_damage | 1 | 1.3% |

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 1 | 1 | 2 | 21 | 16 | 1560 |
| 14 | 1 | 1 | 1 | 38 | 34 | 4151 |
