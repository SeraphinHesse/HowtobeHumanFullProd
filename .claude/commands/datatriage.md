---
description: Coalesce a multi-machine QA playtest session into one balance report — difficulty curve, economy curve, building/enemy meta, and the player questionnaire — then read it for where the game is too hard and too easy.
argument-hint: "[session dir] [--form <csv>] [--skill never,a_bit]"
---

Triage a playtest session: **$ARGUMENTS**

A playtest session is one directory under `QATestingOutputs/` holding a folder
per host machine, each full of the debug recorder's per-run output
(`-events.jsonl`, `-rounds.csv`, `-summary.md`, `-report.html`). The per-run
summaries answer *"what happened in this run"*. This command answers *"what is
the game doing to players"* by pooling every run at the **round** level.

`tools/qa_triage.py` does all the arithmetic. Your job is to run it, then read
the output like a designer.

## Step 1 — Locate the session

If `$ARGUMENTS` names a directory, use it. Otherwise list `QATestingOutputs/`
and use the newest dated folder, saying which one you picked.

Confirm before going further:

```bash
ls "<session>"                       # one folder per host machine
ls "<session>"/*/ | grep -c events   # how many runs are in the pool
```

If the user mentions a player questionnaire / Google Form export, take its path
for `--form`. Ask for it if a session obviously had one and it wasn't given.

## Step 2 — Decide the exclusions BEFORE generating

The tool excludes by default: developer-bucket runs, runs where cheats were
used, and runs shorter than 3 rounds (menu bounces, not play). Flags:
`--include-devs`, `--include-cheats`, `--min-rounds N`.

`--outcome game_over` keeps only runs the game ended, dropping every run the
player walked away from. Use it when the question is "how hard is the game",
because a run that ends in `quit` censors the curve — it neither survived nor
died, and leaving it in makes every round look slightly safer than it was. Say
which way you ran it: the two views answer different questions, and the
game-over-only cohort is biased toward players who kept going, so its early
rounds read easier than they really were. The report prints this caveat itself
when the filter is on.

Two things the tool cannot know — **ask the user** rather than guessing:

- **Feature-test runs.** A dev testing a mechanic under a real-looking player
  name is indistinguishable from a player. If the user names any, delete those
  runs' four files outright (they asked for it) or exclude them; say exactly
  which `run_id`s went.
- **Whether the dev bucket should count at all.** Default is out.

Identical copies of the same `run_id` on several machines are de-duplicated
automatically; a `run_id` collision with *differing* content is surfaced as an
ingest note in section 1. Read those notes — they mean two machines minted the
same id and one of them is being dropped.

## Step 3 — Generate

```bash
py tools/qa_triage.py "<session>" --form "<form.csv>" --out "<session>/TRIAGE.md"
```

That writes **two** files side by side: `TRIAGE.md` and `TRIAGE.html`. The HTML
is the one to send to a human — same numbers, but with the survival curve,
mortality and breach columns, the economy lines, pacing, adoption and skill-split
charts, hover tooltips, and a table view behind every chart. It is one
self-contained file with no CDN and no external font, so it opens from anywhere.
`--html PATH` moves it; `--no-html` skips it.

Then, whenever the cohort supports it, generate the per-skill cuts too — the
whole point of the skill split is that a wall hitting beginners but not
returning players is a **teaching** problem, not a numbers problem:

```bash
py tools/qa_triage.py "<session>" --skill never  --out "<session>/TRIAGE-never.md"
py tools/qa_triage.py "<session>" --skill a_bit  --out "<session>/TRIAGE-a_bit.md"
```

Skip a bucket with fewer than ~8 runs; say that you skipped it and why.

## Step 4 — Read it, don't just hand it over

Report to the user in prose, in this order. Every claim gets its provenance per
`/report` (**measured** = a number from the report; **inferred** = your read of
it).

1. **Cohort in one line** — runs analysed, machines, what was excluded and why.
   If every run is on one map, say so: nothing in the report separates map
   layout from wave tuning.
2. **The difficulty curve's shape.** Name the specific spike rounds and slack
   stretches from section 3, and quote the mortality and breaches/run behind
   each. Cross the spikes against section 7 — a spike on a boss round with a
   lopsided A/B win rate is a *choice* problem, not a wave problem.
3. **The economy.** Is love a constraint or has it stopped mattering? Watch
   `love end` climbing while `spent` stays flat: that is players hoarding
   because nothing is worth buying. Quote the session-wide income-lost-to-dead-
   buildings share — it is a difficulty multiplier that never appears in a
   wave table.
4. **Dead content.** Building types in <25% of runs, level-up options never
   taken, research never bought. Each is either unaffordable, unavailable, or
   unreadable, and the report cannot tell you which — say so and propose the
   check.
5. **Form vs telemetry gaps.** The two cross-check tables at the end are the
   highest-value rows in the file: where players' memory disagrees with the
   recorder, the *feeling* is the bug.
6. **Confidence.** Rounds marked `~` are anecdote. Never build a balance
   recommendation on them without labelling it.

Finish with a short **ranked list of balance changes to consider**, each naming
the round or system it targets and, where you can find it, the `data/balancing/`
knob that controls it. Tag the whole list as inferred.

## Step 5 — Verify

```bash
py -m pytest tools/tests/test_qa_triage.py -q   # ingest rules + both renderers
```

Report: session analysed, runs in vs runs out, exclusions, where the markdown
and HTML landed, and the top three findings. Do **not** paste the report body
into chat — point at the files and summarise.

## Notes

- Three modules, one job each: `tools/qa_triage.py` (ingest + markdown + CLI),
  `tools/qa_triage_charts.py` (SVG/CSS primitives), `tools/qa_triage_html.py`
  (page assembly). All stdlib-only by design, matching `game/debug/report.py`.
  Keep it that way; no pandas, no chart library.
- The too-hard/too-easy thresholds live in one place — `classify_rounds()` and
  `THRESHOLDS` in `qa_triage.py` — so the markdown and the HTML can never
  disagree about which round is a spike.
- Chart rules are not decoration: one y-axis per chart (never dual-axis),
  categorical colours assigned in fixed order and never cycled, a table view
  behind every chart. If you add a chart, follow the ones already there.
- `leaks` and `lives_lost` are the same number in every record. The report
  collapses them into one **breaches** metric — do not reintroduce both.
- Round numbering is normalised: runs whose first `round_summary` is round 0
  are shifted by one so every run's first played round is round 1.
- New session, new folder under `QATestingOutputs/`. The tool takes the session
  dir as an argument precisely so late-arriving machines just drop a folder in
  and get re-run.
