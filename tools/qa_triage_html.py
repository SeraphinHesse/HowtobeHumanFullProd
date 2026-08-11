"""Assemble the playtest triage report as ONE self-contained HTML page.

Chart primitives live in ``qa_triage_charts``; this module decides what the
report says and in what order. Every argument arrives already computed, so
nothing here reaches back into ``qa_triage`` (no import cycle).
"""

from __future__ import annotations

import collections
import statistics

from tools.qa_triage_charts import (
    CSS, SERIES, TIP_JS, bars, esc, hbars, lines, stacked_bars, table, tile, _fmt,
)


def _med(vals):
    vals = list(vals)
    return statistics.median(vals) if vals else 0.0


def _pct(part, whole):
    return 100.0 * part / whole if whole else 0.0


def _pcts(part, whole):
    return f"{_pct(part, whole):.0f}%" if whole else "—"


# ---------------------------------------------------------------------------


def _header(runs, reached, pooled, hard_rounds, session_name, total):
    minutes = sum(r.duration_min for r in runs)
    players = len({r.player.lower() for r in runs})
    lens = [len(r.rounds) for r in runs]
    inc_a = sum(row.get("income_actual", 0) for recs in pooled.values() for row in recs)
    inc_p = sum(row.get("income_potential", 0) for recs in pooled.values() for row in recs)
    worst = max(hard_rounds, key=lambda h: h[1])[0] if hard_rounds else None

    out = [
        f"<h1>Playtest triage — {esc(session_name)}</h1>",
        f'<p class="sub">{total} runs pooled across '
        f'{len({r.host for r in runs})} machines · every number is measured from the '
        "debug recorder, except the flagged verdicts under “Too hard, too easy”.</p>",
        '<div class="tiles">',
    ]
    if worst:
        out.append(tile("Hardest round", f"r{worst}", hero=True,
                        note="highest breach rate of any well-sampled round"))
    out += [
        tile("Runs analysed", total, note=f"{players} distinct player names"),
        tile("Play recorded", f"{minutes:.0f} min",
             note=f"median {_med([r.duration_min for r in runs]):.1f} min per run"),
        tile("Median run", f"{_med(lens):.0f} rounds", note=f"longest was {max(lens)}"),
        tile("Reached round 10", _pcts(reached.get(10, 0), total),
             note=f"{reached.get(10, 0)} of {total} runs"),
        tile("Love never paid", _pcts(inc_p - inc_a, inc_p),
             note=f"{inc_p - inc_a} of {inc_p} lost to dead buildings"),
        "</div>",
    ]
    return out


def _md_bold(s: str) -> str:
    """The caveat strings are shared with the markdown report; honour its **bold**."""
    parts = esc(s).split("**")
    return "".join(p if i % 2 == 0 else f"<b>{p}</b>" for i, p in enumerate(parts))


def _cohort(runs, excluded, notes, caveats):
    hosts = collections.Counter(r.host for r in runs)
    skills = collections.Counter(r.skill for r in runs)
    outcomes = collections.Counter(r.outcome for r in runs)
    maps = collections.Counter(r.map_id for r in runs)
    out = ["<h2>Cohort</h2>", table(["dimension", "breakdown"], [
        ["machine", ", ".join(f"{k} {v}" for k, v in hosts.most_common())],
        ["self-reported skill", ", ".join(f"{k} {v}" for k, v in skills.most_common())],
        ["outcome", ", ".join(f"{k} {v}" for k, v in outcomes.most_common())],
        ["map", ", ".join(f"{k} {v}" for k, v in maps.most_common())],
    ])]
    if excluded:
        out.append("<h3>Excluded from every number below</h3>")
        out.append(table(["reason", "runs"], sorted(excluded.items())))
    for caveat in caveats:
        out.append(f'<p class="note">{_md_bold(caveat)}</p>')
    if len(maps) == 1:
        out.append(f'<p class="note">Every run is on <code>{esc(list(maps)[0])}</code>. '
                   "Map is not a variable in this session, so nothing in this report "
                   "separates map layout from wave tuning.</p>")
    out += [f'<p class="note">ingest note: {esc(n)}</p>' for n in notes]
    return out


