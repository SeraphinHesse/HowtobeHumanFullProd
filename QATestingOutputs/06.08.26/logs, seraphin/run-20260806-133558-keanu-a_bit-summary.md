# Debug run summary — run-20260806-133558-keanu-a_bit

Player: keanu (a_bit)

## Outcome

- outcome: **game_over**
- rounds recorded: **22** (round 1 -> 22)
- love: 0 -> **32**
- lives left: **1**
- village level: **9** (xp 100)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 1056 |
| income (potential, nothing lost) | 1279 |
| **income lost to buildings dying** | **223** |
| story income (Boss1B/3B, paid silently) | 23 |
| painter lump sums | 0 |
| upkeep billed (actual) | 202 |
| upkeep potential | 223 |
| upkeep unpaid because buildings died | 21 |
| net (actual) | 854 |
| net (potential) | 1056 |
| damage dealt (building-credited) | 82299 |
| damage dealt (lightning, no shooter) | 984 |
| damage taken by buildings (HP) | 16228 |
| lives lost | 2 |
| enemies spawned | 752 |
| kills | 686 |
| leaks (base breaches) | 2 |
| kidnaps | 39 |
| buildings placed | 27 |
| love spent on buildings | 454 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 1 | 14 | 14 | 0 | 0 | 0 |
| 2 | 19 | 19 | 0 | 0 | 0 |
| 3 | 23 | 23 | 0 | 0 | 0 |
| 4 | 28 | 28 | 0 | 0 | 0 |
| 5 | 32 | 32 | 0 | 0 | 0 |
| 6 | 32 | 32 | 0 | 0 | 1 |
| 7 | 43 | 43 | 0 | 0 | 1 |
| 8 | 48 | 48 | 0 | 0 | 1 |
| 9 | 48 | 48 | 0 | 0 | 0 |
| 10 | 54 | 63 | 9 | 0 | 5 |
| 11 | 65 | 65 | 0 | 0 | 0 |
| 12 | 58 | 72 | 14 | 0 | 1 |
| 13 | 72 | 72 | 0 | 0 | 0 |
| 14 | 76 | 76 | 0 | 0 | 1 |
| 15 | 55 | 78 | 23 | 0 | 4 |
| 16 | 69 | 78 | 9 | 0 | 4 |
| 17 | 55 | 78 | 23 | 0 | 6 |
| 18 | 57 | 80 | 23 | 0 | 8 |
| 19 | 57 | 80 | 23 | 6 | 6 |
| 20 | 64 | 82 | 18 | 6 | 9 |
| 21 | 34 | 84 | 50 | 6 | 12 |
| 22 | 53 | 84 | 31 | 3 | 8 |

Net effect of losing buildings: **202 love** (223 income lost, 21 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 14 | 0 | 14 | 14 |
| 2 | 4 | 19 | 0 | 19 | 23 |
| 3 | 1 | 23 | 0 | 23 | 24 |
| 4 | 4 | 28 | 0 | 28 | 32 |
| 5 | 0 | 32 | 0 | 32 | 32 |
| 6 | 2 | 32 | 0 | 32 | 34 |
| 7 | 9 | 43 | 0 | 43 | 52 |
| 8 | 1 | 48 | 0 | 48 | 49 |
| 9 | 3 | 48 | 0 | 48 | 51 |
| 10 | 6 | 54 | 0 | 54 | 60 |
| 11 | 5 | 65 | 5 | 60 | 65 |
| 12 | 9 | 58 | 5 | 53 | 62 |
| 13 | 2 | 72 | 8 | 64 | 66 |
| 14 | 1 | 76 | 13 | 63 | 64 |
| 15 | 0 | 55 | 17 | 38 | 38 |
| 16 | 8 | 69 | 17 | 52 | 60 |
| 17 | 0 | 55 | 19 | 36 | 36 |
| 18 | 0 | 57 | 19 | 38 | 38 |
| 19 | 4 | 57 | 19 | 38 | 42 |
| 20 | 0 | 64 | 22 | 42 | 50 |
| 21 | 0 | 34 | 26 | 8 | 14 |
| 22 | 2 | 53 | 32 | 21 | 32 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 60669 | 73.7% |
| aoe_defence | 21630 | 26.3% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| defence | 9680 | 59.6% |
| economic | 4692 | 28.9% |
| wall_builder | 1836 | 11.3% |
| storm_priest | 20 | 0.1% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 364 |
| research | 90 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep**

| building type | love | share |
|---|---:|---:|
| aoe_defence | 150 | 74.3% |
| storm_priest | 46 | 22.8% |
| wall_builder | 6 | 3.0% |

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 21 | 1 | 1 | 2 | 78 | 66 | 11632 |
| 22 | 1 | 1 | 1 | 86 | 29 | 5703 |
