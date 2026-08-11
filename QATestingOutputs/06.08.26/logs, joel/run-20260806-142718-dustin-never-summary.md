# Debug run summary — run-20260806-142718-dustin-never

Player: dustin (never)

## Outcome

- outcome: **game_over**
- rounds recorded: **10** (round 0 -> 9)
- love: 15 -> **16**
- lives left: **1**
- village level: **2** (xp 42)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 158 |
| income (potential, nothing lost) | 195 |
| **income lost to buildings dying** | **37** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 4 |
| upkeep potential | 4 |
| upkeep unpaid because buildings died | 0 |
| net (actual) | 154 |
| net (potential) | 191 |
| damage dealt (building-credited) | 5124 |
| damage dealt (lightning, no shooter) | 156 |
| damage taken by buildings (HP) | 1720 |
| lives lost | 2 |
| enemies spawned | 97 |
| kills | 80 |
| leaks (base breaches) | 2 |
| kidnaps | 7 |
| buildings placed | 7 |
| love spent on buildings | 85 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 0 | 5 | 10 | 5 | 0 | 1 |
| 1 | 15 | 15 | 0 | 0 | 0 |
| 2 | 15 | 15 | 0 | 0 | 0 |
| 3 | 15 | 15 | 0 | 0 | 0 |
| 4 | 10 | 15 | 5 | 0 | 1 |
| 5 | 10 | 19 | 9 | 0 | 1 |
| 6 | 14 | 19 | 5 | 0 | 1 |
| 7 | 29 | 29 | 0 | 0 | 1 |
| 8 | 29 | 29 | 0 | 0 | 1 |
| 9 | 16 | 29 | 13 | 0 | 1 |

Net effect of losing buildings: **37 love** (37 income lost, 0 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 0 | 15 | 5 | 0 | 5 | 20 |
| 1 | 0 | 15 | 0 | 15 | 15 |
| 2 | 8 | 15 | 0 | 15 | 23 |
| 3 | 2 | 15 | 0 | 15 | 17 |
| 4 | 7 | 10 | 0 | 10 | 17 |
| 5 | 12 | 10 | 0 | 10 | 22 |
| 6 | 2 | 14 | 0 | 14 | 16 |
| 7 | 1 | 29 | 0 | 29 | 30 |
| 8 | 5 | 29 | 1 | 28 | 33 |
| 9 | 3 | 16 | 3 | 13 | 16 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 5124 | 100.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| economic | 1290 | 75.0% |
| defence | 430 | 25.0% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 85 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep**

| building type | love | share |
|---|---:|---:|
| storm_priest | 4 | 100.0% |

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 1 | 1 | 2 | 10 | 4 | 420 |
| 9 | 1 | 1 | 1 | 22 | 16 | 1071 |