def _difficulty(pooled, reached, died, quit_, total, thresholds):
    rounds = sorted(pooled)
    labels = [str(r) for r in rounds]
    n_at = {r: len(pooled[r]) for r in rounds}
    sums = lambda r, k: sum(row.get(k, 0) for row in pooled[r])  # noqa: E731

    out = [
        "<h2>Difficulty curve</h2>",
        '<p class="lede">Four views of one question: how hard is each round, and how '
        "many people are still there to find out. They are four charts rather than one "
        "overlaid chart because they are measured in different units — a share of runs, "
        "a share of deaths, a count of breaches, and a kill rate. Late rounds rest on a "
        "handful of runs; the run count is in every table.</p>",
    ]

    surv = [_pct(reached.get(r, 0), total) for r in rounds]
    out.append(lines(
        "Survival — share of all runs still playing",
        "Falls monotonically by construction: every step down is a run that ended at "
        "that round. The steepest segment is where the game sheds the most players.",
        labels, [("still playing", surv)],
        [f"Round {r}<br>{reached.get(r, 0)} of {total} runs still playing "
         f"({_pcts(reached.get(r, 0), total)})" for r in rounds],
        y_suffix="%", area=True,
        table_html=table(["round", "runs reaching", "share of all runs"],
                         [[r, reached.get(r, 0), _pcts(reached.get(r, 0), total)]
                          for r in rounds])))

    mort = [_pct(died.get(r, 0), reached.get(r, 0)) for r in rounds]
    out.append(bars(
        "Mortality — your chance of dying, given that you got this far",
        "Deaths at a round over the runs that reached it. This is the honest "
        "difficulty measure: raw death counts fall off late only because almost "
        f"nobody is left to die. Bars in red clear the {thresholds['mortality']:.0%} flag.",
        labels, mort,
        [f"Round {r}<br>{died.get(r, 0)} of {reached.get(r, 0)} runs ended here "
         f"({_pcts(died.get(r, 0), reached.get(r, 0))})" for r in rounds],
        y_suffix="%",
        colors=["var(--crit)" if m >= thresholds["mortality"] * 100 else SERIES[0]
                for m in mort],
        table_html=table(["round", "reached", "died", "quit", "mortality"],
                         [[r, reached.get(r, 0), died.get(r, 0), quit_.get(r, 0),
                           _pcts(died.get(r, 0), reached.get(r, 0))] for r in rounds])))

    br = [sums(r, "leaks") / n_at[r] for r in rounds]
    out.append(bars(
        "Breaches per run — lives actually lost",
        "A breach costs exactly one life; the recorder's leaks and lives_lost are the "
        "same number in every record, so they are one metric here. Shown as a rate, "
        "not a median: breaches are lumpy, and the median is zero at almost every "
        "round, which hides the entire signal.",
        labels, br,
        [f"Round {r}<br>{sums(r, 'leaks')} breaches over {n_at[r]} runs "
         f"({br[i]:.2f} per run)" for i, r in enumerate(rounds)],
        colors=["var(--crit)" if v >= thresholds["breach"] else SERIES[0] for v in br],
        table_html=table(["round", "runs", "breaches", "per run", "kidnaps/run"],
                         [[r, n_at[r], sums(r, "leaks"), f"{br[i]:.2f}",
                           f"{sums(r, 'kidnaps') / n_at[r]:.1f}"]
                          for i, r in enumerate(rounds)])))

    killp = [_pct(sums(r, "kills"), sums(r, "enemies_spawned")) for r in rounds]
    out.append(lines(
        "Kill rate — share of the wave that died",
        "Kills over enemies spawned. It can exceed 100%: a wave's survivors are "
        "killed during the next round and counted there, so a spike over the line "
        "means the previous wave overran its round.",
        labels, [("kill rate", killp)],
        [f"Round {r}<br>{sums(r, 'kills')} killed of {sums(r, 'enemies_spawned')} "
         f"spawned ({killp[i]:.0f}%)" for i, r in enumerate(rounds)],
        y_suffix="%",
        table_html=table(["round", "median wave", "spawned", "killed", "kill rate"],
                         [[r, _fmt(_med(row.get("wave_size", 0) for row in pooled[r])),
                           sums(r, "enemies_spawned"), sums(r, "kills"),
                           f"{killp[i]:.0f}%"] for i, r in enumerate(rounds)])))
    return out


