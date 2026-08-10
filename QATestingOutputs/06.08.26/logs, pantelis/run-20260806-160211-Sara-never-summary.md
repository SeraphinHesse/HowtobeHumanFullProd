# Debug run summary — run-20260806-160211-Sara-never

Player: Sara (never)

## Outcome

- outcome: **game_over**
- rounds recorded: **15** (round 0 -> 14)
- love: 15 -> **48**
- lives left: **1**
- village level: **5** (xp 93)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 489 |
| income (potential, nothing lost) | 592 |
| **income lost to buildings dying** | **103** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 30 |
| upkeep potential | 35 |
| upkeep unpaid because buildings died | 5 |
| net (actual) | 459 |
| net (potential) | 557 |
| damage dealt (building-credited) | 18179 |
| damage dealt (lightning, no shooter) | 0 |
| damage taken by buildings (HP) | 7137 |
| lives lost | 2 |
| enemies spawned | 237 |
| kills | 209 |
| leaks (base breaches) | 2 |
| kidnaps | 23 |
| buildings placed | 17 |
| love spent on buildings | 295 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 0 | 5 | 10 | 5 | 0 | 1 |
| 1 | 10 | 10 | 0 | 0 | 0 |
| 2 | 15 | 15 | 0 | 0 | 0 |
| 3 | 15 | 15 | 0 | 0 | 0 |
| 4 | 20 | 20 | 0 | 0 | 1 |
| 5 | 20 | 20 | 0 | 0 | 0 |
| 6 | 20 | 20 | 0 | 0 | 0 |
| 7 | 35 | 35 | 0 | 0 | 0 |
| 8 | 47 | 47 | 0 | 0 | 1 |
| 9 | 60 | 60 | 0 | 0 | 2 |
| 10 | 9 | 62 | 53 | 5 | 15 |
| 11 | 59 | 68 | 9 | 0 | 3 |
| 12 | 52 | 70 | 18 | 0 | 3 |
| 13 | 70 | 70 | 0 | 0 | 2 |
| 14 | 52 | 70 | 18 | 0 | 6 |

Net effect of losing buildings: **98 love** (103 income lost, 5 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 0 | 15 | 5 | 0 | 5 | 20 |
| 1 | 10 | 10 | 0 | 10 | 20 |
| 2 | 10 | 15 | 0 | 15 | 25 |
| 3 | 8 | 15 | 0 | 15 | 23 |
| 4 | 6 | 20 | 0 | 20 | 26 |
| 5 | 6 | 20 | 0 | 20 | 26 |
| 6 | 6 | 20 | 0 | 20 | 26 |
| 7 | 1 | 35 | 0 | 35 | 36 |
| 8 | 0 | 47 | 0 | 47 | 47 |
| 9 | 7 | 60 | 0 | 60 | 67 |
| 10 | 2 | 9 | 0 | 9 | 11 |
| 11 | 0 | 59 | 5 | 54 | 54 |
| 12 | 0 | 52 | 7 | 45 | 45 |
| 13 | 5 | 70 | 9 | 61 | 66 |
| 14 | 5 | 52 | 9 | 43 | 48 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 15551 | 85.5% |
| aoe_defence | 2628 | 14.5% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| defence | 4092 | 57.3% |
| economic | 2213 | 31.0% |
| blocker | 512 | 7.2% |
| aoe_defence | 320 | 4.5% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 225 |
| research | 70 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep**

| building type | love | share |
|---|---:|---:|
| aoe_defence | 24 | 80.0% |
| defence | 6 | 20.0% |

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 1 | 1 | 2 | 21 | 17 | 2542 |
| 12 | 1 | 1 | 1 | 27 | 19 | 2093 |
