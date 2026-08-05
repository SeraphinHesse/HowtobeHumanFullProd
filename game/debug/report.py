"""Report writers — PURE stdlib. No pygame, no third-party package, no network.

Three artifacts, all written from ``DebugRecorder.close()``:

``write_rounds_csv``  one row per round; the header IS ``metrics.ROUND_FIELDS``
                      (a test pins that, so schema and CSV cannot drift).
``write_summary``     the markdown digest a human or an LLM skims.
``write_html``        ONE self-contained file. Every chart is inline SVG
                      generated right here — **no external URL, no CDN, no
                      webfont, no JS library, and ``requirements.txt`` gains
                      nothing**. A test asserts the output contains no
                      ``http://`` / ``https://`` / ``//cdn``.

Chart design notes (so a later edit does not undo them): one y-scale per chart —
never a dual axis; "wave size vs damage output" is therefore a SCATTER (one
measure per axis) rather than two stacked scales. Series colours are assigned in
fixed slot order and never cycled; no chart here carries more than three series.
Identity is never colour-alone: every chart has a legend, and the full data table
is embedded at the bottom of the page. Hover tooltips are SVG ``<title>``
elements — native, zero-JS, and they survive the file being opened offline.
"""
import csv
import html

from .metrics import ROUND_FIELDS