def _verdict(hard_rounds, easy_rounds, thresholds):
    out = [
        "<h2>Too hard, too easy</h2>",
        f'<p class="lede"><b>Inferred, not measured.</b> Fixed thresholds — too hard is '
        f'≥{thresholds["breach"]} breaches/run <b>or</b> ≥{thresholds["mortality"]:.0%} '
        f'mortality; too easy is ≤{thresholds["easy_breach"]} breaches/run <b>and</b> '
        f'nobody dying. Rounds seen by fewer than {thresholds["min_n"]} runs are skipped '
        "entirely — they are anecdote, not signal. Treat these as places to look.</p>",
    ]
    if hard_rounds:
        out.append(table(["round", "breaches/run", "mortality", "verdict"],
                         [[r, f"{b:.2f}", f"{m:.0%}",
                           '<span class="badge hard">too hard</span>']
                          for r, b, m in hard_rounds]))
    else:
        out.append("<p>No round crossed the too-hard thresholds.</p>")
    if easy_rounds:
        out.append(table(["round", "verdict"],
                         [[r, '<span class="badge easy">too easy</span>']
                          for r in easy_rounds]))
    else:
        out.append("<p>No round crossed the too-easy thresholds.</p>")
    return out


def _economy(pooled):
    rounds = sorted(pooled)
    labels = [str(r) for r in rounds]
    n_at = {r: len(pooled[r]) for r in rounds}
    med_of = lambda k: [_med(row.get(k, 0) for row in pooled[r]) for r in rounds]  # noqa: E731
    sum_of = lambda k: [sum(row.get(k, 0) for row in pooled[r]) for r in rounds]  # noqa: E731

    series = [("income", med_of("income_actual")),
              ("spent on buildings", med_of("love_spent_buildings")),
              ("wallet at round end", med_of("love_end"))]
    out = [
        "<h2>Economy</h2>",
        '<p class="lede">All three series are love, so they share one axis. The shape to '
        "look for: income and wallet climbing together while spend stays flat means "
        "players are hoarding — either nothing is worth buying, or they cannot tell "
        "what is.</p>",
        lines(
            "Income, spend and wallet (medians)",
            "Median across every run that played the round, so a late round's point is "
            "drawn from the few players who got there.",
            labels, series,
            [[f"Round {r}<br>{name}: {_fmt(vals[i])} love<br>{n_at[r]} runs"
              for i, r in enumerate(rounds)] for name, vals in series],
            table_html=table(
                ["round", "runs", "love start", "income", "upkeep", "spent", "love end"],
                [[r, n_at[r], _fmt(med_of("love_start")[i]), _fmt(med_of("income_actual")[i]),
                  _fmt(med_of("upkeep_actual")[i]),
                  _fmt(med_of("love_spent_buildings")[i]), _fmt(med_of("love_end")[i])]
                 for i, r in enumerate(rounds)])),
    ]

    lost = sum_of("income_lost_to_damage")
    out.append(bars(
        "Income lost because the building was dead at payday",
        "Payday skips a building that is not alive, so losing one costs its next payout "
        "as well. This is a difficulty multiplier that never appears in a wave table — "
        "where it spikes, a hard round is quietly getting harder.",
        labels, lost,
        [f"Round {r}<br>{lost[i]:.0f} love never paid out<br>{n_at[r]} runs"
         for i, r in enumerate(rounds)],
        table_html=table(["round", "income actual", "income potential", "lost"],
                         [[r, sum_of("income_actual")[i], sum_of("income_potential")[i],
                           lost[i]] for i, r in enumerate(rounds)])))
    return out


