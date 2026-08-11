# Debug run summary — run-20260806-154427-UWAGA-a_bit

Player: UWAGA (a_bit)

## Outcome

- outcome: **game_over**
- rounds recorded: **13** (round 0 -> 12)
- love: 15 -> **43**
- lives left: **1**
- village level: **5** (xp 18)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 314 |
| income (potential, nothing lost) | 354 |
| **income lost to buildings dying** | **40** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 6 |
| upkeep potential | 12 |
| upkeep unpaid because buildings died | 6 |
| net (actual) | 308 |
| net (potential) | 342 |
| damage dealt (building-credited) | 12942 |
| damage dealt (lightning, no shooter) | 0 |
| damage taken by buildings (HP) | 4424 |
| lives lost | 2 |
| enemies spawned | 167 |
| kills | 157 |
| leaks (base breaches) | 2 |
| kidnaps | 9 |
| buildings placed | 11 |
| love spent on buildings | 170 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 0 | 5 | 10 | 5 | 0 | 1 |
| 1 | 15 | 15 | 0 | 0 | 0 |
| 2 | 19 | 19 | 0 | 0 | 0 |
| 3 | 14 | 23 | 9 | 0 | 1 |
| 4 | 23 | 23 | 0 | 0 | 0 |
| 5 | 23 | 23 | 0 | 0 | 0 |
| 6 | 31 | 31 | 0 | 0 | 0 |
| 7 | 33 | 33 | 0 | 0 | 0 |
| 8 | 33 | 33 | 0 | 0 | 0 |
| 9 | 33 | 33 | 0 | 3 | 1 |
| 10 | 9 | 35 | 26 | 3 | 10 |
| 11 | 37 | 37 | 0 | 0 | 2 |
| 12 | 39 | 39 | 0 | 0 | 3 |

Net effect of losing buildings: **34 love** (40 income lost, 6 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 0 | 15 | 5 | 0 | 5 | 20 |
| 1 | 0 | 15 | 0 | 15 | 15 |
| 2 | 3 | 19 | 0 | 19 | 22 |
| 3 | 0 | 14 | 0 | 14 | 14 |
| 4 | 4 | 23 | 0 | 23 | 27 |
| 5 | 7 | 23 | 0 | 23 | 30 |
| 6 | 0 | 31 | 0 | 31 | 31 |
| 7 | 1 | 33 | 0 | 33 | 34 |
| 8 | 4 | 33 | 0 | 33 | 37 |
| 9 | 2 | 33 | 0 | 33 | 35 |
| 10 | 0 | 9 | 0 | 9 | 9 |
| 11 | 9 | 37 | 3 | 34 | 43 |
| 12 | 7 | 39 | 3 | 36 | 43 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 11755 | 90.8% |
| aoe_defence | 1187 | 9.2% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| defence | 2754 | 62.3% |
| economic | 850 | 19.2% |
| blocker | 500 | 11.3% |
| aoe_defence | 320 | 7.2% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 150 |
| research | 20 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep**

| building type | love | share |
|---|---:|---:|
| aoe_defence | 6 | 100.0% |

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 3 | 1 | 1 | 2 | 5 | 3 | 252 |
| 10 | 1 | 1 | 1 | 21 | 20 | 2229 |
