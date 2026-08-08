# Debug run summary — run-20260806-163110-Sara-a_bit

Player: Sara (a_bit)

## Outcome

- outcome: **game_over**
- rounds recorded: **17** (round 1 -> 17)
- love: 0 -> **35**
- lives left: **1**
- village level: **5** (xp 116)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 756 |
| income (potential, nothing lost) | 886 |
| **income lost to buildings dying** | **130** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 57 |
| upkeep potential | 73 |
| upkeep unpaid because buildings died | 16 |
| net (actual) | 699 |
| net (potential) | 813 |
| damage dealt (building-credited) | 33917 |
| damage dealt (lightning, no shooter) | 144 |
| damage taken by buildings (HP) | 9584 |
| lives lost | 2 |
| enemies spawned | 388 |
| kills | 349 |
| leaks (base breaches) | 2 |
| kidnaps | 26 |
| buildings placed | 22 |
| love spent on buildings | 287 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 1 | 14 | 14 | 0 | 0 | 0 |
| 2 | 19 | 19 | 0 | 0 | 0 |
| 3 | 23 | 23 | 0 | 0 | 0 |
| 4 | 23 | 23 | 0 | 0 | 0 |
| 5 | 31 | 31 | 0 | 0 | 0 |
| 6 | 36 | 36 | 0 | 0 | 0 |
| 7 | 47 | 47 | 0 | 0 | 0 |
| 8 | 33 | 47 | 14 | 0 | 1 |
| 9 | 47 | 47 | 0 | 0 | 0 |
| 10 | 27 | 59 | 32 | 0 | 8 |
| 11 | 67 | 67 | 0 | 3 | 2 |
| 12 | 71 | 71 | 0 | 3 | 2 |
| 13 | 59 | 73 | 14 | 5 | 4 |
| 14 | 63 | 77 | 14 | 5 | 5 |
| 15 | 68 | 81 | 13 | 0 | 5 |
| 16 | 81 | 84 | 3 | 0 | 5 |
| 17 | 47 | 87 | 40 | 0 | 8 |

Net effect of losing buildings: **114 love** (130 income lost, 16 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 14 | 0 | 14 | 14 |
| 2 | 4 | 19 | 0 | 19 | 23 |
| 3 | 1 | 23 | 0 | 23 | 24 |
| 4 | 7 | 23 | 0 | 23 | 30 |
| 5 | 0 | 31 | 0 | 31 | 31 |
| 6 | 0 | 36 | 0 | 36 | 36 |
| 7 | 0 | 47 | 0 | 47 | 47 |
| 8 | 1 | 33 | 3 | 30 | 31 |
| 9 | 1 | 47 | 3 | 44 | 45 |
| 10 | 0 | 27 | 3 | 24 | 24 |
| 11 | 4 | 67 | 0 | 67 | 71 |
| 12 | 6 | 71 | 5 | 66 | 72 |
| 13 | 2 | 59 | 5 | 54 | 56 |
| 14 | 9 | 63 | 5 | 58 | 67 |
| 15 | 2 | 68 | 10 | 58 | 60 |
| 16 | 0 | 81 | 10 | 71 | 71 |
| 17 | 1 | 47 | 13 | 34 | 35 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 25427 | 75.0% |
| aoe_defence | 8490 | 25.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| defence | 5585 | 58.3% |
| economic | 2677 | 27.9% |
| aoe_defence | 1258 | 13.1% |
| meditator | 64 | 0.7% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 287 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep**

| building type | love | share |
|---|---:|---:|
| aoe_defence | 54 | 94.7% |
| storm_priest | 3 | 5.3% |

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 1 | 1 | 2 | 21 | 15 | 1586 |
| 17 | 1 | 1 | 1 | 57 | 38 | 4607 |