def _pacing(runs, pooled):
    rounds = sorted(pooled)
    build: dict[int, list[float]] = collections.defaultdict(list)
    wave: dict[int, list[float]] = collections.defaultdict(list)
    for run in runs:
        prev = 0.0
        waves = run.events_of("wave_start")
        for row in run.rounds:
            end = row.get("wall_ms", 0)
            if end <= prev:
                prev = end
                continue
            spawn = next((e["wall_ms"] for e in waves
                          if prev < e.get("wall_ms", 0) <= end), None)
            if spawn:
                build[row["round"]].append((spawn - prev) / 1000.0)
                wave[row["round"]].append((end - spawn) / 1000.0)
            else:
                wave[row["round"]].append((end - prev) / 1000.0)
            prev = end
    rounds = [r for r in rounds if wave.get(r)]
    if not rounds:
        return []
    labels = [str(r) for r in rounds]
    b = [_med(build.get(r, [0])) for r in rounds]
    w = [_med(wave.get(r, [0])) for r in rounds]
    return [
        "<h2>Pacing</h2>",
        '<p class="lede">Median wall-clock seconds per round, split at the moment the '
        "wave spawns. A build phase of a few seconds means players are committing "
        "without deliberating — either they have nothing to decide, or the UI is "
        "rushing them.</p>",
        stacked_bars(
            "Seconds per round, build phase vs wave",
            "Both segments are seconds, so they stack legitimately. The 2px gap between "
            "them is surface colour, not a stroke.",
            labels, [("build phase", b), ("wave", w)],
            [f"Round {r}<br>build {b[i]:.0f}s · wave {w[i]:.0f}s<br>"
             f"total {b[i] + w[i]:.0f}s over {len(wave.get(r, []))} runs"
             for i, r in enumerate(rounds)],
            y_suffix="s",
            table_html=table(["round", "runs", "build s", "wave s", "total s"],
                             [[r, len(wave.get(r, [])), f"{b[i]:.0f}", f"{w[i]:.0f}",
                               f"{b[i] + w[i]:.0f}"] for i, r in enumerate(rounds)])),
    ]


def _buildings(runs):
    placed = collections.Counter()
    runs_with = collections.Counter()
    first: dict[str, list[int]] = collections.defaultdict(list)
    spend = collections.Counter()
    opener = collections.Counter()
    for run in runs:
        seen: dict[str, int] = {}
        evs = run.events_of("place")
        if evs:
            opener[evs[0].get("building_type", "?")] += 1
        for ev in evs:
            bt = ev.get("building_type", "?")
            placed[bt] += 1
            spend[bt] += ev.get("cost", 0)
            seen.setdefault(bt, ev.get("round", 0))
        for bt, rnd in seen.items():
            runs_with[bt] += 1
            first[bt].append(rnd)
    if not placed:
        return []
    total = len(runs)
    ranked = sorted(runs_with.items(), key=lambda kv: -kv[1])
    rows = [(bt, _pct(n, total),
             f"{bt}<br>{n} of {total} runs ({_pcts(n, total)})<br>"
             f"{placed[bt]} placements · first seen round {_fmt(_med(first[bt]))}")
            for bt, n in ranked]
    colours = {bt: (SERIES[0] if v >= 50 else "var(--muted)") for bt, v in
               ((bt, _pct(n, total)) for bt, n in ranked)}
    return [
        "<h2>Building meta</h2>",
        '<p class="lede">Share of runs a type appears in at all — the number that says '
        "whether it is a choice. A type in nearly every run is a requirement, not a "
        "decision; a type in almost none is unaffordable, unavailable, or unreadable, "
        "and this report cannot tell you which. Greyed bars sit under half the runs.</p>",
        hbars("Adoption — share of runs that placed this type at least once",
              "Ranked by adoption. Placement counts and first-seen rounds are in the table.",
              rows, colors=colours,
              table_html=table(
                  ["building", "placements", "runs", "% of runs", "median first round",
                   "love spent"],
                  [[bt, placed[bt], n, _pcts(n, total), _fmt(_med(first[bt])), spend[bt]]
                   for bt, n in ranked])),
        '<p class="note">Opening placement: ' +
        ", ".join(f"<b>{esc(k)}</b> {_pcts(v, total)}" for k, v in opener.most_common()) +
        ".</p>",
    ]


