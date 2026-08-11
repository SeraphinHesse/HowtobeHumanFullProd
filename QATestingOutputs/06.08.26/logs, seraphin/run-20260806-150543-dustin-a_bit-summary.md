# Debug run summary — run-20260806-150543-dustin-a_bit

Player: dustin (a_bit)

## Outcome

- outcome: **game_over**
- rounds recorded: **6** (round 1 -> 6)
- love: 5 -> **11**
- lives left: **1**
- village level: **1** (xp 41)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 50 |
| income (potential, nothing lost) | 70 |
| **income lost to buildings dying** | **20** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 0 |
| upkeep potential | 0 |
| upkeep unpaid because buildings died | 0 |
| net (actual) | 50 |
| net (potential) | 70 |
| damage dealt (building-credited) | 1680 |
| damage dealt (lightning, no shooter) | 0 |
| damage taken by buildings (HP) | 960 |
| lives lost | 2 |
| enemies spawned | 39 |
| kills | 30 |
| leaks (base breaches) | 2 |
| kidnaps | 6 |
| buildings placed | 5 |
| love spent on buildings | 50 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 1 | 5 | 5 | 0 | 0 | 0 |
| 2 | 10 | 10 | 0 | 0 | 0 |
| 3 | 10 | 10 | 0 | 0 | 1 |
| 4 | 15 | 15 | 0 | 0 | 1 |
| 5 | 5 | 15 | 10 | 0 | 2 |
| 6 | 5 | 15 | 10 | 0 | 2 |

Net effect of losing buildings: **20 love** (20 income lost, 0 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 1 | 5 | 5 | 0 | 5 | 10 |
| 2 | 0 | 10 | 0 | 10 | 10 |
| 3 | 10 | 10 | 0 | 10 | 20 |
| 4 | 3 | 15 | 0 | 15 | 18 |
| 5 | 1 | 5 | 0 | 5 | 6 |
| 6 | 6 | 5 | 0 | 5 | 11 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 1680 | 100.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| economic | 490 | 51.0% |
| defence | 470 | 49.0% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 50 |

Upkeep billed by building type:

**Upkeep** — none recorded.

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 3 | 1 | 1 | 2 | 5 | 3 | 168 |
| 4 | 1 | 1 | 1 | 7 | 4 | 224 |