# Categorical slots 1-3 (blue / orange / aqua), light and dark steps. This
# opening triple is the validated all-pairs-safe set; do not add a fourth
# without re-validating.
_SERIES_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a")
_SERIES_DARK = ("#3987e5", "#d95926", "#199e70")


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
def write_rounds_csv(rows, path):
    """One row per round. Header == ``metrics.ROUND_FIELDS``, in order.
    ``lineterminator="\\n"`` keeps two runs of the same seed byte-identical
    across platforms."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ROUND_FIELDS),
                                extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


# ---------------------------------------------------------------------------
# markdown digest
# ---------------------------------------------------------------------------
def _total(rows, key):
    return sum(r.get(key, 0) for r in rows)


def _merge_by_type(breakdowns, key):
    out = {}
    for bd in breakdowns or ():
        for btype, amount in (bd.get(key) or {}).items():
            out[btype] = out.get(btype, 0) + amount
    return out


def _share_table(title, totals, unit="dmg"):
    if not totals:
        return [f"**{title}** — none recorded.", ""]
    grand = sum(totals.values()) or 1
    lines = [f"**{title}**", "",
             f"| building type | {unit} | share |", "|---|---:|---:|"]
    for btype, amount in sorted(totals.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {btype} | {amount} | {100.0 * amount / grand:.1f}% |")
    lines.append("")
    return lines


def write_summary(rows, events, path, run_id="", outcome=None):
    """The markdown digest.

    ``events`` is the per-round auxiliary breakdown list the recorder keeps
    parallel to ``rows`` (``metrics.round_breakdown`` records: damage / income /
    upkeep split by building type, plus love spend by reason). It carries the
    detail that deliberately does not fit the flat CSV schema.
    """
    breakdowns = events or []
    out = [f"# Debug run summary — {run_id or 'run'}", ""]

    if not rows:
        out += ["No rounds were recorded (the run ended before the first "
                "payday).", ""]
        _write_text(path, "\n".join(out))
        return path

    first, last = rows[0], rows[-1]
    out += [
        "## Outcome", "",
        f"- outcome: **{outcome or 'unknown'}**",
        f"- rounds recorded: **{len(rows)}** (round {first['round']} -> "
        f"{last['round']})",
        f"- love: {first['love_start']} -> **{last['love_end']}**",
        f"- lives left: **{last['lives_end']}**",
        f"- village level: **{last['village_level']}** "
        f"(xp {last['player_xp']})",
        f"- cheats used this run: **{'YES' if last['cheated'] else 'no'}**",
        "",
        "## Totals", "",
        "| metric | total |", "|---|---:|",
        f"| income (actual) | {_total(rows, 'income_actual')} |",
        f"| income (potential, nothing lost) | "
        f"{_total(rows, 'income_potential')} |",
        f"| **income lost to buildings dying** | "
        f"**{_total(rows, 'income_lost_to_damage')}** |",
        f"| story income (Boss1B/3B, paid silently) | "
        f"{_total(rows, 'story_income')} |",
        f"| painter lump sums | {_total(rows, 'painter_income')} |",
        f"| upkeep billed (actual) | {_total(rows, 'upkeep_actual')} |",
        f"| upkeep potential | {_total(rows, 'upkeep_potential')} |",
        f"| upkeep unpaid because buildings died | "
        f"{_total(rows, 'upkeep_unpaid_from_deaths')} |",
        f"| net (actual) | {_total(rows, 'net_actual')} |",
        f"| net (potential) | {_total(rows, 'net_potential')} |",
        f"| damage dealt (building-credited) | {_total(rows, 'dmg_dealt')} |",
        f"| damage dealt (lightning, no shooter) | "
        f"{_total(rows, 'dmg_dealt_lightning')} |",
        f"| damage taken by buildings (HP) | "
        f"{_total(rows, 'dmg_taken_buildings')} |",
        f"| lives lost | {_total(rows, 'lives_lost')} |",
        f"| enemies spawned | {_total(rows, 'enemies_spawned')} |",
        f"| kills | {_total(rows, 'kills')} |",
        f"| leaks (base breaches) | {_total(rows, 'leaks')} |",
        f"| kidnaps | {_total(rows, 'kidnaps')} |",
        f"| buildings placed | {_total(rows, 'buildings_placed')} |",
        f"| love spent on buildings | "
        f"{_total(rows, 'love_spent_buildings')} |",
        "",
        "> `lives_lost` is NOT HP damage: a base breach applies none. Lightning "
        "damage is listed separately because it has no shooter and earns no "
        "`RoundStats` credit.",
        "",
        "## The actual-vs-potential income gap", "",
        "Payday's income sweep AND its upkeep sweep both skip a building that "
        "is not alive, so a building destroyed during the wave earns nothing "
        "and pays no upkeep. Both halves, never fused:", "",
        "| round | income actual | income potential | lost | upkeep unpaid | "
        "dead at payday |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        out.append(
            f"| {r['round']} | {r['income_actual']} | {r['income_potential']} "
            f"| {r['income_lost_to_damage']} | "
            f"{r['upkeep_unpaid_from_deaths']} | "
            f"{r['buildings_dead_at_payday']} |")
    lost = _total(rows, 'income_lost_to_damage')
    unpaid = _total(rows, 'upkeep_unpaid_from_deaths')
    out += [
        "",
        f"Net effect of losing buildings: **{lost - unpaid} love** "
        f"({lost} income lost, {unpaid} upkeep not billed).",
        "",
        "## Income curve", "",
        "| round | love start | income | upkeep | net | love end |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        out.append(
            f"| {r['round']} | {r['love_start']} | {r['income_actual']} | "
            f"{r['upkeep_actual']} | {r['net_actual']} | {r['love_end']} |")
    out.append("")

    out += ["## Damage share by building type", ""]
    out += _share_table("Damage dealt",
                        _merge_by_type(breakdowns, "dmg_dealt_by_type"))
    out += _share_table("Damage taken (HP)",
                        _merge_by_type(breakdowns, "dmg_taken_by_type"))

    out += ["## Love-spend breakdown", ""]
    spend = {}
    for bd in breakdowns:
        for reason, amount in (bd.get("love_spent_by_reason") or {}).items():
            spend[reason] = spend.get(reason, 0) + amount
    if spend:
        out += ["| reason | love |", "|---|---:|"]
        out += [f"| {k} | {v} |" for k, v in sorted(spend.items())]
    else:
        out.append("No love was spent on buildings during this run.")
    out += ["", "Upkeep billed by building type:", ""]
    out += _share_table("Upkeep",
                        _merge_by_type(breakdowns, "upkeep_actual_by_type"),
                        unit="love")

    out += ["## Leak rounds", ""]
    leaks = [r for r in rows if r["leaks"] or r["lives_lost"]]
    if leaks:
        out += ["| round | leaks | lives lost | lives left | wave size | "
                "kills | dmg dealt |", "|---:|---:|---:|---:|---:|---:|---:|"]
        for r in leaks:
            out.append(
                f"| {r['round']} | {r['leaks']} | {r['lives_lost']} | "
                f"{r['lives_end']} | {r['wave_size']} | {r['kills']} | "
                f"{r['dmg_dealt']} |")
    else:
        out.append("No enemy ever reached the hole.")
    out.append("")

    _write_text(path, "\n".join(out))
    return path


def _write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")


# ---------------------------------------------------------------------------
# inline-SVG chart primitives
# ---------------------------------------------------------------------------
_W, _H = 720, 260
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 52, 16, 16, 34


def _nice_max(value):
    """A round-ish axis maximum >= ``value`` (never 0, so the scale is sane)."""
    if value <= 0:
        return 1
    step = 1
    while step * 10 <= value:
        step *= 10
    for mult in (1, 2, 2.5, 5, 10):
        cap = step * mult
        if cap >= value:
            return int(cap) if cap == int(cap) else cap
    return value


def _axes(vmax, labels):
    """Grid lines + y ticks + x labels. Recessive: 1px, muted ink."""
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B
    parts = []
    for i in range(5):
        val = vmax * i / 4.0
        y = _PAD_T + plot_h - plot_h * i / 4.0
        parts.append(
            f'<line x1="{_PAD_L}" y1="{y:.1f}" x2="{_W - _PAD_R}" '
            f'y2="{y:.1f}" class="grid"/>')
        parts.append(
            f'<text x="{_PAD_L - 8}" y="{y + 4:.1f}" class="tick" '
            f'text-anchor="end">{_fmt(val)}</text>')
    # x labels: thin them out so they never collide.
    n = max(1, len(labels))
    stride = max(1, n // 12)
    for i, label in enumerate(labels):
        if i % stride:
            continue
        x = _PAD_L + plot_w * (i + 0.5) / n
        parts.append(
            f'<text x="{x:.1f}" y="{_H - _PAD_B + 18}" class="tick" '
            f'text-anchor="middle">{html.escape(str(label))}</text>')
    return "".join(parts)


def _fmt(value):
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def _bar_path(x, y, w, h, r=4.0):
    """A bar with rounded FREE end only — the baseline end stays square."""
    r = min(r, w / 2.0, max(h, 0.0))
    if h <= 0.5:
        return ""
    bottom = y + h
    return (f"M{x:.1f},{bottom:.1f} L{x:.1f},{y + r:.1f} "
            f"Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
            f"L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} "
            f"{x + w:.1f},{y + r:.1f} L{x + w:.1f},{bottom:.1f} Z")


def _svg_open(title):
    # No preserveAspectRatio override: the default (xMidYMid meet) keeps the
    # viewBox aspect, so text and markers never stretch when the card resizes.
    return (f'<svg viewBox="0 0 {_W} {_H}" role="img" '
            f'aria-label="{html.escape(title)}">')


def _legend(names):
    swatches = "".join(
        f'<span class="key"><i class="sw s{i + 1}"></i>{html.escape(n)}</span>'
        for i, n in enumerate(names))
    return f'<div class="legend">{swatches}</div>'


def _figure(title, note, names, body):
    legend = _legend(names) if len(names) > 1 else ""
    note_html = f'<p class="note">{html.escape(note)}</p>' if note else ""
    return (f'<figure class="chart"><figcaption>{html.escape(title)}'
            f'</figcaption>{legend}{body}{note_html}</figure>')


def _bar_chart(title, note, labels, series):
    """Grouped bars. ``series`` = [(name, [values...]), ...], max 3."""
    vmax = _nice_max(max((max(v) if v else 0 for _n, v in series), default=0))
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B
    n = max(1, len(labels))
    group_w = plot_w / n
    inner = max(2.0, group_w - 6.0)
    bar_w = max(1.5, inner / len(series) - 2.0)   # 2px surface gap between bars
    marks = []
    for si, (name, values) in enumerate(series):
        for i, value in enumerate(values):
            h = plot_h * (value / vmax) if vmax else 0
            x = _PAD_L + group_w * i + 3.0 + si * (bar_w + 2.0)
            y = _PAD_T + plot_h - h
            path = _bar_path(x, y, bar_w, h)
            if not path:
                continue
            marks.append(
                f'<path d="{path}" class="s{si + 1}f"><title>'
                f'{html.escape(str(labels[i]))} — {html.escape(name)}: '
                f'{value}</title></path>')
    body = (_svg_open(title) + _axes(vmax, labels) + "".join(marks)
            + f'<line x1="{_PAD_L}" y1="{_PAD_T + plot_h}" '
              f'x2="{_W - _PAD_R}" y2="{_PAD_T + plot_h}" class="axis"/>'
            + "</svg>")
    return _figure(title, note, [n for n, _v in series], body)


def _line_chart(title, note, labels, series):
    """Lines with visible point markers + a direct label on the last point."""
    vmax = _nice_max(max((max(v) if v else 0 for _n, v in series), default=0))
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B
    n = max(1, len(labels))

    def px(i):
        return _PAD_L + plot_w * (i + 0.5) / n

    def py(value):
        return _PAD_T + plot_h - (plot_h * (value / vmax) if vmax else 0)

    marks = []
    for si, (name, values) in enumerate(series):
        pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(values))
        marks.append(f'<polyline points="{pts}" class="s{si + 1}l"/>')
        for i, value in enumerate(values):
            marks.append(
                f'<circle cx="{px(i):.1f}" cy="{py(value):.1f}" r="4.5" '
                f'class="s{si + 1}f dot"><title>'
                f'{html.escape(str(labels[i]))} — {html.escape(name)}: '
                f'{value}</title></circle>')
        if values:
            # Stagger above/below so two series' end labels cannot collide.
            dy = -10 if si % 2 == 0 else 18
            marks.append(
                f'<text x="{px(len(values) - 1) - 8:.1f}" '
                f'y="{py(values[-1]) + dy:.1f}" class="dlabel" '
                f'text-anchor="end">{html.escape(name)}: {values[-1]}</text>')
    body = (_svg_open(title) + _axes(vmax, labels) + "".join(marks)
            + f'<line x1="{_PAD_L}" y1="{_PAD_T + plot_h}" '
              f'x2="{_W - _PAD_R}" y2="{_PAD_T + plot_h}" class="axis"/>'
            + "</svg>")
    return _figure(title, note, [n for n, _v in series], body)


def _scatter(title, note, xs, ys, labels, x_name, y_name):
    """One measure per axis — the honest alternative to a dual-axis chart."""
    xmax = _nice_max(max(xs) if xs else 0)
    ymax = _nice_max(max(ys) if ys else 0)
    plot_w = _W - _PAD_L - _PAD_R
    plot_h = _H - _PAD_T - _PAD_B
    marks = []
    for i, (xv, yv) in enumerate(zip(xs, ys)):
        cx = _PAD_L + plot_w * (xv / xmax if xmax else 0)
        cy = _PAD_T + plot_h - plot_h * (yv / ymax if ymax else 0)
        marks.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" class="s1f dot">'
            f'<title>round {html.escape(str(labels[i]))} — {x_name} {xv}, '
            f'{y_name} {yv}</title></circle>')
    axis_labels = []
    for i in range(5):
        y = _PAD_T + plot_h - plot_h * i / 4.0
        axis_labels.append(
            f'<line x1="{_PAD_L}" y1="{y:.1f}" x2="{_W - _PAD_R}" '
            f'y2="{y:.1f}" class="grid"/>'
            f'<text x="{_PAD_L - 8}" y="{y + 4:.1f}" class="tick" '
            f'text-anchor="end">{_fmt(ymax * i / 4.0)}</text>')
        x = _PAD_L + plot_w * i / 4.0
        axis_labels.append(
            f'<text x="{x:.1f}" y="{_H - _PAD_B + 18}" class="tick" '
            f'text-anchor="middle">{_fmt(xmax * i / 4.0)}</text>')
    body = (_svg_open(title) + "".join(axis_labels) + "".join(marks)
            + f'<line x1="{_PAD_L}" y1="{_PAD_T + plot_h}" '
              f'x2="{_W - _PAD_R}" y2="{_PAD_T + plot_h}" class="axis"/>'
            + "</svg>")
    return _figure(title, note, [f"{y_name} vs {x_name}"], body)


_CSS = """
:root { color-scheme: light dark; }
body { margin: 0; padding: 24px; font: 14px/1.5 system-ui, sans-serif;
       background: var(--surface-0); color: var(--text-primary); }