def _enemies(runs):
    killed, spawned, kidnaps, took = (collections.Counter() for _ in range(4))
    base_hits = collections.Counter()
    for run in runs:
        for ev in run.events_of("enemy_death"):
            killed[ev.get("etype", "?")] += 1
        for ev in run.events_of("wave_start"):
            for etype, n in (ev.get("composition") or {}).items():
                spawned[etype] += n
        for ev in run.events_of("kidnap"):
            kidnaps[ev.get("etype", "?")] += 1
            took[ev.get("building_type", "?")] += 1
        for ev in run.events_of("base_hit"):
            base_hits[ev.get("etype", "?")] += 1
    if not spawned:
        return []
    ranked = sorted(spawned.items(), key=lambda kv: -kv[1])
    rows = [(et, _pct(killed.get(et, 0), n),
             f"{et}<br>{killed.get(et, 0)} killed of {n} spawned "
             f"({_pcts(killed.get(et, 0), n)})<br>{base_hits.get(et, 0)} reached the base")
            for et, n in ranked]
    return [
        "<h2>Enemies</h2>",
        '<p class="lede">Kill rate per type across the whole session. The type players '
        "kill least often relative to how often they meet it is the one actually "
        "applying the pressure.</p>",
        hbars("Kill rate by enemy type", "Ranked by how many of each were spawned.",
              rows,
              table_html=table(["enemy", "spawned", "killed", "kill rate",
                                "reached base", "kidnaps"],
                               [[et, n, killed.get(et, 0), _pcts(killed.get(et, 0), n),
                                 base_hits.get(et, 0), kidnaps.get(et, 0)]
                                for et, n in ranked])),
        ('<p class="note">Buildings kidnapped, by type: ' +
         ", ".join(f"<b>{esc(k)}</b> ×{v}" for k, v in took.most_common()) + ".</p>")
        if took else "",
    ]


def _progression(runs):
    levelup, unlock, research, boss = (collections.Counter() for _ in range(4))
    for run in runs:
        for ev in run.events_of("levelup"):
            levelup[ev.get("option", "?")] += 1
        for ev in run.events_of("unlock"):
            unlock[ev.get("building_type", "?")] += 1
        for ev in run.events_of("research"):
            research[f"{ev.get('building_type', '?')} T{ev.get('tier', '?')}"] += 1
        for ev in run.events_of("boss_choice"):
            boss[(ev.get("boss_num"), ev.get("option"), ev.get("outcome"))] += 1
    if not (levelup or unlock or boss):
        return []
    out = ["<h2>Progression choices</h2>",
           '<p class="lede">What players pick when the game offers them a choice. An '
           "option nobody takes is either strictly worse or badly explained — both are "
           "balance problems, and neither shows up in a difficulty curve.</p>"]
    tot = sum(levelup.values())
    if tot:
        out.append(hbars(
            "Level-up option taken",
            "Every level-up is a fork. If one arm takes nearly all of them, it is not "
            "a fork.",
            [(k, _pct(v, tot), f"{k}<br>{v} of {tot} level-ups ({_pcts(v, tot)})")
             for k, v in levelup.most_common()],
            table_html=table(["option", "times", "share"],
                             [[k, v, _pcts(v, tot)] for k, v in levelup.most_common()])))
    tot_u = sum(unlock.values())
    if tot_u:
        out.append(hbars(
            "Buildings unlocked",
            "Which unlock players spend a level on. Compare against the adoption chart "
            "above: a type unlocked often but placed rarely was a disappointment.",
            [(k, _pct(v, tot_u), f"{k}<br>unlocked {v} times ({_pcts(v, tot_u)} of unlocks)")
             for k, v in unlock.most_common()],
            table_html=table(["building", "times", "share of unlocks"],
                             [[k, v, _pcts(v, tot_u)] for k, v in unlock.most_common()])))
    if research:
        out.append("<h3>Research purchased</h3>")
        out.append(table(["research", "times"], research.most_common()))
    if boss:
        by_choice, wins = collections.Counter(), collections.Counter()
        for (num, opt, outcome), n in boss.items():
            by_choice[(num, opt)] += n
            if outcome == "win":
                wins[(num, opt)] += n
        out.append("<h3>Boss encounters</h3>")
        out.append('<p>Win rate per choice — a fork where one arm is taken by almost '
                   "everyone and loses almost every time is the sharpest balance signal "
                   "in the report.</p>")
        out.append(table(["boss", "choice", "taken", "won", "win rate"],
                         [[f"boss {num}", f"option {opt}", n, wins[(num, opt)],
                           _pcts(wins[(num, opt)], n)]
                          for (num, opt), n in sorted(by_choice.items())]))
    return out


