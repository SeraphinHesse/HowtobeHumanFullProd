# Debug run summary — run-20260806-170215-al-never

Player: al (never)

## Outcome

- outcome: **game_over**
- rounds recorded: **12** (round 0 -> 11)
- love: 15 -> **34**
- lives left: **1**
- village level: **4** (xp 94)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 309 |
| income (potential, nothing lost) | 469 |
| **income lost to buildings dying** | **160** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 9 |
| upkeep potential | 14 |
| upkeep unpaid because buildings died | 5 |
| net (actual) | 300 |
| net (potential) | 455 |
| damage dealt (building-credited) | 8751 |
| damage dealt (lightning, no shooter) | 324 |
| damage taken by buildings (HP) | 5145 |
| lives lost | 2 |
| enemies spawned | 140 |
| kills | 115 |
| leaks (base breaches) | 2 |
| kidnaps | 17 |
| buildings placed | 11 |
| love spent on buildings | 125 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 0 | 5 | 10 | 5 | 0 | 1 |
| 1 | 14 | 14 | 0 | 0 | 0 |
| 2 | 19 | 19 | 0 | 0 | 0 |
| 3 | 23 | 23 | 0 | 0 | 0 |
| 4 | 23 | 23 | 0 | 0 | 0 |
| 5 | 23 | 32 | 9 | 0 | 1 |
| 6 | 37 | 37 | 0 | 0 | 0 |
| 7 | 44 | 53 | 9 | 0 | 3 |
| 8 | 39 | 57 | 18 | 0 | 3 |
| 9 | 39 | 65 | 26 | 0 | 3 |
| 10 | 9 | 67 | 58 | 5 | 11 |
| 11 | 34 | 69 | 35 | 0 | 5 |

Net effect of losing buildings: **155 love** (160 income lost, 5 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 0 | 15 | 5 | 0 | 5 | 20 |
| 1 | 5 | 14 | 0 | 14 | 19 |
| 2 | 2 | 19 | 0 | 19 | 21 |
| 3 | 6 | 23 | 0 | 23 | 29 |
| 4 | 2 | 23 | 0 | 23 | 25 |
| 5 | 0 | 23 | 0 | 23 | 23 |
| 6 | 3 | 37 | 0 | 37 | 40 |
| 7 | 0 | 44 | 0 | 44 | 44 |
| 8 | 3 | 39 | 1 | 38 | 41 |
| 9 | 1 | 39 | 3 | 36 | 37 |
| 10 | 7 | 9 | 0 | 9 | 16 |
| 11 | 5 | 34 | 5 | 29 | 34 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 8751 | 100.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| economic | 3200 | 62.2% |
| defence | 1625 | 31.6% |
| storm_priest | 320 | 6.2% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 125 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep**

| building type | love | share |
|---|---:|---:|
| storm_priest | 9 | 100.0% |

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 1 | 1 | 2 | 21 | 17 | 1855 |
| 11 | 1 | 1 | 1 | 22 | 11 | 1051 |
