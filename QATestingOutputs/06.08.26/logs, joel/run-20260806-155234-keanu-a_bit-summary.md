# Debug run summary — run-20260806-155234-keanu-a_bit

Player: keanu (a_bit)

## Outcome

- outcome: **game_over**
- rounds recorded: **21** (round 1 -> 21)
- love: 0 -> **78**
- lives left: **1**
- village level: **9** (xp 72)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 1350 |
| income (potential, nothing lost) | 1614 |
| **income lost to buildings dying** | **264** |
| story income (Boss1B/3B, paid silently) | 25 |
| painter lump sums | 0 |
| upkeep billed (actual) | 164 |
| upkeep potential | 237 |
| upkeep unpaid because buildings died | 73 |
| net (actual) | 1186 |
| net (potential) | 1377 |
| damage dealt (building-credited) | 84303 |
| damage dealt (lightning, no shooter) | 0 |
| damage taken by buildings (HP) | 20615 |
| lives lost | 2 |
| enemies spawned | 666 |
| kills | 667 |
| leaks (base breaches) | 2 |
| kidnaps | 33 |
| buildings placed | 35 |
| love spent on buildings | 819 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 1 | 14 | 14 | 0 | 0 | 0 |
| 2 | 18 | 18 | 0 | 0 | 0 |
| 3 | 18 | 18 | 0 | 0 | 0 |
| 4 | 27 | 27 | 0 | 0 | 0 |
| 5 | 31 | 31 | 0 | 0 | 1 |
| 6 | 31 | 31 | 0 | 0 | 1 |
| 7 | 42 | 42 | 0 | 0 | 0 |
| 8 | 47 | 47 | 0 | 3 | 1 |
| 9 | 56 | 56 | 0 | 3 | 1 |
| 10 | 9 | 63 | 54 | 8 | 11 |
| 11 | 65 | 65 | 0 | 5 | 1 |
| 12 | 59 | 73 | 14 | 3 | 3 |
| 13 | 75 | 75 | 0 | 3 | 2 |
| 14 | 76 | 95 | 19 | 0 | 1 |
| 15 | 105 | 105 | 0 | 4 | 2 |
| 16 | 61 | 120 | 59 | 4 | 4 |
| 17 | 118 | 132 | 14 | 6 | 5 |
| 18 | 121 | 135 | 14 | 4 | 3 |
| 19 | 138 | 142 | 4 | 6 | 6 |
| 20 | 147 | 147 | 0 | 13 | 8 |
| 21 | 92 | 178 | 86 | 11 | 14 |

Net effect of losing buildings: **191 love** (264 income lost, 73 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 14 | 0 | 14 | 14 |
| 2 | 4 | 18 | 0 | 18 | 22 |
| 3 | 5 | 18 | 0 | 18 | 23 |
| 4 | 8 | 27 | 0 | 27 | 35 |
| 5 | 8 | 31 | 0 | 31 | 39 |
| 6 | 8 | 31 | 0 | 31 | 39 |
| 7 | 9 | 42 | 0 | 42 | 51 |
| 8 | 6 | 47 | 0 | 47 | 53 |
| 9 | 3 | 56 | 3 | 53 | 56 |
| 10 | 0 | 9 | 0 | 9 | 9 |
| 11 | 9 | 65 | 3 | 62 | 71 |
| 12 | 0 | 59 | 5 | 54 | 54 |
| 13 | 4 | 75 | 7 | 68 | 72 |
| 14 | 2 | 76 | 14 | 62 | 64 |
| 15 | 4 | 105 | 12 | 93 | 97 |
| 16 | 7 | 61 | 14 | 47 | 54 |
| 17 | 4 | 118 | 14 | 104 | 108 |
| 18 | 9 | 121 | 21 | 100 | 109 |
| 19 | 12 | 138 | 21 | 117 | 129 |
| 20 | 0 | 147 | 23 | 124 | 136 |
| 21 | 0 | 92 | 27 | 65 | 78 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 63400 | 75.2% |
| aoe_defence | 20903 | 24.8% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| defence | 9776 | 47.4% |
| blocker | 4596 | 22.3% |
| economic | 3387 | 16.4% |
| aoe_defence | 2134 | 10.4% |
| meditator | 722 | 3.5% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 689 |
| research | 130 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep**

| building type | love | share |
|---|---:|---:|
| aoe_defence | 104 | 63.4% |
| defence | 60 | 36.6% |

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 1 | 1 | 2 | 21 | 19 | 2244 |
| 21 | 1 | 1 | 1 | 78 | 76 | 13878 |