def _skill_split(runs):
    by_skill: dict[str, list] = collections.defaultdict(list)
    for run in runs:
        by_skill[run.skill].append(run)
    if len(by_skill) < 2:
        return []
    ordered = sorted(by_skill.items(), key=lambda kv: -len(kv[1]))
    # Categorical slots are assigned in fixed order and never cycled: past three
    # buckets the chart folds to the three largest and the table carries the rest.
    charted = ordered[:3]
    max_round = max((len(r.rounds) for r in runs), default=0)
    rounds = list(range(1, max_round + 1))
    labels = [str(r) for r in rounds]
    series, tips = [], []
    for skill, group in charted:
        vals = [_pct(sum(1 for g in group if len(g.rounds) >= r), len(group)) for r in rounds]
        series.append((f"{skill} (n={len(group)})", vals))
        tips.append([f"{skill} · round {r}<br>"
                     f"{sum(1 for g in group if len(g.rounds) >= r)} of {len(group)} "
                     f"still playing ({vals[i]:.0f}%)" for i, r in enumerate(rounds)])
    out = [
        "<h2>By self-reported skill</h2>",
        '<p class="lede">The same players, split by the skill box they ticked. Where the '
        "curves separate is where experience starts to matter; where they overlap, a "
        "wall is hitting everyone equally and is a tuning problem rather than a "
        "teaching one. Small buckets are anecdote — the n is in the legend.</p>",
        lines("Survival by skill bucket",
              "Share of each bucket still playing at each round, so buckets of different "
              "size are comparable.",
              labels, series, tips, y_suffix="%",
              table_html=table(
                  ["skill", "runs", "median rounds", "best", "breaches/round", "median min"],
                  [[skill, len(g), _fmt(_med([len(r.rounds) for r in g])),
                    max(len(r.rounds) for r in g),
                    f"{sum(row.get('leaks', 0) for r in g for row in r.rounds) / max(1, sum(len(r.rounds) for r in g)):.2f}",
                    f"{_med([r.duration_min for r in g]):.1f}"]
                   for skill, g in ordered])),
    ]
    if len(ordered) > 3:
        out.append('<p class="note">Only the three largest buckets are plotted — '
                   "categorical colours are assigned in a fixed order and never cycled. "
                   "Every bucket is in the table.</p>")
    return out


