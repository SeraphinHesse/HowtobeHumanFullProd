# Debug run summary — run-20260806-134601-Caro-never

Player: Caro (never)

## Outcome

- outcome: **game_over**
- rounds recorded: **8** (round 0 -> 7)
- love: 15 -> **40**
- lives left: **1**
- village level: **2** (xp 5)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 110 |
| income (potential, nothing lost) | 110 |
| **income lost to buildings dying** | **0** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 0 |
| upkeep potential | 0 |
| upkeep unpaid because buildings died | 0 |
| net (actual) | 110 |
| net (potential) | 110 |
| damage dealt (building-credited) | 3668 |
| damage dealt (lightning, no shooter) | 0 |
| damage taken by buildings (HP) | 750 |
| lives lost | 2 |
| enemies spawned | 56 |
| kills | 50 |
| leaks (base breaches) | 2 |
| kidnaps | 2 |
| buildings placed | 3 |
| love spent on buildings | 30 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 0 | 10 | 10 | 0 | 0 | 0 |
| 1 | 10 | 10 | 0 | 0 | 0 |
| 2 | 10 | 10 | 0 | 0 | 0 |
| 3 | 14 | 14 | 0 | 0 | 0 |
| 4 | 14 | 14 | 0 | 0 | 0 |
| 5 | 14 | 14 | 0 | 0 | 1 |
| 6 | 18 | 18 | 0 | 0 | 0 |
| 7 | 20 | 20 | 0 | 0 | 1 |

Net effect of losing buildings: **0 love** (0 income lost, 0 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 0 | 15 | 10 | 0 | 10 | 25 |
| 1 | 15 | 10 | 0 | 10 | 25 |
| 2 | 25 | 10 | 0 | 10 | 35 |
| 3 | 0 | 14 | 0 | 14 | 14 |
| 4 | 14 | 14 | 0 | 14 | 28 |
| 5 | 28 | 14 | 0 | 14 | 42 |
| 6 | 2 | 18 | 0 | 18 | 20 |
| 7 | 20 | 20 | 0 | 20 | 40 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 3668 | 100.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| defence | 750 | 100.0% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 30 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep** — none recorded.

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 1 | 1 | 2 | 1 | 0 | 0 |
| 7 | 1 | 1 | 1 | 16 | 12 | 966 |