.viz-root {
  --surface-0: #f4f3f0; --surface-1: #fcfcfb;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #7a7975;
  --grid: #e2e1dd; --axis: #b8b7b2;
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a;
}
@media (prefers-color-scheme: dark) {
  .viz-root {
    --surface-0: #111110; --surface-1: #1a1a19;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #8f8e86;
    --grid: #2e2e2b; --axis: #4a4a46;
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
  }
}
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 28px 0 8px; color: var(--text-secondary);
     text-transform: uppercase; letter-spacing: .06em; }
.sub { color: var(--text-secondary); margin: 0 0 20px; }
.tiles { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 8px; }
.tile { background: var(--surface-1); border: 1px solid var(--grid);
        border-radius: 8px; padding: 10px 14px; min-width: 132px; }
.tile b { display: block; font-size: 22px; font-weight: 600; }
.tile span { color: var(--text-secondary); font-size: 12px; }
.charts { display: flex; flex-wrap: wrap; gap: 14px; }
.chart { background: var(--surface-1); border: 1px solid var(--grid);
         border-radius: 8px; margin: 0; padding: 12px 14px 6px; flex: 1 1 560px; }
figcaption { font-weight: 600; margin-bottom: 2px; }
.note { color: var(--text-muted); font-size: 12px; margin: 2px 0 6px; }
.legend { display: flex; gap: 14px; flex-wrap: wrap; margin: 2px 0 6px;
          color: var(--text-secondary); font-size: 12px; }