def _form(form_rows, runs):
    if not form_rows:
        return []
    fields = [f for f in form_rows[0].keys() if f and f.lower() != "timestamp"]
    out = ["<h2>Player questionnaire</h2>",
           f'<p class="lede"><b>{len(form_rows)} responses.</b> The form is anonymous, so '
           "it cannot be joined to individual runs — it is a separate sample over the "
           "same session. The two cross-checks at the end are the highest-value rows in "
           "this report: where memory disagrees with the recorder, the feeling is the "
           "bug.</p>"]
    for field in fields:
        answers = [(r.get(field) or "").strip() for r in form_rows]
        answers = [a for a in answers if a]
        if not answers:
            continue
        out.append(f"<h3>{esc(field)}</h3>")
        if statistics.mean(len(a) for a in answers) > 40:
            out.append("<ul>" + "".join(
                f"<li>{esc(a).replace(chr(10), ' / ')}</li>" for a in answers) + "</ul>")
        else:
            counts = collections.Counter(answers)
            out.append(table(["answer", "n", "share"],
                             [[k, v, _pcts(v, len(answers))] for k, v in counts.most_common()]))

    def claimed(field, pick):
        vals = []
        for r in form_rows:
            nums = [int(d) for d in
                    "".join(c if c.isdigit() else " " for c in (r.get(field) or "")).split()]
            if nums:
                vals.append(pick(nums))
        return vals

    far = next((f for f in fields if "how far" in f.lower()), None)
    if far:
        c = claimed(far, max)
        best: dict[str, int] = {}
        for run in runs:
            best[run.player.lower()] = max(best.get(run.player.lower(), 0), len(run.rounds))
        if c and best:
            out.append("<h3>Cross-check — furthest round reached</h3>")
            out.append(table(["source", "n", "median", "max"], [
                ["self-reported on the form", len(c), _fmt(_med(c)), max(c)],
                ["measured, per run", len(runs), _fmt(_med([len(r.rounds) for r in runs])),
                 max(len(r.rounds) for r in runs)],
                ["measured, best run per player name", len(best),
                 _fmt(_med(best.values())), max(best.values())],
            ]))
            out.append('<p class="note">Players report their <i>best</i> run; the '
                       "per-run median covers every run including the short ones — "
                       "compare the form against the best-run row. If the question was a "
                       "bucketed dropdown, its resolution is the bucket width.</p>")

    life = next((f for f in fields
                 if "first live" in f.lower() or "first life" in f.lower()), None)
    if life:
        c = claimed(life, min)
        measured = [nxt for nxt in
                    (next((row["round"] for row in run.rounds if row.get("leaks", 0) > 0), None)
                     for run in runs) if nxt]
        if c and measured:
            out.append("<h3>Cross-check — round of the first life lost</h3>")
            out.append(table(["source", "n", "median", "earliest", "latest"], [
                ["self-reported on the form", len(c), _fmt(_med(c)), min(c), max(c)],
                ["measured", len(measured), _fmt(_med(measured)), min(measured), max(measured)],
            ]))
            out.append(f'<p class="note">{len(runs) - len(measured)} of {len(runs)} runs '
                       "never lost a life at all and are absent from the measured row. A "
                       "self-reported figure <i>earlier</i> than the measured one means "
                       "the first breach felt worse than it was — a feedback problem "
                       "rather than a tuning one.</p>")
    return out


# ---------------------------------------------------------------------------


def write_html(path, *, session_name, runs, pooled, reached, died, quit_, excluded,
               notes, form_rows, hard_rounds, easy_rounds, thresholds, caveats=()):
    """Render the whole report into ONE self-contained file at ``path``."""
    total = len(runs)
    body: list[str] = []
    body += _header(runs, reached, pooled, hard_rounds, session_name, total)
    body += _cohort(runs, excluded, notes, caveats)
    body += _difficulty(pooled, reached, died, quit_, total, thresholds)
    body += _verdict(hard_rounds, easy_rounds, thresholds)
    body += _economy(pooled)
    body += _pacing(runs, pooled)
    body += _buildings(runs)
    body += _enemies(runs)
    body += _progression(runs)
    body += _skill_split(runs)
    body += _form(form_rows, runs)

    doc = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Playtest triage — {esc(session_name)}</title>"
        f"<style>{CSS}</style></head>"
        f'<body class="viz-root"><div class="wrap">{"".join(body)}</div>'
        '<div id="tip"></div>'
        f"<script>{TIP_JS}</script></body></html>"
    )
    path.write_text(doc, encoding="utf-8")
    return path
