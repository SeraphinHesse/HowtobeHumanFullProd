# Debug run summary — run-20260806-141429-Sammy-a_bit

Player: Sammy (a_bit)

## Outcome

- outcome: **game_over**
- rounds recorded: **16** (round 0 -> 15)
- love: 15 -> **64**
- lives left: **1**
- village level: **6** (xp 1)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 362 |
| income (potential, nothing lost) | 499 |
| **income lost to buildings dying** | **137** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 21 |
| upkeep potential | 23 |
| upkeep unpaid because buildings died | 2 |
| net (actual) | 341 |
| net (potential) | 476 |
| damage dealt (building-credited) | 23167 |
| damage dealt (lightning, no shooter) | 0 |
| damage taken by buildings (HP) | 6796 |
| lives lost | 2 |
| enemies spawned | 281 |
| kills | 251 |
| leaks (base breaches) | 2 |
| kidnaps | 26 |
| buildings placed | 14 |
| love spent on buildings | 245 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 0 | 5 | 10 | 5 | 0 | 1 |
| 1 | 10 | 10 | 0 | 0 | 0 |
| 2 | 10 | 10 | 0 | 0 | 0 |
| 3 | 10 | 15 | 5 | 0 | 2 |
| 4 | 10 | 15 | 5 | 0 | 1 |
| 5 | 15 | 15 | 0 | 0 | 0 |
| 6 | 15 | 15 | 0 | 0 | 0 |
| 7 | 29 | 29 | 0 | 0 | 1 |
| 8 | 25 | 34 | 9 | 0 | 1 |
| 9 | 29 | 38 | 9 | 0 | 2 |
| 10 | 9 | 48 | 39 | 0 | 10 |
| 11 | 24 | 50 | 26 | 0 | 4 |
| 12 | 39 | 52 | 13 | 0 | 2 |
| 13 | 39 | 52 | 13 | 0 | 3 |
| 14 | 39 | 52 | 13 | 0 | 3 |
| 15 | 54 | 54 | 0 | 2 | 4 |

Net effect of losing buildings: **135 love** (137 income lost, 2 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 0 | 15 | 5 | 0 | 5 | 20 |
| 1 | 0 | 10 | 0 | 10 | 10 |
| 2 | 3 | 10 | 0 | 10 | 13 |
| 3 | 3 | 10 | 0 | 10 | 13 |
| 4 | 3 | 10 | 0 | 10 | 13 |
| 5 | 3 | 15 | 0 | 15 | 18 |
| 6 | 8 | 15 | 0 | 15 | 23 |
| 7 | 3 | 29 | 0 | 29 | 32 |
| 8 | 5 | 25 | 0 | 25 | 30 |
| 9 | 5 | 29 | 0 | 29 | 34 |
| 10 | 0 | 9 | 0 | 9 | 9 |
| 11 | 9 | 24 | 0 | 24 | 33 |
| 12 | 0 | 39 | 2 | 37 | 37 |
| 13 | 2 | 39 | 5 | 34 | 36 |
| 14 | 5 | 39 | 7 | 32 | 37 |
| 15 | 17 | 54 | 7 | 47 | 64 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 21903 | 94.5% |
| aoe_defence | 1264 | 5.5% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| defence | 4324 | 63.6% |
| economic | 2328 | 34.3% |
| aoe_defence | 144 | 2.1% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 195 |
| research | 50 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep**

| building type | love | share |
|---|---:|---:|
| defence | 12 | 57.1% |
| aoe_defence | 9 | 42.9% |

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 1 | 1 | 2 | 21 | 19 | 2072 |
| 11 | 1 | 1 | 1 | 22 | 14 | 1507 |
