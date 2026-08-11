# Debug run summary — run-20260806-153736-bug-a_bit

Player: bug (a_bit)

## Outcome

- outcome: **game_over**
- rounds recorded: **11** (round 1 -> 11)
- love: 5 -> **39**
- lives left: **1**
- village level: **4** (xp 90)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 198 |
| income (potential, nothing lost) | 280 |
| **income lost to buildings dying** | **82** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 0 |
| upkeep potential | 0 |
| upkeep unpaid because buildings died | 0 |
| net (actual) | 198 |
| net (potential) | 280 |
| damage dealt (building-credited) | 8856 |
| damage dealt (lightning, no shooter) | 0 |
| damage taken by buildings (HP) | 3826 |
| lives lost | 2 |
| enemies spawned | 139 |
| kills | 122 |
| leaks (base breaches) | 2 |
| kidnaps | 6 |
| buildings placed | 11 |
| love spent on buildings | 110 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 1 | 10 | 10 | 0 | 0 | 0 |
| 2 | 10 | 10 | 0 | 0 | 0 |
| 3 | 14 | 14 | 0 | 0 | 0 |
| 4 | 14 | 23 | 9 | 0 | 1 |
| 5 | 23 | 23 | 0 | 0 | 0 |
| 6 | 23 | 23 | 0 | 0 | 0 |
| 7 | 16 | 30 | 14 | 0 | 2 |
| 8 | 16 | 34 | 18 | 0 | 2 |
| 9 | 25 | 34 | 9 | 0 | 2 |
| 10 | 9 | 36 | 27 | 0 | 10 |
| 11 | 38 | 43 | 5 | 0 | 2 |

Net effect of losing buildings: **82 love** (82 income lost, 0 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 1 | 5 | 10 | 0 | 10 | 15 |
| 2 | 8 | 10 | 0 | 10 | 18 |
| 3 | 3 | 14 | 0 | 14 | 17 |
| 4 | 2 | 14 | 0 | 14 | 16 |
| 5 | 6 | 23 | 0 | 23 | 29 |
| 6 | 9 | 23 | 0 | 23 | 32 |
| 7 | 1 | 16 | 0 | 16 | 17 |
| 8 | 2 | 16 | 0 | 16 | 18 |
| 9 | 8 | 25 | 0 | 25 | 33 |
| 10 | 2 | 9 | 0 | 9 | 11 |
| 11 | 1 | 38 | 0 | 38 | 39 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 8856 | 100.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| defence | 2096 | 54.8% |
| economic | 1730 | 45.2% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 110 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep** — none recorded.

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 1 | 1 | 2 | 21 | 21 | 2052 |
| 11 | 1 | 1 | 1 | 22 | 11 | 1113 |