.key { display: inline-flex; align-items: center; gap: 6px; }
.sw { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.sw.s1 { background: var(--series-1); }
.sw.s2 { background: var(--series-2); }
.sw.s3 { background: var(--series-3); }
svg { width: 100%; height: auto; display: block; }
.grid { stroke: var(--grid); stroke-width: 1; }
.axis { stroke: var(--axis); stroke-width: 1; }
.tick { fill: var(--text-muted); font-size: 11px; }
.dlabel { fill: var(--text-secondary); font-size: 11px; }
.s1f { fill: var(--series-1); } .s2f { fill: var(--series-2); }
.s3f { fill: var(--series-3); }
.dot { stroke: var(--surface-1); stroke-width: 2; }
.s1l, .s2l, .s3l { fill: none; stroke-width: 2; }
.s1l { stroke: var(--series-1); } .s2l { stroke: var(--series-2); }
.s3l { stroke: var(--series-3); }
table { border-collapse: collapse; font-size: 12px; width: 100%;
        background: var(--surface-1); }
th, td { border: 1px solid var(--grid); padding: 3px 6px; text-align: right;
         white-space: nowrap; }
th { color: var(--text-secondary); font-weight: 600; position: sticky; top: 0;
     background: var(--surface-1); }
.scroll { overflow: auto; max-height: 420px; border-radius: 8px; }
"""


def _tile(label, value):
    return (f'<div class="tile"><b>{html.escape(str(value))}</b>'
            f'<span>{html.escape(label)}</span></div>')


def _table(rows):
    head = "".join(f"<th>{html.escape(f)}</th>" for f in ROUND_FIELDS)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(r.get(f, '')))}</td>"
                         for f in ROUND_FIELDS) + "</tr>"
        for r in rows)
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


def write_html(rows, path, run_id="", outcome=None):
    """ONE self-contained HTML file: inline CSS, inline SVG, no external
    reference of any kind. Six charts + a stat row + the full data table."""
    title = f"Debug run report — {run_id or 'run'}"
    if not rows:
        _write_text(path, (
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>{_CSS}</style></head>'
            f'<body class="viz-root"><h1>{html.escape(title)}</h1>'
            '<p class="sub">No rounds were recorded (the run ended before the '
            'first payday).</p></body></html>'))
        return path

    labels = [r["round"] for r in rows]
    col = lambda k: [r.get(k, 0) for r in rows]  # noqa: E731
    last = rows[-1]

    tiles = "".join([
        _tile("rounds", len(rows)),
        _tile("love at end", last["love_end"]),
        _tile("lives left", last["lives_end"]),
        _tile("kills", _total(rows, "kills")),
        _tile("leaks", _total(rows, "leaks")),
        _tile("income lost to deaths", _total(rows, "income_lost_to_damage")),
        _tile("cheated", "YES" if last["cheated"] else "no"),
    ])

    dmg_total = [a + b for a, b in zip(col("dmg_dealt"),
                                       col("dmg_dealt_lightning"))]
    charts = "".join([
        _line_chart(
            "Love over rounds",
            "Love held at the end of each payday.",
            labels, [("love", col("love_end"))]),
        _bar_chart(
            "Income vs upkeep",
            "Actual love paid in and billed out each payday. Upkeep is what "
            "was BILLED — love clamps at 0, so a bankrupt round paid less.",
            labels, [("income", col("income_actual")),
                     ("upkeep", col("upkeep_actual"))]),
        _line_chart(
            "Actual vs potential income",
            "Potential = the same board with nothing dead. The gap is income "
            "lost because a building was destroyed during the wave.",
            labels, [("actual", col("income_actual")),
                     ("potential", col("income_potential"))]),
        _bar_chart(
            "Damage dealt vs taken",
            "Lightning is its own series: it has no shooter and earns no "
            "RoundStats credit. Damage TAKEN is building HP only — a base "
            "breach costs a life and applies no HP damage.",
            labels, [("dealt (buildings)", col("dmg_dealt")),
                     ("dealt (lightning)", col("dmg_dealt_lightning")),
                     ("taken (building HP)", col("dmg_taken_buildings"))]),
        _bar_chart(
            "Kills vs leaks",
            "A leak is an enemy that reached the hole; a waived tutorial leak "
            "costs no life, so lives lost can be lower.",
            labels, [("kills", col("kills")), ("leaks", col("leaks")),
                     ("lives lost", col("lives_lost"))]),
        _scatter(
            "Wave size vs damage output",
            "One point per round. Two measures, two axes of their own — never "
            "a dual y-scale.",
            col("wave_size"), dmg_total, labels,
            "wave size", "damage dealt"),
    ])

    doc = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{html.escape(title)}</title><style>{_CSS}</style></head>'
        f'<body class="viz-root"><h1>{html.escape(title)}</h1>'
        f'<p class="sub">outcome: <b>{html.escape(str(outcome or "unknown"))}'
        f'</b> &middot; rounds {rows[0]["round"]}&ndash;{last["round"]}</p>'
        f'<div class="tiles">{tiles}</div>'
        f'<h2>Charts</h2><div class="charts">{charts}</div>'
        f'<h2>Every round</h2>{_table(rows)}'
        '</body></html>')
    _write_text(path, doc)
    return path
