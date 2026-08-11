# Debug run summary — run-20260806-144523-Whyistimehere-never

Player: Whyistimehere (never)

## Outcome

- outcome: **game_over**
- rounds recorded: **9** (round 0 -> 8)
- love: 15 -> **15**
- lives left: **1**
- village level: **2** (xp 23)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 134 |
| income (potential, nothing lost) | 182 |
| **income lost to buildings dying** | **48** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 1 |
| upkeep potential | 1 |
| upkeep unpaid because buildings died | 0 |
| net (actual) | 133 |
| net (potential) | 181 |
| damage dealt (building-credited) | 3949 |
| damage dealt (lightning, no shooter) | 72 |
| damage taken by buildings (HP) | 1440 |
| lives lost | 2 |
| enemies spawned | 75 |
| kills | 60 |
| leaks (base breaches) | 2 |
| kidnaps | 8 |
| buildings placed | 10 |
| love spent on buildings | 115 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 0 | 5 | 10 | 5 | 0 | 1 |
| 1 | 10 | 10 | 0 | 0 | 0 |
| 2 | 10 | 10 | 0 | 0 | 0 |
| 3 | 15 | 15 | 0 | 0 | 0 |
| 4 | 19 | 19 | 0 | 0 | 0 |
| 5 | 24 | 24 | 0 | 0 | 0 |
| 6 | 19 | 24 | 5 | 0 | 1 |
| 7 | 16 | 35 | 19 | 0 | 3 |
| 8 | 16 | 35 | 19 | 0 | 3 |

Net effect of losing buildings: **48 love** (48 income lost, 0 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 0 | 15 | 5 | 0 | 5 | 20 |
| 1 | 10 | 10 | 0 | 10 | 20 |
| 2 | 3 | 10 | 0 | 10 | 13 |
| 3 | 3 | 15 | 0 | 15 | 18 |
| 4 | 3 | 19 | 0 | 19 | 22 |
| 5 | 2 | 24 | 0 | 24 | 26 |
| 6 | 26 | 19 | 0 | 19 | 45 |
| 7 | 9 | 16 | 0 | 16 | 25 |
| 8 | 0 | 16 | 1 | 15 | 15 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 3949 | 100.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| economic | 1330 | 92.4% |
| defence | 110 | 7.6% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 115 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep**

| building type | love | share |
|---|---:|---:|
| storm_priest | 1 | 100.0% |

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 7 | 1 | 1 | 2 | 16 | 10 | 726 |
| 8 | 1 | 1 | 1 | 19 | 12 | 832 |
