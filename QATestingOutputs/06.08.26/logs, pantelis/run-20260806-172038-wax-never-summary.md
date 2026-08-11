# Debug run summary — run-20260806-172038-wax-never

Player: wax (never)

## Outcome

- outcome: **game_over**
- rounds recorded: **12** (round 0 -> 11)
- love: 15 -> **60**
- lives left: **1**
- village level: **4** (xp 101)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 379 |
| income (potential, nothing lost) | 528 |
| **income lost to buildings dying** | **149** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 9 |
| upkeep potential | 12 |
| upkeep unpaid because buildings died | 3 |
| net (actual) | 370 |
| net (potential) | 516 |
| damage dealt (building-credited) | 9233 |
| damage dealt (lightning, no shooter) | 120 |
| damage taken by buildings (HP) | 4930 |
| lives lost | 2 |
| enemies spawned | 140 |
| kills | 127 |
| leaks (base breaches) | 2 |
| kidnaps | 10 |
| buildings placed | 14 |
| love spent on buildings | 155 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 0 | 5 | 10 | 5 | 0 | 1 |
| 1 | 15 | 15 | 0 | 0 | 0 |
| 2 | 15 | 15 | 0 | 0 | 0 |
| 3 | 15 | 15 | 0 | 0 | 0 |
| 4 | 20 | 20 | 0 | 0 | 0 |
| 5 | 25 | 25 | 0 | 0 | 0 |
| 6 | 41 | 41 | 0 | 0 | 0 |
| 7 | 61 | 61 | 0 | 0 | 0 |
| 8 | 48 | 66 | 18 | 0 | 2 |
| 9 | 65 | 82 | 17 | 0 | 2 |
| 10 | 9 | 88 | 79 | 3 | 13 |
| 11 | 60 | 90 | 30 | 0 | 3 |

Net effect of losing buildings: **146 love** (149 income lost, 3 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 0 | 15 | 5 | 0 | 5 | 20 |
| 1 | 0 | 15 | 0 | 15 | 15 |
| 2 | 15 | 15 | 0 | 15 | 30 |
| 3 | 6 | 15 | 0 | 15 | 21 |
| 4 | 1 | 20 | 0 | 20 | 21 |
| 5 | 1 | 25 | 0 | 25 | 26 |
| 6 | 6 | 41 | 0 | 41 | 47 |
| 7 | 7 | 61 | 0 | 61 | 68 |
| 8 | 2 | 48 | 3 | 45 | 47 |
| 9 | 7 | 65 | 3 | 62 | 69 |
| 10 | 4 | 9 | 0 | 9 | 13 |
| 11 | 3 | 60 | 3 | 57 | 60 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 9233 | 100.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| economic | 3434 | 69.7% |
| defence | 1176 | 23.9% |
| storm_priest | 320 | 6.5% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 155 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep**

| building type | love | share |
|---|---:|---:|
| storm_priest | 9 | 100.0% |

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 1 | 1 | 2 | 21 | 19 | 1876 |
| 11 | 1 | 1 | 1 | 22 | 16 | 1498 |
