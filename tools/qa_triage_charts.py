"""HTML rendering for the playtest triage report — charts, not just tables.

ONE self-contained file: inline CSS, inline SVG, one small inline script for
the hover tooltip. No CDN, no build step, no external font — the report has to
open from a USB stick on a machine that has never seen this repo.

Chart conventions follow the house data-viz rules:
  * categorical slots are assigned in fixed order (blue, orange, aqua) and never
    cycled; a 4th series folds into "other" or gets its own chart,
  * one y-axis per chart — two measures of different scale become two charts,
  * bars cap at 24px with a 4px rounded data-end, lines are 2px, dots >= 8px
    with a 2px surface ring, gridlines are hairline and recessive,
  * every chart is backed by a table view in a <details>, which is also the
    relief for the one light-mode slot under 3:1 contrast,
  * dark mode is a selected set of steps for the dark surface, not a flip.
"""

from __future__ import annotations

import collections
import html
import statistics

# --- palette -----------------------------------------------------------------
# Validated with the house validator (all-pairs, both modes): worst CVD dE 9.2
# light / 9.4 dark, worst normal-vision dE 24.0 light / 20.9 dark.
CSS = """
:root { color-scheme: light dark; }
.viz-root {
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
  --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7; --ring:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a;
  --good:#0ca30c; --warn:#fab219; --serious:#ec835a; --crit:#d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz-root {
    --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7;
    --muted:#898781; --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
    --s1:#3987e5; --s2:#d95926; --s3:#199e70;
  }
}
:root[data-theme="dark"] .viz-root {
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7;
  --muted:#898781; --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--plane); color:var(--ink);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
.wrap { max-width:1080px; margin:0 auto; padding:40px 24px 96px; }
h1 { font-size:30px; line-height:1.2; margin:0 0 6px; letter-spacing:-.02em; }
h2 { font-size:21px; margin:56px 0 6px; letter-spacing:-.01em; }
h3 { font-size:15px; margin:28px 0 4px; }
p  { color:var(--ink2); margin:0 0 14px; max-width:74ch; }
.sub { color:var(--muted); font-size:14px; margin-bottom:28px; }
.lede { color:var(--ink2); font-size:15px; }
a { color:var(--s1); }

.tiles { display:grid; gap:12px; margin:24px 0 8px;
  grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); }
.tile { background:var(--surface); border:1px solid var(--ring); border-radius:10px;
  padding:14px 16px; }
.tile b { display:block; font-size:27px; font-weight:600; letter-spacing:-.02em; }
.tile span { display:block; color:var(--muted); font-size:12.5px; margin-top:2px; }
.tile .hero { font-size:44px; }

figure { background:var(--surface); border:1px solid var(--ring); border-radius:12px;
  margin:18px 0; padding:18px 18px 12px; }
figcaption { font-weight:600; font-size:14.5px; margin-bottom:2px; }
.cap { color:var(--muted); font-size:12.5px; margin:0 0 12px; max-width:80ch; }
svg { width:100%; height:auto; display:block; overflow:visible; }
.grid { stroke:var(--grid); stroke-width:1; }
.axis { stroke:var(--axis); stroke-width:1; }
.tick { fill:var(--muted); font-size:11px; font-variant-numeric:tabular-nums; }
.dlabel { fill:var(--ink2); font-size:11.5px; font-weight:600; }
.mark { transition:opacity .12s; }
figure:hover .mark { opacity:.5; }
figure .mark:hover, figure .mark.on { opacity:1; }
.legend { display:flex; flex-wrap:wrap; gap:16px; margin:0 0 12px; font-size:12.5px;
  color:var(--ink2); }
.legend i { width:11px; height:11px; border-radius:3px; display:inline-block;
  margin-right:6px; vertical-align:-1px; }

details { margin:6px 0 2px; }
summary { cursor:pointer; color:var(--muted); font-size:12.5px; padding:4px 0; }
summary:hover { color:var(--ink2); }
table { border-collapse:collapse; width:100%; font-size:12.5px; margin:8px 0 4px;
  font-variant-numeric:tabular-nums; }
th,td { padding:5px 9px; border-bottom:1px solid var(--grid); text-align:right;
  white-space:nowrap; }
th:first-child,td:first-child { text-align:left; }
thead th { color:var(--muted); font-weight:600; border-bottom:1px solid var(--axis); }
tbody tr:hover { background:var(--plane); }
td.flag { color:var(--crit); font-weight:600; }
.badge { display:inline-block; padding:1px 8px; border-radius:99px; font-size:11.5px;
  font-weight:600; border:1px solid var(--ring); }
.badge.hard { color:var(--crit); } .badge.easy { color:var(--s1); }
.note { border-left:3px solid var(--axis); padding:2px 0 2px 14px; color:var(--muted);
  font-size:13.5px; margin:14px 0; max-width:74ch; }
ul { color:var(--ink2); max-width:74ch; padding-left:20px; }
li { margin:4px 0; }
#tip { position:fixed; pointer-events:none; opacity:0; transition:opacity .1s;
  background:var(--ink); color:var(--plane); padding:6px 10px; border-radius:7px;
  font-size:12px; line-height:1.45; max-width:260px; z-index:9;
  font-variant-numeric:tabular-nums; }
@media print { figure { break-inside:avoid; } details { display:none; } }
"""

