# Debug run summary — run-20260806-161636-keanu-a_bit

Player: keanu (a_bit)

## Outcome

- outcome: **game_over**
- rounds recorded: **20** (round 1 -> 20)
- love: 0 -> **84**
- lives left: **1**
- village level: **8** (xp 179)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 1052 |
| income (potential, nothing lost) | 1182 |
| **income lost to buildings dying** | **130** |
| story income (Boss1B/3B, paid silently) | 9 |
| painter lump sums | 0 |
| upkeep billed (actual) | 136 |
| upkeep potential | 161 |
| upkeep unpaid because buildings died | 25 |
| net (actual) | 916 |
| net (potential) | 1021 |
| damage dealt (building-credited) | 62959 |
| damage dealt (lightning, no shooter) | 0 |
| damage taken by buildings (HP) | 13329 |
| lives lost | 2 |
| enemies spawned | 588 |
| kills | 573 |
| leaks (base breaches) | 2 |
| kidnaps | 20 |
| buildings placed | 32 |
| love spent on buildings | 559 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 1 | 14 | 14 | 0 | 0 | 0 |
| 2 | 19 | 19 | 0 | 0 | 0 |
| 3 | 23 | 23 | 0 | 0 | 0 |
| 4 | 27 | 27 | 0 | 0 | 0 |
| 5 | 31 | 31 | 0 | 0 | 0 |
| 6 | 36 | 36 | 0 | 0 | 0 |
| 7 | 46 | 46 | 0 | 0 | 0 |
| 8 | 46 | 46 | 0 | 3 | 2 |
| 9 | 51 | 51 | 0 | 0 | 1 |
| 10 | 9 | 61 | 52 | 3 | 14 |
| 11 | 63 | 63 | 0 | 0 | 3 |
| 12 | 65 | 65 | 0 | 0 | 1 |
| 13 | 70 | 70 | 0 | 0 | 1 |
| 14 | 70 | 70 | 0 | 0 | 1 |
| 15 | 81 | 86 | 5 | 0 | 2 |
| 16 | 81 | 86 | 5 | 3 | 5 |
| 17 | 67 | 95 | 28 | 3 | 5 |
| 18 | 83 | 97 | 14 | 0 | 3 |
| 19 | 71 | 97 | 26 | 8 | 11 |
| 20 | 99 | 99 | 0 | 5 | 7 |

Net effect of losing buildings: **105 love** (130 income lost, 25 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 14 | 0 | 14 | 14 |
| 2 | 4 | 19 | 0 | 19 | 23 |
| 3 | 1 | 23 | 0 | 23 | 24 |
| 4 | 4 | 27 | 0 | 27 | 31 |
| 5 | 0 | 31 | 0 | 31 | 31 |
| 6 | 0 | 36 | 0 | 36 | 36 |
| 7 | 6 | 46 | 0 | 46 | 52 |
| 8 | 0 | 46 | 0 | 46 | 46 |
| 9 | 1 | 51 | 3 | 48 | 49 |
| 10 | 4 | 9 | 0 | 9 | 13 |
| 11 | 3 | 63 | 3 | 60 | 63 |
| 12 | 1 | 65 | 8 | 57 | 58 |
| 13 | 2 | 70 | 8 | 62 | 64 |
| 14 | 4 | 70 | 11 | 59 | 63 |
| 15 | 6 | 81 | 14 | 67 | 73 |
| 16 | 3 | 81 | 11 | 70 | 73 |
| 17 | 3 | 67 | 16 | 51 | 54 |
| 18 | 0 | 83 | 22 | 61 | 61 |
| 19 | 6 | 71 | 16 | 55 | 61 |
| 20 | 0 | 99 | 24 | 75 | 84 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 39538 | 62.8% |
| aoe_defence | 17755 | 28.2% |
| sun_scorcher | 5666 | 9.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| defence | 7136 | 53.5% |
| economic | 2699 | 20.2% |
| blocker | 1346 | 10.1% |
| wall_builder | 1326 | 9.9% |
| aoe_defence | 652 | 4.9% |
| painter | 170 | 1.3% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 499 |
| research | 60 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep**

| building type | love | share |
|---|---:|---:|
| aoe_defence | 74 | 54.4% |
| sun_scorcher | 45 | 33.1% |
| wall_builder | 15 | 11.0% |
| defence | 2 | 1.5% |

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 1 | 1 | 2 | 21 | 21 | 2876 |
| 19 | 1 | 1 | 1 | 70 | 51 | 6733 |
