"""Coalesce a multi-machine QA playtest session into one balance report.

A playtest session is a directory of per-host folders, each holding the debug
recorder's output for every run on that machine:

    QATestingOutputs/06.08.26/
        logs, joel/      run-<ts>-<name>-<skill>-events.jsonl   (+ -rounds.csv,
        logs, pantelis/                                          -summary.md,
        logs, seraphin/                                          -report.html)

The per-run `-summary.md` files answer "what happened in THIS run". This tool
answers "what is the game doing to PLAYERS" by pooling every run at the
*round* level and reporting medians with sample sizes, never averages of
averages.

Usage:
    py tools/qa_triage.py QATestingOutputs/06.08.26
    py tools/qa_triage.py QATestingOutputs/06.08.26 --form "path/to/form.csv"
    py tools/qa_triage.py QATestingOutputs/06.08.26 --skill never
    py tools/qa_triage.py QATestingOutputs/06.08.26 --out report.md

Stdlib only, to match game/debug/report.py.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import os
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# ---------------------------------------------------------------------------
# Tunables for the "too hard / too easy" verdict. These are report heuristics,
# not game balance values, so they live here rather than in data/balancing/.
# ---------------------------------------------------------------------------

MIN_N_FOR_CONFIDENCE = 8  # rounds seen by fewer runs than this are low-confidence
HARD_BREACH_RATE = 0.40   # breaches per run at a round -> "too hard" candidate
EASY_BREACH_RATE = 0.05   # ...and below this with full lives -> "too easy"
HARD_MORTALITY = 0.20     # share of runs *reaching* a round that die on it

# Runs shorter than this are menu bounces / restarts, not play sessions.
DEFAULT_MIN_ROUNDS = 3

# Self-reported skill buckets that are developers, not players.
DEV_SKILLS = {"developer"}


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


class Run:
    """One recorded run, parsed from its events.jsonl."""

    def __init__(self, path: Path, host: str, events: list[dict]):
        self.path = path
        self.host = host
        self.events = events
        start = events[0] if events else {}
        self.run_id = start.get("run_id") or path.stem
        self.player = (start.get("player_name") or "").strip() or "(anon)"
        self.skill = start.get("player_skill") or "(unset)"
        self.map_id = start.get("map_id") or "(unknown)"

        self.rounds = self._normalised_rounds()
        self.cheated = any(e["t"] == "cheat" for e in events) or any(
            r.get("cheated") for r in self.rounds
        )

        end = [e for e in events if e["t"] == "run_end"]
        self.outcome = end[0].get("outcome") if end else "no_end_event"
        # A run that ends in game_over died ON the round after its last summary.
        self.died = self.outcome == "game_over"
        self.last_round = self.rounds[-1]["round"] if self.rounds else 0
        self.death_round = self.last_round + 1 if self.died else None
        self.duration_min = max((e.get("wall_ms", 0) for e in events), default=0) / 60000.0

    def _normalised_rounds(self) -> list[dict]:
        """Round-summary rows, re-indexed so the first played round is round 1.

        Some runs record their first summary as round 0 (the tutorial round is
        emitted before the counter increments). Left raw, those runs would
        stack their round-1 data onto everyone else's round 0 and shift the
        whole curve by one.
        """
        rows = [dict(e) for e in self.events if e["t"] == "round_summary"]
        if not rows:
            return []
        shift = 1 if min(r.get("round", 0) for r in rows) == 0 else 0
        for r in rows:
            r["round"] = r.get("round", 0) + shift
        rows.sort(key=lambda r: r["round"])
        return rows

    def events_of(self, kind: str) -> list[dict]:
        return [e for e in self.events if e["t"] == kind]


def load_session(session_dir: Path) -> tuple[list[Run], list[str]]:
    """Load every run under session_dir, de-duplicated by run_id.

    The same run is often copied into more than one host folder. Identical
    copies are dropped silently; copies that share a run_id but differ in
    content are reported as a collision, because that means two machines
    generated the same id and only one of them can be trusted.
    """
    runs: dict[str, Run] = {}
    digests: dict[str, str] = {}
    notes: list[str] = []

    for path in sorted(session_dir.glob("*/*-events.jsonl")):
        host = path.parent.name
        for prefix in ("logs, ", "logs-", "logs_"):
            if host.lower().startswith(prefix):
                host = host[len(prefix):]
                break
        raw = path.read_bytes()
        try:
            events = [json.loads(ln) for ln in raw.decode("utf-8").splitlines() if ln.strip()]
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            notes.append(f"unreadable, skipped: {path.name} ({exc})")
            continue
        if not events:
            notes.append(f"empty, skipped: {path.name}")
            continue

        run = Run(path, host, events)
        digest = hashlib.md5(raw).hexdigest()
        if run.run_id in runs:
            if digests[run.run_id] == digest:
                continue  # exact copy on another machine
            notes.append(
                f"run_id COLLISION with differing content: {run.run_id} "
                f"({runs[run.run_id].host} vs {run.host}) — kept the first"
            )
            continue
        runs[run.run_id] = run
        digests[run.run_id] = digest

    return sorted(runs.values(), key=lambda r: r.run_id), notes


def apply_filters(runs: list[Run], args) -> tuple[list[Run], dict[str, int]]:
    """Split the pool into analysed runs plus a census of what was excluded."""
    excluded: dict[str, int] = collections.Counter()
    kept: list[Run] = []
    for run in runs:
        if not args.include_devs and run.skill in DEV_SKILLS:
            excluded["developer runs"] += 1
            continue
        if not args.include_cheats and run.cheated:
            excluded["runs with cheats used"] += 1
            continue
        if args.skill and run.skill not in args.skill:
            excluded[f"skill not in {'/'.join(args.skill)}"] += 1
            continue
        if args.outcome and run.outcome not in args.outcome:
            excluded[f"outcome not in {'/'.join(args.outcome)}"] += 1
            continue
        if len(run.rounds) < args.min_rounds:
            excluded[f"abandoned (<{args.min_rounds} rounds played)"] += 1
            continue
        kept.append(run)
    return kept, dict(excluded)


# ---------------------------------------------------------------------------
# Small stats helpers
# ---------------------------------------------------------------------------


def caveats_for(args) -> list[str]:
    """Warnings that a filter changed what a column means, not just the sample."""
    out = []
    if args.outcome and set(args.outcome) == {"game_over"}:
        out.append(
            "Only runs that ended in **game over** are counted — every run the "
            "player walked away from is excluded. That makes the survival curve a "
            "pure death curve and mortality the share of *these* runs that ended at "
            "each round, so the two now sum to the whole cohort. It also means the "
            "cohort is biased toward players who kept going: someone who quit in "
            "frustration at round 4 is not in here, so early rounds will look easier "
            "than they were."
        )
    elif args.outcome:
        out.append("Filtered to outcomes: " + ", ".join(f"`{o}`" for o in args.outcome) +
                   ". The survival and mortality curves describe only these runs.")
    return out


def med(values) -> float:
    values = list(values)
    return statistics.median(values) if values else 0.0


def iqr(values) -> tuple[float, float]:
    values = sorted(values)
    if len(values) < 4:
        return (values[0], values[-1]) if values else (0.0, 0.0)
    q = statistics.quantiles(values, n=4)
    return q[0], q[2]


def pct(part: float, whole: float) -> str:
    return f"{100.0 * part / whole:.0f}%" if whole else "—"


def fmt(x: float) -> str:
    return f"{x:.0f}" if float(x).is_integer() else f"{x:.1f}"


def table(headers: list[str], rows: list[list], aligns: str = "") -> list[str]:
    aligns = aligns or "l" * len(headers)
    sep = {"l": "---", "r": "---:", "c": ":---:"}
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(sep[a] for a in aligns) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return out


# ---------------------------------------------------------------------------
# Round-level pooling
# ---------------------------------------------------------------------------


def pool_rounds(runs: list[Run]) -> dict[int, list[dict]]:
    """All round records from all runs, keyed by round number."""
    pooled: dict[int, list[dict]] = collections.defaultdict(list)
    for run in runs:
        for row in run.rounds:
            pooled[row["round"]].append(row)
    return dict(sorted(pooled.items()))


def reach_counts(runs: list[Run]) -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
    """How many runs reached / died on / quit on each round."""
    reached: dict[int, int] = collections.Counter()
    died: dict[int, int] = collections.Counter()
    quit_: dict[int, int] = collections.Counter()
    for run in runs:
        for r in range(1, run.last_round + 1):
            reached[r] += 1
        stop = run.last_round + 1
        reached[stop] += 1  # they entered the round they died/quit on
        (died if run.died else quit_)[stop] += 1
    return dict(reached), dict(died), dict(quit_)


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------


def section_cohort(runs: list[Run], excluded: dict, notes: list[str], args) -> list[str]:
    out = ["## 1. Cohort", ""]
    hosts = collections.Counter(r.host for r in runs)
    skills = collections.Counter(r.skill for r in runs)
    outcomes = collections.Counter(r.outcome for r in runs)
    maps = collections.Counter(r.map_id for r in runs)
    players = {r.player.lower() for r in runs}
    lengths = [len(r.rounds) for r in runs]
    mins = [r.duration_min for r in runs]

    out += [
        f"**{len(runs)} runs analysed** from {len(hosts)} machines, "
        f"~{len(players)} distinct player names, {sum(mins):.0f} minutes of play.",
        "",
    ]
    out += table(
        ["dimension", "breakdown"],
        [
            ["machine", ", ".join(f"{k} {v}" for k, v in hosts.most_common())],
            ["self-reported skill", ", ".join(f"{k} {v}" for k, v in skills.most_common())],
            ["outcome", ", ".join(f"{k} {v}" for k, v in outcomes.most_common())],
            ["map", ", ".join(f"{k} {v}" for k, v in maps.most_common())],
            ["rounds survived", f"median {med(lengths):.0f}, range {min(lengths)}–{max(lengths)}"],
            ["session length", f"median {med(mins):.1f} min, longest {max(mins):.1f} min"],
        ],
    )
    out.append("")
    if excluded:
        out += ["**Excluded from every number below:**", ""]
        out += table(["reason", "runs"], [[k, v] for k, v in sorted(excluded.items())], "lr")
        out.append("")
    for caveat in caveats_for(args):
        out += [f"> {caveat}", ""]
    if len(maps) == 1:
        out += [
            f"> Every run is on `{list(maps)[0]}`. Map is not a variable in this "
            "session, so nothing here separates map layout from wave tuning.",
            "",
        ]
    for note in notes:
        out.append(f"> ingest note: {note}")
    if notes:
        out.append("")
    return out


def section_difficulty(runs: list[Run], pooled: dict) -> list[str]:
    reached, died, quit_ = reach_counts(runs)
    total = len(runs)
    out = [
        "## 2. Difficulty curve",
        "",
        "One row per round. `reached` is how many runs entered that round at "
        "all — it only ever falls, so it is the survival curve. `died` counts "
        "runs whose game ended there; `mortality` is `died / reached`, i.e. "
        "your chance of dying **given that you got this far**, which is the "
        "honest measure of how hard a round is. `breaches` is base hits per "
        "run that round — a breach costs exactly one life, since the "
        "recorder's `leaks` and `lives_lost` are the same number in every "
        "record, so they are reported once. `kill %` is kills over enemies "
        "spawned; it can exceed 100% because a wave's survivors are killed "
        "during the *next* round and counted there, so a figure over 100 "
        "means the previous wave was still on the board when this one "
        f"started. Rows with n below {MIN_N_FOR_CONFIDENCE} are marked `~` "
        "and should be read as anecdote.",
        "",
    ]
    rows = []
    for rnd in sorted(reached):
        n_reach = reached[rnd]
        recs = pooled.get(rnd, [])
        n = len(recs)
        mortality = died.get(rnd, 0) / n_reach if n_reach else 0
        # Breaches are rare and lumpy: the median is 0 at almost every round,
        # which hides the whole signal. Rate per run is the readable number.
        breaches = sum(r.get("leaks", 0) for r in recs) / n if n else 0
        spawned = sum(r.get("enemies_spawned", 0) for r in recs)
        kills = sum(r.get("kills", 0) for r in recs)
        lives = med(r.get("lives_end", 0) for r in recs) if recs else 0
        wave = med(r.get("wave_size", 0) for r in recs) if recs else 0
        kidnaps = sum(r.get("kidnaps", 0) for r in recs) / n if n else 0
        flag = "~" if n_reach < MIN_N_FOR_CONFIDENCE else ""
        rows.append([
            f"{rnd}{flag}",
            n_reach,
            pct(n_reach, total),
            died.get(rnd, 0),
            quit_.get(rnd, 0),
            pct(died.get(rnd, 0), n_reach),
            fmt(wave),
            pct(kills, spawned) if spawned else "—",
            f"{breaches:.2f}",
            f"{kidnaps:.1f}",
            fmt(lives),
        ])
    out += table(
        ["round", "reached", "of all", "died", "quit", "mortality", "wave",
         "kill %", "breaches", "kidnaps", "lives left"],
        rows,
        "lrrrrrrrrrr",
    )
    out.append("")
    return out


def classify_rounds(runs: list[Run], pooled: dict) -> tuple[list, list]:
    """Flag rounds as too hard / too easy against the fixed thresholds.

    Shared by the markdown and HTML renderers so the two can never disagree.
    """
    reached, died, _ = reach_counts(runs)
    hard, easy = [], []
    for rnd in sorted(pooled):
        n_reach = reached.get(rnd, 0)
        if n_reach < MIN_N_FOR_CONFIDENCE:
            continue
        recs = pooled[rnd]
        breach_rate = sum(r.get("leaks", 0) for r in recs) / len(recs)
        mortality = died.get(rnd, 0) / n_reach
        if breach_rate >= HARD_BREACH_RATE or mortality >= HARD_MORTALITY:
            hard.append((rnd, breach_rate, mortality))
        elif breach_rate <= EASY_BREACH_RATE and mortality == 0:
            easy.append(rnd)
    return hard, easy


THRESHOLDS = {
    "breach": HARD_BREACH_RATE,
    "mortality": HARD_MORTALITY,
    "easy_breach": EASY_BREACH_RATE,
    "min_n": MIN_N_FOR_CONFIDENCE,
}


def section_verdict(runs: list[Run], pooled: dict) -> list[str]:
    """Opinionated read of the curve. Inference, kept separate from the data."""
    hard, easy = classify_rounds(runs, pooled)

    out = [
        "## 3. Where the game is too hard and too easy",
        "",
        "*Inferred* from the curve above using fixed thresholds "
        f"(too hard: ≥{HARD_BREACH_RATE} breaches/run **or** ≥{HARD_MORTALITY:.0%} "
        f"mortality; too easy: ≤{EASY_BREACH_RATE} breaches/run **and** nobody "
        f"dying; rounds seen by <{MIN_N_FOR_CONFIDENCE} runs skipped). "
        "These are flags to look at, not conclusions.",
        "",
    ]
    if hard:
        out += ["**Spike rounds (too hard):**", ""]
        out += table(
            ["round", "breaches/run", "mortality"],
            [[r, f"{b:.2f}", f"{m:.0%}"] for r, b, m in hard],
            "lrr",
        )
        out.append("")
    else:
        out += ["No round crossed the too-hard thresholds.", ""]
    if easy:
        runs_of = _consecutive(easy)
        out += [
            "**Slack rounds (too easy)** — essentially nobody lost a life and "
            "no run ended: " + ", ".join(runs_of) + ".",
            "",
        ]
    else:
        out += ["No round crossed the too-easy thresholds.", ""]
    return out


def _consecutive(nums: list[int]) -> list[str]:
    out, start, prev = [], None, None
    for n in nums + [None]:
        if start is None:
            start = prev = n
            continue
        if n is not None and n == prev + 1:
            prev = n
            continue
        out.append(str(start) if start == prev else f"{start}–{prev}")
        start = prev = n
    return out


def section_economy(pooled: dict, reached: dict) -> list[str]:
    out = [
        "## 4. Economy curve",
        "",
        "`love end` is the wallet at the close of the round — the number that "
        "says whether players are starved or hoarding. A median that climbs "
        "without bound means love has stopped being a constraint; a median "
        "pinned near zero means every decision is forced. `spent` is love put "
        "into buildings that round; if it stays far below `income`, players "
        "either can't afford anything worth buying or don't know what to buy. "
        "`lost` is income that a building would have paid had it survived the "
        "wave — a hidden second penalty on top of losing the building.",
        "",
    ]
    rows = []
    for rnd, recs in pooled.items():
        lo, hi = iqr([r.get("love_end", 0) for r in recs])
        rows.append([
            rnd,
            len(recs),
            fmt(med(r.get("love_start", 0) for r in recs)),
            fmt(med(r.get("income_actual", 0) for r in recs)),
            fmt(med(r.get("upkeep_actual", 0) for r in recs)),
            fmt(med(r.get("love_spent_buildings", 0) for r in recs)),
            fmt(med(r.get("love_end", 0) for r in recs)),
            f"{fmt(lo)}–{fmt(hi)}",
            sum(r.get("income_lost_to_damage", 0) for r in recs),
        ])
    out += table(
        ["round", "n", "love start", "income", "upkeep", "spent", "love end",
         "IQR", "lost"],
        rows,
        "lrrrrrrrr",
    )
    out.append("")

    tot_actual = sum(r.get("income_actual", 0) for recs in pooled.values() for r in recs)
    tot_pot = sum(r.get("income_potential", 0) for recs in pooled.values() for r in recs)
    lost = tot_pot - tot_actual
    out += [
        f"Across the whole session players earned **{tot_actual} love** of a "
        f"possible **{tot_pot}** — **{lost} love ({pct(lost, tot_pot)}) never "
        "paid out because the building that would have paid it was dead at "
        "payday.**",
        "",
    ]
    return out


def section_pacing(runs: list[Run], pooled: dict) -> list[str]:
    """Wall-clock per round, from the gap between consecutive round summaries."""
    per_round: dict[int, list[float]] = collections.defaultdict(list)
    build_phase: dict[int, list[float]] = collections.defaultdict(list)
    for run in runs:
        prev_end = 0.0
        for row in run.rounds:
            rnd = row["round"]
            end = row.get("wall_ms", 0)
            if end > prev_end:
                per_round[rnd].append((end - prev_end) / 1000.0)
            waves = [e for e in run.events_of("wave_start")
                     if e.get("wall_ms", 0) > prev_end and e.get("wall_ms", 0) <= end]
            if waves and waves[0].get("wall_ms", 0) > prev_end:
                build_phase[rnd].append((waves[0]["wall_ms"] - prev_end) / 1000.0)
            prev_end = end

    out = [
        "## 5. Pacing",
        "",
        "Seconds of wall-clock per round, and how much of that was the build "
        "phase (round start to the wave spawning). A build phase of a few "
        "seconds means players are committing without deliberating — either "
        "they have nothing to decide, or the UI is rushing them.",
        "",
    ]
    rows = []
    for rnd in sorted(pooled):
        tot = per_round.get(rnd, [])
        bld = build_phase.get(rnd, [])
        if not tot:
            continue
        rows.append([
            rnd, len(tot), f"{med(tot):.0f}",
            f"{med(bld):.0f}" if bld else "—",
            pct(med(bld), med(tot)) if bld and med(tot) else "—",
        ])
    out += table(["round", "n", "total s", "build s", "build share"], rows, "lrrrr")
    out.append("")
    total_min = sum(r.duration_min for r in runs)
    out += [
        f"Total recorded play: **{total_min:.0f} minutes** over {len(runs)} runs "
        f"(median {med([r.duration_min for r in runs]):.1f} min per run).",
        "",
    ]
    return out


def section_buildings(runs: list[Run]) -> list[str]:
    placed = collections.Counter()
    runs_with = collections.Counter()
    first_round: dict[str, list[int]] = collections.defaultdict(list)
    spend = collections.Counter()
    opener = collections.Counter()

    for run in runs:
        seen: dict[str, int] = {}
        places = run.events_of("place")
        if places:
            opener[places[0].get("building_type", "?")] += 1
        for ev in places:
            bt = ev.get("building_type", "?")
            placed[bt] += 1
            spend[bt] += ev.get("cost", 0)
            seen.setdefault(bt, ev.get("round", 0))
        for bt, rnd in seen.items():
            runs_with[bt] += 1
            first_round[bt].append(rnd)

    out = [
        "## 6. Building meta",
        "",
        "`% of runs` is the real signal. A type in nearly every run is not a "
        "choice, it is a requirement; a type in almost none is either "
        "unaffordable, unavailable, or unreadable. `first seen` is the median "
        "round it first hits the board.",
        "",
    ]
    total = len(runs)
    rows = []
    for bt, n in placed.most_common():
        rows.append([
            bt, n, runs_with[bt], pct(runs_with[bt], total),
            fmt(med(first_round[bt])), spend[bt],
            f"{spend[bt] / n:.1f}",
        ])
    out += table(
        ["building", "placements", "runs", "% of runs", "first seen", "love spent", "avg cost"],
        rows, "lrrrrrr",
    )
    out.append("")
    if opener:
        out += [
            "Opening placement: " +
            ", ".join(f"**{k}** {pct(v, total)}" for k, v in opener.most_common()) + ".",
            "",
        ]
    return out


def section_progression(runs: list[Run]) -> list[str]:
    levelup = collections.Counter()
    unlock = collections.Counter()
    research = collections.Counter()
    boss = collections.Counter()
    levels_reached = []

    for run in runs:
        for ev in run.events_of("levelup"):
            levelup[ev.get("option", "?")] += 1
        for ev in run.events_of("unlock"):
            unlock[ev.get("building_type", "?")] += 1
        for ev in run.events_of("research"):
            research[f"{ev.get('building_type','?')} T{ev.get('tier','?')}"] += 1
        for ev in run.events_of("boss_choice"):
            boss[(ev.get("boss_num"), ev.get("option"), ev.get("outcome"))] += 1
        if run.rounds:
            levels_reached.append(run.rounds[-1].get("village_level", 1))

    out = [
        "## 7. Progression choices",
        "",
        "What players actually pick when the game offers them a choice. An "
        "option that is never taken is either strictly worse or badly "
        "explained; both are balance problems.",
        "",
    ]
    tot_lv = sum(levelup.values())
    out += ["**Level-up option taken:**", ""]
    out += table(["option", "times", "share"],
                 [[k, v, pct(v, tot_lv)] for k, v in levelup.most_common()], "lrr")
    out += ["", "**Buildings unlocked:**", ""]
    tot_un = sum(unlock.values())
    out += table(["building", "times", "share of unlocks"],
                 [[k, v, pct(v, tot_un)] for k, v in unlock.most_common()], "lrr")
    out += ["", "**Research purchased:**", ""]
    out += table(["research", "times"],
                 [[k, v] for k, v in research.most_common()] or [["none recorded", 0]], "lr")
    if levels_reached:
        out += ["", f"Village level reached: median **{med(levels_reached):.0f}**, "
                    f"max **{max(levels_reached)}**."]
    if boss:
        out += ["", "**Boss encounters:**", ""]
        rows = []
        for (num, opt, outcome), n in sorted(boss.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1] or "")):
            rows.append([f"boss {num}", f"option {opt}", outcome, n])
        out += table(["boss", "choice", "result", "times"], rows, "lllr")
        by_choice = collections.Counter()
        wins = collections.Counter()
        for (num, opt, outcome), n in boss.items():
            by_choice[(num, opt)] += n
            if outcome == "win":
                wins[(num, opt)] += n
        out += ["", "Win rate per choice: " + ", ".join(
            f"boss {num} option {opt} **{pct(wins[(num, opt)], t)}** ({t} taken)"
            for (num, opt), t in sorted(by_choice.items())) + "."]
    out.append("")
    return out


def section_spatial(runs: list[Run]) -> list[str]:
    """Where players build vs where enemies actually die."""
    places = collections.Counter()
    deaths = collections.Counter()
    for run in runs:
        for ev in run.events_of("place"):
            places[(ev.get("col"), ev.get("row"))] += 1
        for ev in run.events_of("enemy_death"):
            wx, wy = ev.get("wx"), ev.get("wy")
            if wx is None or wy is None:
                continue
            deaths[(int(wx), int(wy))] += 1
    if not places and not deaths:
        return []

    out = [
        "## 8. Where the fight happens",
        "",
        "Top build tiles against top kill tiles. Where they coincide the "
        "defence is doing its job; kills far from any build tile are the base "
        "or lightning finishing enemies the towers failed to stop.",
        "",
    ]
    out += table(
        ["rank", "build tile (col,row)", "placements", "kill tile (x,y)", "kills"],
        [
            [
                i + 1,
                f"{p[0][0]},{p[0][1]}" if p else "—", p[1] if p else "—",
                f"{d[0][0]},{d[0][1]}" if d else "—", d[1] if d else "—",
            ]
            for i, (p, d) in enumerate(
                zip(places.most_common(10) + [None] * 10, deaths.most_common(10) + [None] * 10)
            )
            if i < 10
        ],
        "lrrrr",
    )
    out.append("")

    hits = collections.Counter()
    for run in runs:
        for ev in run.events_of("base_hit"):
            hits[ev.get("etype", "?")] += 1
    if hits:
        out += ["Enemy types that reached the base: " +
                ", ".join(f"**{k}** ×{v}" for k, v in hits.most_common()) + ".", ""]
    return out


def section_enemies(runs: list[Run]) -> list[str]:
    killed = collections.Counter()
    spawned = collections.Counter()
    kidnappers = collections.Counter()
    kidnapped = collections.Counter()
    for run in runs:
        for ev in run.events_of("enemy_death"):
            killed[ev.get("etype", "?")] += 1
        for ev in run.events_of("wave_start"):
            for etype, n in (ev.get("composition") or {}).items():
                spawned[etype] += n
        for ev in run.events_of("kidnap"):
            kidnappers[ev.get("etype", "?")] += 1
            kidnapped[ev.get("building_type", "?")] += 1
    if not spawned and not killed:
        return []
    out = [
        "## 9. Enemies",
        "",
        "Kill rate per enemy type across the session. A type players kill far "
        "less often than they meet is the one actually applying the pressure.",
        "",
    ]
    rows = []
    for etype in sorted(set(spawned) | set(killed)):
        s, k = spawned.get(etype, 0), killed.get(etype, 0)
        rows.append([etype, s, k, pct(k, s) if s else "—", kidnappers.get(etype, 0)])
    out += table(["enemy", "spawned", "killed", "kill %", "kidnaps"], rows, "lrrrr")
    out.append("")
    if kidnapped:
        out += ["Buildings kidnapped, by type: " +
                ", ".join(f"**{k}** ×{v}" for k, v in kidnapped.most_common()) + ".", ""]
    return out


def section_skill_split(runs: list[Run]) -> list[str]:
    """The same curve, cut by self-reported skill."""
    by_skill: dict[str, list[Run]] = collections.defaultdict(list)
    for run in runs:
        by_skill[run.skill].append(run)
    if len(by_skill) < 2:
        return []

    out = [
        "## 10. By self-reported skill",
        "",
        "The same players, split by the skill box they ticked. If a wall hits "
        "one bucket and not another it is a teaching problem, not a numbers "
        "problem. Buckets with few runs are anecdote — the `runs` column is "
        "there so you can tell which is which.",
        "",
    ]
    rows = []
    for skill, group in sorted(by_skill.items(), key=lambda kv: -len(kv[1])):
        lens = [len(r.rounds) for r in group]
        deaths = [r.death_round for r in group if r.death_round]
        breaches = sum(row.get("leaks", 0) for r in group for row in r.rounds)
        rounds_played = sum(lens)
        rows.append([
            skill, len(group), fmt(med(lens)), max(lens),
            fmt(med(deaths)) if deaths else "—",
            f"{breaches / rounds_played:.2f}" if rounds_played else "—",
            f"{med([r.duration_min for r in group]):.1f}",
        ])
    out += table(
        ["skill", "runs", "median rounds", "best", "median death round",
         "breaches/round", "median min"],
        rows, "lrrrrrr",
    )
    out.append("")

    out += ["**Survival by round, per bucket** (share of that bucket's runs still alive):", ""]
    max_round = max((len(r.rounds) for r in runs), default=0)
    steps = [r for r in range(1, max_round + 1) if r % max(1, max_round // 10) == 0][:10]
    header = ["skill", "runs"] + [f"r{r}" for r in steps]
    rows = []
    for skill, group in sorted(by_skill.items(), key=lambda kv: -len(kv[1])):
        row = [skill, len(group)]
        for r in steps:
            row.append(pct(sum(1 for g in group if len(g.rounds) >= r), len(group)))
        rows.append(row)
    out += table(header, rows, "lr" + "r" * len(steps))
    out.append("")
    return out


def read_form(form_path) -> list[dict]:
    """Player questionnaire rows, or [] if there is no readable file."""
    if not form_path:
        return []
    try:
        with open(form_path, encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def section_form(form_path: Path, runs: list[Run]) -> list[str]:
    """Aggregate the player questionnaire and cross-check it against telemetry."""
    rows = read_form(form_path)
    if not form_path.exists():
        return ["## 11. Player questionnaire", "",
                f"> could not read {form_path}", ""]
    if not rows:
        return ["## 11. Player questionnaire", "", "> form file has no responses.", ""]

    out = [
        "## 11. Player questionnaire",
        "",
        f"**{len(rows)} responses.** The form is anonymous, so it cannot be "
        "joined to individual runs — it is read as a separate sample over the "
        "same session. Where a question has an answer the telemetry also "
        "measures, both are shown, and the gap is the finding.",
        "",
    ]
    fields = [f for f in rows[0].keys() if f and f.lower() != "timestamp"]
    # Short answers get counted; long free text gets listed verbatim.
    for field in fields:
        answers = [(r.get(field) or "").strip() for r in rows]
        answers = [a for a in answers if a]
        if not answers:
            continue
        long_form = statistics.mean(len(a) for a in answers) > 40
        out += [f"**{field}**  *(n={len(answers)})*", ""]
        if long_form:
            for a in answers:
                out.append(f"- {a.replace(chr(10), ' / ')}")
        else:
            counts = collections.Counter(answers)
            out += table(["answer", "n", "share"],
                         [[k, v, pct(v, len(answers))] for k, v in counts.most_common()],
                         "lrr")
        out.append("")

    # Cross-check: self-reported furthest round vs measured.
    reach_field = next((f for f in fields if "how far" in f.lower()), None)
    if reach_field:
        claimed = []
        for r in rows:
            digits = "".join(ch if ch.isdigit() else " " for ch in (r.get(reach_field) or ""))
            nums = [int(d) for d in digits.split() if d]
            if nums:
                claimed.append(max(nums))
        if claimed:
            measured = [len(r.rounds) for r in runs]
            best_per_player: dict[str, int] = {}
            for run in runs:
                key = run.player.lower()
                best_per_player[key] = max(best_per_player.get(key, 0), len(run.rounds))
            out += [
                "**Cross-check — furthest round reached:**", "",
            ]
            out += table(
                ["source", "n", "median", "max"],
                [
                    ["self-reported on the form", len(claimed), fmt(med(claimed)), max(claimed)],
                    ["measured, per run", len(measured), fmt(med(measured)), max(measured)],
                    ["measured, best run per player name", len(best_per_player),
                     fmt(med(best_per_player.values())), max(best_per_player.values())],
                ],
                "lrrr",
            )
            out += [
                "",
                "> Players report their *best* run; the telemetry median covers "
                "*every* run including the short ones. Compare the form figure "
                "against the best-run-per-player row, not the per-run row. If "
                "the form asked this as a bucketed dropdown, its resolution is "
                "the bucket width — read the answer table above for the "
                "wording before trusting the median.",
                "",
            ]

    # Cross-check: when players *think* they first lost a life vs when they did.
    life_field = next((f for f in fields if "first live" in f.lower()
                       or "first life" in f.lower()), None)
    if life_field:
        claimed = []
        for r in rows:
            digits = "".join(ch if ch.isdigit() else " " for ch in (r.get(life_field) or ""))
            nums = [int(d) for d in digits.split() if d]
            if nums:
                claimed.append(min(nums))
        measured = []
        for run in runs:
            hit = next((row["round"] for row in run.rounds if row.get("leaks", 0) > 0), None)
            if hit:
                measured.append(hit)
        if claimed and measured:
            out += ["**Cross-check — round of first life lost:**", ""]
            out += table(
                ["source", "n", "median", "earliest", "latest"],
                [
                    ["self-reported on the form", len(claimed), fmt(med(claimed)),
                     min(claimed), max(claimed)],
                    ["measured", len(measured), fmt(med(measured)),
                     min(measured), max(measured)],
                ],
                "lrrrr",
            )
            out += [
                "",
                f"> {len(runs) - len(measured)} of {len(runs)} runs never lost a "
                "life at all and are absent from the measured row. A "
                "self-reported figure that lands *earlier* than the measured "
                "one means the first breach felt worse than it was — a "
                "feedback/clarity issue rather than a tuning one.",
                "",
            ]
    return out


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_report(runs: list[Run], excluded: dict, notes: list[str], args) -> str:
    pooled = pool_rounds(runs)
    reached, _, _ = reach_counts(runs)
    lines: list[str] = []
    lines += [
        f"# QA triage — {args.session.name}",
        "",
        f"Pooled balance report over {len(runs)} runs. Generated by "
        "`tools/qa_triage.py`; every number below is measured from the debug "
        "recorder's `events.jsonl`, except section 3, which is explicitly "
        "inferred.",
        "",
        "---",
        "",
    ]
    lines += section_cohort(runs, excluded, notes, args)
    lines += section_difficulty(runs, pooled)
    lines += section_verdict(runs, pooled)
    lines += section_economy(pooled, reached)
    lines += section_pacing(runs, pooled)
    lines += section_buildings(runs)
    lines += section_progression(runs)
    lines += section_spatial(runs)
    lines += section_enemies(runs)
    lines += section_skill_split(runs)
    if args.form:
        lines += section_form(Path(args.form), runs)
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("session", type=Path, help="session dir holding per-host log folders")
    ap.add_argument("--form", help="player questionnaire CSV to fold in")
    ap.add_argument("--skill", help="comma-separated skill buckets to keep (e.g. never,a_bit)")
    ap.add_argument("--outcome",
                    help="comma-separated run outcomes to keep (game_over, quit, "
                         "quit_to_menu). --outcome game_over drops every run the "
                         "player walked away from, so the survival curve is a pure "
                         "death curve")
    ap.add_argument("--min-rounds", type=int, default=DEFAULT_MIN_ROUNDS,
                    help=f"drop runs shorter than this (default {DEFAULT_MIN_ROUNDS})")
    ap.add_argument("--include-devs", action="store_true",
                    help="keep runs whose skill bucket is a developer one")
    ap.add_argument("--include-cheats", action="store_true",
                    help="keep runs where cheats were used")
    ap.add_argument("--out", help="write markdown here instead of stdout")
    ap.add_argument("--html", help="also write the charted HTML report here "
                                   "(default: alongside --out, same name, .html)")
    ap.add_argument("--no-html", action="store_true",
                    help="skip the HTML report even when --out is given")
    args = ap.parse_args(argv)

    if not args.session.is_dir():
        print(f"no such session dir: {args.session}", file=sys.stderr)
        return 2
    args.skill = [s.strip() for s in args.skill.split(",")] if args.skill else None
    args.outcome = [s.strip() for s in args.outcome.split(",")] if args.outcome else None

    runs, notes = load_session(args.session)
    if not runs:
        print(f"no runs found under {args.session}", file=sys.stderr)
        return 1
    kept, excluded = apply_filters(runs, args)
    if not kept:
        print("every run was filtered out — loosen --skill / --min-rounds", file=sys.stderr)
        return 1

    report = build_report(kept, excluded, notes, args)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"wrote {args.out} — {len(kept)} runs analysed, "
              f"{sum(excluded.values())} excluded")
    else:
        sys.stdout.write(report)

    html_path = Path(args.html) if args.html else (
        Path(args.out).with_suffix(".html") if args.out and not args.no_html else None
    )
    if html_path:
        write_html_report(html_path, kept, excluded, notes, args)
        print(f"wrote {html_path}")
    return 0


def write_html_report(path: Path, runs: list[Run], excluded: dict,
                      notes: list[str], args) -> Path:
    """The charted HTML twin of the markdown report, from the same numbers."""
    from tools.qa_triage_html import write_html

    pooled = pool_rounds(runs)
    reached, died, quit_ = reach_counts(runs)
    hard, easy = classify_rounds(runs, pooled)
    return write_html(
        path,
        session_name=args.session.name,
        runs=runs, pooled=pooled, reached=reached, died=died, quit_=quit_,
        excluded=excluded, notes=notes, form_rows=read_form(args.form),
        hard_rounds=hard, easy_rounds=easy, thresholds=THRESHOLDS,
        caveats=caveats_for(args),
    )


if __name__ == "__main__":
    raise SystemExit(main())