TIP_JS = """
(function(){
  var tip=document.getElementById('tip');
  document.addEventListener('mouseover',function(e){
    var m=e.target.closest('[data-tip]'); if(!m) return;
    tip.innerHTML=m.getAttribute('data-tip'); tip.style.opacity=1; m.classList.add('on');
  });
  document.addEventListener('mousemove',function(e){
    if(tip.style.opacity!=1) return;
    var x=e.clientX+14, y=e.clientY+14, r=tip.getBoundingClientRect();
    if(x+r.width>innerWidth-8) x=e.clientX-r.width-14;
    if(y+r.height>innerHeight-8) y=e.clientY-r.height-14;
    tip.style.left=x+'px'; tip.style.top=y+'px';
  });
  document.addEventListener('mouseout',function(e){
    var m=e.target.closest('[data-tip]'); if(!m) return;
    tip.style.opacity=0; m.classList.remove('on');
  });
})();
"""

# --- svg primitives ----------------------------------------------------------

W, H = 760, 250
PAD_L, PAD_R, PAD_T, PAD_B = 46, 18, 16, 30
PLOT_W = W - PAD_L - PAD_R
PLOT_H = H - PAD_T - PAD_B

SERIES = ["var(--s1)", "var(--s2)", "var(--s3)"]


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def _nice_max(v: float) -> float:
    """Round an axis top up to a clean number."""
    if v <= 0:
        return 1.0
    for mult in (1, 2, 2.5, 5, 10):
        for mag in (0.01, 0.1, 1, 10, 100, 1000, 10000):
            top = mult * mag
            if top >= v:
                return top
    return v


def _fmt(v: float) -> str:
    if v >= 1000:
        return f"{v:,.0f}"
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


def _frame(vmax: float, labels: list, y_suffix: str = "", ticks: int = 4) -> str:
    """Hairline gridlines, y ticks, baseline, and a sparse x-axis."""
    out = []
    for i in range(ticks + 1):
        y = PAD_T + PLOT_H - PLOT_H * i / ticks
        val = vmax * i / ticks
        out.append(f'<line class="grid" x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick" x="{PAD_L - 8}" y="{y + 3.5:.1f}" '
                   f'text-anchor="end">{_fmt(val)}{y_suffix}</text>')
    out.append(f'<line class="axis" x1="{PAD_L}" y1="{PAD_T + PLOT_H}" '
               f'x2="{W - PAD_R}" y2="{PAD_T + PLOT_H}"/>')
    n = len(labels)
    if n:
        step = max(1, n // 14)
        for i, lab in enumerate(labels):
            if i % step and i != n - 1:
                continue
            x = PAD_L + (PLOT_W * (i + 0.5) / n)
            out.append(f'<text class="tick" x="{x:.1f}" y="{H - PAD_B + 16}" '
                       f'text-anchor="middle">{esc(lab)}</text>')
    return "".join(out)


def _figure(title: str, caption: str, body: str, legend: list | None = None,
            table_html: str = "") -> str:
    leg = ""
    if legend:
        leg = '<div class="legend">' + "".join(
            f'<span><i style="background:{c}"></i>{esc(n)}</span>' for n, c in legend
        ) + "</div>"
    det = ""
    if table_html:
        det = f"<details><summary>Show the numbers</summary>{table_html}</details>"
    return (f'<figure><figcaption>{esc(title)}</figcaption>'
            f'<p class="cap">{caption}</p>{leg}'
            f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}">{body}</svg>'
            f'{det}</figure>')


