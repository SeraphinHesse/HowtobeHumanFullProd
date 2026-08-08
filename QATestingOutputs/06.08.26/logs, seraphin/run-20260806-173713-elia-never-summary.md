# Debug run summary — run-20260806-173713-elia-never

Player: elia (never)

## Outcome

- outcome: **game_over**
- rounds recorded: **7** (round 1 -> 7)
- love: 15 -> **15**
- lives left: **1**
- village level: **2** (xp 5)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 47 |
| income (potential, nothing lost) | 72 |
| **income lost to buildings dying** | **25** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 0 |
| upkeep potential | 0 |
| upkeep unpaid because buildings died | 0 |
| net (actual) | 47 |
| net (potential) | 72 |
| damage dealt (building-credited) | 2623 |
| damage dealt (lightning, no shooter) | 0 |
| damage taken by buildings (HP) | 975 |
| lives lost | 2 |
| enemies spawned | 55 |
| kills | 43 |
| leaks (base breaches) | 2 |
| kidnaps | 7 |
| buildings placed | 5 |
| love spent on buildings | 50 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 1 | 5 | 10 | 5 | 0 | 1 |
| 2 | 5 | 10 | 5 | 0 | 1 |
| 3 | 5 | 10 | 5 | 0 | 1 |
| 4 | 5 | 10 | 5 | 0 | 1 |
| 5 | 5 | 10 | 5 | 0 | 1 |
| 6 | 10 | 10 | 0 | 0 | 1 |
| 7 | 12 | 12 | 0 | 0 | 1 |

Net effect of losing buildings: **25 love** (25 income lost, 0 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 1 | 15 | 5 | 0 | 5 | 20 |
| 2 | 10 | 5 | 0 | 5 | 15 |
| 3 | 5 | 5 | 0 | 5 | 10 |
| 4 | 3 | 5 | 0 | 5 | 8 |
| 5 | 8 | 5 | 0 | 5 | 13 |
| 6 | 3 | 10 | 0 | 10 | 13 |
| 7 | 3 | 12 | 0 | 12 | 15 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 2623 | 100.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| economic | 625 | 64.1% |
| defence | 350 | 35.9% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 50 |
| unlock | 0 |

Upkeep billed by building type:

**Upkeep** — none recorded.

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 1 | 1 | 2 | 3 | 1 | 56 |
| 7 | 1 | 1 | 1 | 16 | 11 | 719 |
