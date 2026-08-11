# Debug run summary — run-20260806-140345-Caro-a_bit

Player: Caro (a_bit)

## Outcome

- outcome: **game_over**
- rounds recorded: **10** (round 0 -> 9)
- love: 15 -> **23**
- lives left: **1**
- village level: **2** (xp 49)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 165 |
| income (potential, nothing lost) | 208 |
| **income lost to buildings dying** | **43** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 2 |
| upkeep potential | 2 |
| upkeep unpaid because buildings died | 0 |
| net (actual) | 163 |
| net (potential) | 206 |
| damage dealt (building-credited) | 5698 |
| damage dealt (lightning, no shooter) | 132 |
| damage taken by buildings (HP) | 1170 |
| lives lost | 2 |
| enemies spawned | 97 |
| kills | 88 |
| leaks (base breaches) | 2 |
| kidnaps | 7 |
| buildings placed | 9 |
| love spent on buildings | 105 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 0 | 10 | 10 | 0 | 0 | 0 |
| 1 | 10 | 10 | 0 | 0 | 0 |
| 2 | 14 | 14 | 0 | 0 | 0 |
| 3 | 14 | 14 | 0 | 0 | 0 |
| 4 | 19 | 19 | 0 | 0 | 0 |
| 5 | 19 | 24 | 5 | 0 | 1 |
| 6 | 19 | 24 | 5 | 0 | 1 |
| 7 | 26 | 31 | 5 | 0 | 1 |
| 8 | 17 | 31 | 14 | 0 | 2 |
| 9 | 17 | 31 | 14 | 0 | 2 |

Net effect of losing buildings: **43 love** (43 income lost, 0 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 0 | 15 | 10 | 0 | 10 | 25 |
| 1 | 15 | 10 | 0 | 10 | 25 |
| 2 | 3 | 14 | 0 | 14 | 17 |
| 3 | 0 | 14 | 0 | 14 | 14 |
| 4 | 4 | 19 | 0 | 19 | 23 |
| 5 | 2 | 19 | 0 | 19 | 21 |
| 6 | 1 | 19 | 0 | 19 | 20 |
| 7 | 0 | 26 | 0 | 26 | 26 |
| 8 | 1 | 17 | 1 | 16 | 17 |
| 9 | 7 | 17 | 1 | 16 | 23 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 5698 | 100.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| economic | 1170 | 100.0% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 105 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep**

| building type | love | share |
|---|---:|---:|
| storm_priest | 2 | 100.0% |

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 1 | 1 | 2 | 1 | 0 | 0 |
| 9 | 1 | 1 | 1 | 22 | 19 | 1407 |