def table(headers: list, rows: list) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{c if isinstance(c, str) and c.startswith('<') else esc(c)}</td>"
                         for c in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


# --- chart forms -------------------------------------------------------------


def bars(title, caption, labels, values, tips, *, y_suffix="", colors=None,
         table_html="", label_every=0):
    """Columns from a single baseline. One series, one axis."""
    if not values:
        return ""
    vmax = _nice_max(max(values) or 1)
    band = PLOT_W / len(values)
    bw = min(24.0, band - 6)
    out = [_frame(vmax, labels, y_suffix)]
    for i, v in enumerate(values):
        h = PLOT_H * (v / vmax)
        x = PAD_L + band * i + (band - bw) / 2
        y = PAD_T + PLOT_H - h
        fill = (colors[i] if colors else SERIES[0])
        # 4px rounded data-end, square at the baseline: a path, not a rect.
        r = min(4.0, h, bw / 2)
        if h <= 0.6:
            continue
        d = (f"M{x:.1f},{PAD_T + PLOT_H} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} "
             f"{x + r:.1f},{y:.1f} L{x + bw - r:.1f},{y:.1f} "
             f"Q{x + bw:.1f},{y:.1f} {x + bw:.1f},{y + r:.1f} "
             f"L{x + bw:.1f},{PAD_T + PLOT_H} Z")
        out.append(f'<path class="mark" d="{d}" fill="{fill}" data-tip="{esc(tips[i])}"/>')
        if label_every and (i % label_every == 0 or v == max(values)):
            out.append(f'<text class="dlabel" x="{x + bw / 2:.1f}" y="{y - 6:.1f}" '
                       f'text-anchor="middle">{_fmt(v)}{y_suffix}</text>')
    return _figure(title, caption, "".join(out), table_html=table_html)


def stacked_bars(title, caption, labels, series, tips, *, y_suffix="", table_html=""):
    """Parts of a whole, one unit. 2px surface gap between segments."""
    n = len(labels)
    if not n:
        return ""
    totals = [sum(s[1][i] for s in series) for i in range(n)]
    vmax = _nice_max(max(totals) or 1)
    band = PLOT_W / n
    bw = min(24.0, band - 6)
    out = [_frame(vmax, labels, y_suffix)]
    for i in range(n):
        base = PAD_T + PLOT_H
        for j, (_, vals) in enumerate(series):
            h = PLOT_H * (vals[i] / vmax)
            if h <= 0.6:
                continue
            x = PAD_L + band * i + (band - bw) / 2
            gap = 2 if j else 0  # surface gap, not a stroke
            y = base - h
            out.append(f'<rect class="mark" x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                       f'height="{max(0.5, h - gap):.1f}" rx="{min(4, bw / 2):.1f}" '
                       f'fill="{SERIES[j]}" data-tip="{esc(tips[i])}"/>')
            base -= h
    legend = [(name, SERIES[j]) for j, (name, _) in enumerate(series)]
    return _figure(title, caption, "".join(out), legend, table_html)


