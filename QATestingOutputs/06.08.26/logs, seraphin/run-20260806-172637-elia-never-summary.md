# Debug run summary — run-20260806-172637-elia-never

Player: elia (never)

## Outcome

- outcome: **game_over**
- rounds recorded: **10** (round 0 -> 9)
- love: 15 -> **22**
- lives left: **1**
- village level: **2** (xp 50)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 107 |
| income (potential, nothing lost) | 155 |
| **income lost to buildings dying** | **48** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 0 |
| upkeep potential | 0 |
| upkeep unpaid because buildings died | 0 |
| net (actual) | 107 |
| net (potential) | 155 |
| damage dealt (building-credited) | 4925 |
| damage dealt (lightning, no shooter) | 0 |
| damage taken by buildings (HP) | 2110 |
| lives lost | 2 |
| enemies spawned | 97 |
| kills | 82 |
| leaks (base breaches) | 2 |
| kidnaps | 11 |
| buildings placed | 8 |
| love spent on buildings | 80 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 0 | 10 | 10 | 0 | 0 | 0 |
| 1 | 10 | 10 | 0 | 0 | 0 |
| 2 | 10 | 10 | 0 | 0 | 0 |
| 3 | 5 | 10 | 5 | 0 | 1 |
| 4 | 14 | 14 | 0 | 0 | 0 |
| 5 | 14 | 14 | 0 | 0 | 0 |
| 6 | 5 | 19 | 14 | 0 | 2 |
| 7 | 16 | 21 | 5 | 0 | 3 |
| 8 | 7 | 21 | 14 | 0 | 3 |
| 9 | 16 | 26 | 10 | 0 | 3 |

Net effect of losing buildings: **48 love** (48 income lost, 0 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 0 | 15 | 10 | 0 | 10 | 25 |
| 1 | 5 | 10 | 0 | 10 | 15 |
| 2 | 8 | 10 | 0 | 10 | 18 |
| 3 | 8 | 5 | 0 | 5 | 13 |
| 4 | 8 | 14 | 0 | 14 | 22 |
| 5 | 12 | 14 | 0 | 14 | 26 |
| 6 | 16 | 5 | 0 | 5 | 21 |
| 7 | 4 | 16 | 0 | 16 | 20 |
| 8 | 20 | 7 | 0 | 7 | 27 |
| 9 | 6 | 16 | 0 | 16 | 22 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 4925 | 100.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| economic | 1260 | 59.7% |
| defence | 850 | 40.3% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 80 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep** — none recorded.

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 1 | 1 | 2 | 1 | 0 | 0 |
| 6 | 1 | 1 | 1 | 13 | 8 | 504 |
