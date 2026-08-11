# Debug run summary — run-20260806-174401-elia-never

Player: elia (never)

## Outcome

- outcome: **game_over**
- rounds recorded: **5** (round 1 -> 5)
- love: 5 -> **20**
- lives left: **1**
- village level: **1** (xp 22)
- cheats used this run: **no**

## Totals

| metric | total |
|---|---:|
| income (actual) | 30 |
| income (potential, nothing lost) | 44 |
| **income lost to buildings dying** | **14** |
| story income (Boss1B/3B, paid silently) | 0 |
| painter lump sums | 0 |
| upkeep billed (actual) | 0 |
| upkeep potential | 0 |
| upkeep unpaid because buildings died | 0 |
| net (actual) | 30 |
| net (potential) | 44 |
| damage dealt (building-credited) | 1260 |
| damage dealt (lightning, no shooter) | 0 |
| damage taken by buildings (HP) | 401 |
| lives lost | 2 |
| enemies spawned | 26 |
| kills | 17 |
| leaks (base breaches) | 2 |
| kidnaps | 2 |
| buildings placed | 2 |
| love spent on buildings | 20 |

> `lives_lost` is NOT HP damage: a base breach applies none. Lightning damage is listed separately because it has no shooter and earns no `RoundStats` credit.

## The actual-vs-potential income gap

Payday's income sweep AND its upkeep sweep both skip a building that is not alive, so a building destroyed during the wave earns nothing and pays no upkeep. Both halves, never fused:

| round | income actual | income potential | lost | upkeep unpaid | dead at payday |
|---:|---:|---:|---:|---:|---:|
| 1 | 5 | 5 | 0 | 0 | 0 |
| 2 | 5 | 5 | 0 | 0 | 0 |
| 3 | 10 | 10 | 0 | 0 | 0 |
| 4 | 5 | 10 | 5 | 0 | 1 |
| 5 | 5 | 14 | 9 | 0 | 1 |

Net effect of losing buildings: **14 love** (14 income lost, 0 upkeep not billed).

## Income curve

| round | love start | income | upkeep | net | love end |
|---:|---:|---:|---:|---:|---:|
| 1 | 5 | 5 | 0 | 5 | 10 |
| 2 | 10 | 5 | 0 | 5 | 15 |
| 3 | 5 | 10 | 0 | 10 | 15 |
| 4 | 15 | 5 | 0 | 5 | 20 |
| 5 | 15 | 5 | 0 | 5 | 20 |

## Damage share by building type

**Damage dealt**

| building type | dmg | share |
|---|---:|---:|
| defence | 1260 | 100.0% |

**Damage taken (HP)**

| building type | dmg | share |
|---|---:|---:|
| economic | 341 | 85.0% |
| defence | 60 | 15.0% |

## Love-spend breakdown

| reason | love |
|---|---:|
| place | 20 |

Upkeep billed by building type:

**Upkeep** — none recorded.

## Leak rounds

| round | leaks | lives lost | lives left | wave size | kills | dmg dealt |
|---:|---:|---:|---:|---:|---:|---:|
| 4 | 1 | 1 | 2 | 7 | 5 | 350 |
| 5 | 1 | 1 | 1 | 10 | 3 | 280 |