def lines(title, caption, labels, series, tips, *, y_suffix="", table_html="",
          area=False, end_labels=True):
    """2px lines sharing ONE axis. Dots >= 8px with a 2px surface ring."""
    n = len(labels)
    if not n:
        return ""
    vmax = _nice_max(max((max(v) for _, v in series if v), default=1) or 1)
    out = [_frame(vmax, labels, y_suffix)]
    xs = [PAD_L + PLOT_W * (i + 0.5) / n for i in range(n)]
    # End labels only work while the series separate at the right edge. When they
    # converge, nudging labels apart detaches them from their lines and reads as
    # noise — drop them all and let the legend + tooltip carry identity.
    if end_labels and len(series) > 1:
        ends = sorted(PLOT_H * (v[-1] / vmax) for _, v in series if v)
        if any(b - a < 14 for a, b in zip(ends, ends[1:])):
            end_labels = False
    for j, (name, vals) in enumerate(series):
        colour = SERIES[j % len(SERIES)]
        pts = [(xs[i], PAD_T + PLOT_H - PLOT_H * (vals[i] / vmax)) for i in range(len(vals))]
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        if area and len(series) == 1:
            fill = (f"{d} L{pts[-1][0]:.1f},{PAD_T + PLOT_H} "
                    f"L{pts[0][0]:.1f},{PAD_T + PLOT_H} Z")
            out.append(f'<path d="{fill}" fill="{colour}" opacity=".10"/>')
        out.append(f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="2" '
                   f'stroke-linejoin="round" stroke-linecap="round"/>')
        for i, (x, y) in enumerate(pts):
            out.append(f'<circle class="mark" cx="{x:.1f}" cy="{y:.1f}" r="4.5" '
                       f'fill="{colour}" stroke="var(--surface)" stroke-width="2" '
                       f'data-tip="{esc(tips[j][i] if isinstance(tips[0], list) else tips[i])}"/>')
        if end_labels and pts:
            x, y = pts[-1]
            out.append(f'<text class="dlabel" x="{x + 8:.1f}" y="{y + 4:.1f}">'
                       f'{_fmt(vals[-1])}{y_suffix}</text>')
    legend = [(name, SERIES[j % len(SERIES)]) for j, (name, _) in enumerate(series)] \
        if len(series) > 1 else None
    return _figure(title, caption, "".join(out), legend, table_html)


def hbars(title, caption, rows, *, suffix="%", table_html="", colors=None):
    """Horizontal bars for a ranked categorical list. rows: (label, value, tip)."""
    if not rows:
        return ""
    rowh, gap = 26, 8
    height = PAD_T + len(rows) * rowh + 20
    vmax = _nice_max(max(v for _, v, _ in rows) or 1)
    label_w = 128
    plot_w = W - label_w - 60
    out = []
    for i, (lab, val, tip) in enumerate(rows):
        y = PAD_T + i * rowh
        bh = min(18, rowh - gap)
        bwid = plot_w * (val / vmax)
        out.append(f'<text class="tick" x="{label_w - 10}" y="{y + bh / 2 + 4:.1f}" '
                   f'text-anchor="end" style="font-size:12px">{esc(lab)}</text>')
        r = min(4.0, bwid, bh / 2)
        if bwid > 0.6:
            d = (f"M{label_w},{y:.1f} L{label_w + bwid - r:.1f},{y:.1f} "
                 f"Q{label_w + bwid:.1f},{y:.1f} {label_w + bwid:.1f},{y + r:.1f} "
                 f"L{label_w + bwid:.1f},{y + bh - r:.1f} "
                 f"Q{label_w + bwid:.1f},{y + bh:.1f} {label_w + bwid - r:.1f},{y + bh:.1f} "
                 f"L{label_w},{y + bh:.1f} Z")
            out.append(f'<path class="mark" d="{d}" '
                       f'fill="{(colors or {}).get(lab, SERIES[0])}" data-tip="{esc(tip)}"/>')
        out.append(f'<text class="dlabel" x="{label_w + bwid + 8:.1f}" '
                   f'y="{y + bh / 2 + 4:.1f}">{_fmt(val)}{suffix}</text>')
    body = "".join(out)
    return (f'<figure><figcaption>{esc(title)}</figcaption>'
            f'<p class="cap">{caption}</p>'
            f'<svg viewBox="0 0 {W} {height}" role="img" aria-label="{esc(title)}">{body}</svg>'
            + (f"<details><summary>Show the numbers</summary>{table_html}</details>"
               if table_html else "") + "</figure>")


def tile(label, value, *, hero=False, note=""):
    cls = ' class="hero"' if hero else ""
    sub = f"<span>{esc(note)}</span>" if note else f"<span>{esc(label)}</span>"
    top = f"<span>{esc(label)}</span>" if note else ""
    return f'<div class="tile">{top}<b{cls}>{esc(value)}</b>{sub}</div>'
