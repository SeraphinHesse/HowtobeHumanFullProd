"""The editor's test-run REPORT writer — Qt-free, pygame-free (TestRunnerPLAN TR-4).

What this module is: a pure serializer. It turns one ``editor.test_runner``
``RunResult`` into a durable pair of files under ``.claude/testruns/`` (a `.json`
for machines, a `.md` for humans) plus one block of paste-at-Claude text. It
renders nothing, launches nothing, and imports no Qt — which is what puts its
tests in the fast ``core`` tier and lets TR-5 call it from a worker thread.

Four rules, none decorative:

1. **THIS MODULE NEVER INVENTS A VERDICT.** ``gate_line`` is copied verbatim
   from the result or written as ``null``. ``editor/test_runner.py`` populates it
   only from a real ``GATE …`` line, and never for a per-area re-run (D2). A
   re-run report therefore says *"this is not a gate"* in words — never a blank
   line that reads like a missing verdict.

2. **EVERY READ OF THE RESULT GOES THROUGH ``_get``.** TR-3 owns the result
   contract; if a field is renamed there, the fix is one function here and
   nowhere else. ``_get`` reads an object OR a mapping, so the tests drive plain
   dicts and never import the run engine.

3. **REPORTS ARE NOT ``data/`` CONTENT.** They do NOT go through
   ``engine.data_io.write_validated`` and get no ``data/schemas/`` entry: a
   report is gitignored agent scratch, not a schema-gated asset. It is still
   written deterministically (sorted keys, 2-space indent, trailing newline) so
   two reports of the same run are byte-comparable.

4. **A RUN ALWAYS LEAVES SOMETHING BEHIND.** Green, red, or cancelled, both
   files are written and ``agent_prompt`` returns usable text — never ``""``,
   never a raise.

Purity: stdlib only, plus a GUARDED import of ``tools.test_domains`` for display
labels. Guarded on purpose — a label lookup must never be the thing that stops a
report from being written. In ``test_editor_viewport.TestPurity``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

try:  # display labels only — never load-bearing (see the module docstring)
    from tools.test_domains import DOMAIN_LABELS as _DOMAIN_LABELS
except Exception:  # pragma: no cover - defensive; the table is normally present
    _DOMAIN_LABELS = {}

REPO = Path(__file__).resolve().parents[1]

#: Report FORMAT version. Not a data/ schema version — reports are not data/.
SCHEMA_VERSION = 1

#: Node-IDs listed inline in the agent prompt before it says "and N more".
PROMPT_NODEID_CAP = 8

_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"


# --------------------------------------------------------------------------
# The ONE result accessor
# --------------------------------------------------------------------------

def _get(obj, name, default=None):
    """Read ``name`` off an object OR a mapping; missing/None -> ``default``.

    The single seam between this module and TR-3's ``RunResult``. Keep it that
    way: a contract change must stay a one-function edit.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        value = obj.get(name, default)
    else:
        value = getattr(obj, name, default)
    return default if value is None else value


def _get_maybe_none(obj, name):
    """Like :func:`_get` but preserves an explicit ``None`` (gate_line, total)."""
    if obj is None:
        return None
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _iso(value):
    """Epoch float, ``datetime``, or an ISO-Z string -> ``YYYY-MM-DDTHH:MM:SSZ``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        stamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc).strftime(_TIME_FMT)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), timezone.utc).strftime(_TIME_FMT)
    return str(value)


def _stamp(iso_text):
    """``2026-08-13T09:47:38Z`` -> ``20260813-094738`` (agent_forms.py:146-147)."""
    if not iso_text:
        iso_text = datetime.now(timezone.utc).strftime(_TIME_FMT)
    text = str(iso_text).replace("-", "").replace(":", "")
    return text.replace("T", "-").rstrip("Z")


def label_for(key, override=None):
    """Display label for a domain key: the result's own, then TR-1, then a guess."""
    if override:
        return str(override)
    return _DOMAIN_LABELS.get(key) or str(key).replace("_", " ").title()


def _domain_order(keys):
    """TR-1's row order first, then anything else alphabetically (stable rows)."""
    known = [k for k in _DOMAIN_LABELS if k in keys]
    extra = sorted(k for k in keys if k not in _DOMAIN_LABELS)
    return known + extra


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

def _repo(repo=None):
    return Path(repo) if repo is not None else REPO


def testruns_dir(repo=None):
    """``<repo>/.claude/testruns`` — no I/O, no mkdir (agent_forms.py:140)."""
    return _repo(repo) / ".claude" / "testruns"


# --------------------------------------------------------------------------
# The report document
# --------------------------------------------------------------------------

def _failure_dict(failure):
    """One TR-3 ``Failure`` -> one report record.

    ``kind`` is TR-3's vocabulary verbatim (``failed`` | ``subfailed`` |
    ``unexpected_skip``); there is no ``error`` kind — testgate's ``ERROR``
    buckets as ``failed`` upstream and must not be re-invented here.
    """
    return {
        "nodeid": str(_get(failure, "nodeid", "")),
        "module": str(_get(failure, "module", "")),
        "domain": str(_get(failure, "domain", "")),
        "kind": str(_get(failure, "kind", "failed")),
        "params": str(_get(failure, "params", "")),
        "message": str(_get(failure, "message", "")),
    }


def build_report(result):
    """The report document for one ``RunResult``. Pure — no I/O.

    Split out from :func:`write_report` so the round-trip test can compare
    structures without touching disk.
    """
    domain = _get_maybe_none(result, "domain")
    is_gate_run = domain is None

    failures = sorted(
        (_failure_dict(f) for f in _get(result, "failures", ()) or ()),
        key=lambda f: (f["nodeid"], f["params"], f["kind"]))

    skips_by_domain = {}
    fails_by_domain = {}
    for failure in failures:
        bucket = (skips_by_domain if failure["kind"] == "unexpected_skip"
                  else fails_by_domain)
        bucket[failure["domain"]] = bucket.get(failure["domain"], 0) + 1

    domains = {}
    for key, dom in (_get(result, "domains", {}) or {}).items():
        domains[key] = {
            "label": label_for(key, _get_maybe_none(dom, "label")),
            "state": str(_get(dom, "state", "pending")),
            "done": int(_get(dom, "done", 0)),
            "total": _get_maybe_none(dom, "total"),
            "passed": int(_get(dom, "passed", 0)),
            "failed": int(_get(dom, "failed", 0)),
            "subfailed": int(_get(dom, "subfailed", 0)),
            "skipped": int(_get(dom, "skipped", 0)),
            "unexpected_skips": skips_by_domain.get(key, 0),
            "modules": sorted(str(m) for m in _get(dom, "modules", ()) or ()),
        }

    totals = {
        "ran": int(_get(result, "total_ran", 0))
               or sum(d["done"] for d in domains.values()),
        "done": sum(d["done"] for d in domains.values()),
        "passed": sum(d["passed"] for d in domains.values()),
        "failed": sum(d["failed"] for d in domains.values()),
        "subfailed": sum(d["subfailed"] for d in domains.values()),
        "skipped": sum(d["skipped"] for d in domains.values()),
        "unexpected_skips": sum(d["unexpected_skips"] for d in domains.values()),
    }

    started_at = _iso(_get_maybe_none(result, "started_at"))
    finished_at = _iso(_get_maybe_none(result, "finished_at"))
    duration = _get_maybe_none(result, "duration_s")
    verdict = str(_get(result, "verdict", "error"))

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "gate" if is_gate_run else "domain",
        # Filled in by write_report once the path exists; the key is ALWAYS
        # present so a consumer can index it on an unwritten report too.
        "report_path": None,
        "domain": domain,
        # Verbatim or null. A per-area re-run is NOT a gate (D2), and TR-3
        # already guarantees None there — this never re-derives a verdict line.
        "gate_line": _get_maybe_none(result, "gate_line"),
        "verdict": verdict,
        "passed": verdict == "pass",
        "completed": bool(_get(result, "completed", False)),
        "cancelled": bool(_get(result, "cancelled", False)),
        "returncode": _get_maybe_none(result, "returncode"),
        "command": [str(c) for c in _get(result, "command", ()) or ()],
        "stream_command": [str(c) for c in _get(result, "stream_command", ()) or ()],
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_s": float(duration) if duration is not None else None,
        "totals": totals,
        "domains": domains,
        "failures": failures,
        "unknown_modules": sorted(
            str(m) for m in _get(result, "unknown_modules", ()) or ()),
        "raw_tail": [str(line) for line in _get(result, "raw_tail", ()) or ()],
    }


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def _duration_text(seconds):
    if seconds is None:
        return "unknown duration"
    seconds = float(seconds)
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m {int(seconds % 60):02d}s"


def _headline(report):
    """The one line under the title. NEVER blank — a missing gate line is said
    out loud, because a blank there reads like a verdict that got lost."""
    if report["kind"] == "domain":
        label = label_for(report["domain"])
        return f"**Re-run of one area ({label}) — this is not a gate.**"
    if report["cancelled"]:
        return "**Run cancelled — no verdict. This is not a gate.**"
    if report["gate_line"]:
        return f"**{report['gate_line']}**"
    return "**No gate line — the run did not finish. This is not a gate.**"


def render_markdown(report):
    """The human-readable ``.md`` body for a report dict. No I/O."""
    lines = [f"# Test run — {report['finished_at'] or 'unknown time'}", ""]
    lines.append(
        f"{_headline(report)}  ·  verdict `{report['verdict']}`  ·  "
        f"{_duration_text(report['duration_s'])}")
    if report.get("report_path"):
        lines.append(f"Report: `{report['report_path']}`")
    lines.append("")
    lines.append("| Area | Ran | Failed | Sub-failed | Skipped | Unexpected skips |")
    lines.append("|---|---|---|---|---|---|")
    for key in _domain_order(report["domains"]):
        d = report["domains"][key]
        failed = f"**{d['failed']}**" if d["failed"] else "0"
        lines.append(
            f"| {d['label']} | {d['done']} | {failed} | {d['subfailed']} | "
            f"{d['skipped']} | {d['unexpected_skips']} |")
    lines.append("")

    if not report["failures"]:
        lines.append("No failures.")
        lines.append("")
    else:
        lines.append("## Failures")
        lines.append("")
        by_domain = {}
        for failure in report["failures"]:
            by_domain.setdefault(failure["domain"], []).append(failure)
        for key in _domain_order(by_domain):
            lines.append(f"### {label_for(key)}")
            for failure in by_domain[key]:
                nodeid = failure["nodeid"] + failure["params"]
                suffix = "" if failure["kind"] == "failed" else f" ({failure['kind']})"
                lines.append(f"- `{nodeid}`{suffix}")
                if failure["message"]:
                    lines.append(f"  - {failure['message']}")
            lines.append("")
        if report["raw_tail"]:
            lines.append(f"## Output tail ({len(report['raw_tail'])} lines)")
            lines.append("")
            lines.append("```")
            lines.extend(report["raw_tail"])
            lines.append("```")
            lines.append("")

    if report["unknown_modules"]:
        lines.append("## Test modules in no known domain")
        lines.append("")
        for module in report["unknown_modules"]:
            lines.append(f"- `{module}` — add it to `tools/test_domains.py`.")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


# --------------------------------------------------------------------------
# Writing + reading
# --------------------------------------------------------------------------

def report_relpath(path, repo=None):
    """Repo-relative POSIX path, falling back to the absolute one.

    Unlike ``agent_forms.handoff_relpath`` this never raises: a report is
    scratch, and a prompt with a long path beats a prompt that blew up.
    """
    path = Path(path).resolve()
    try:
        return path.relative_to(_repo(repo).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _dumps(report):
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def write_report(result, repo=None):
    """Write ``<stamp>.json`` + ``<stamp>.md`` under ``.claude/testruns/``.

    Returns the ``.json`` path. A name collision suffixes ``-2``, ``-3``, … on
    BOTH files, so the pair always shares a stem.
    """
    report = build_report(result)
    directory = testruns_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)

    stem = _stamp(report["finished_at"])
    path = directory / f"{stem}.json"
    n = 2
    while path.exists() or path.with_suffix(".md").exists():
        path = directory / f"{stem}-{n}.json"
        n += 1

    report["report_path"] = report_relpath(path, repo)
    path.write_text(_dumps(report), encoding="utf-8")
    path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")

    # TR-6 inserts the ledger record here: a COMPLETED full run only —
    # report["kind"] == "gate" and report["completed"] and not
    # report["cancelled"] and report["gate_line"] is not None.
    return path


def load_report(path):
    """``json.loads`` of a written report."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# The agent prompt
# --------------------------------------------------------------------------

def _failing_areas(report):
    """[(label, count)] per domain with failures, in row order. Counts FAILURES,
    not tests — an unexpected skip is a failure the designer must see."""
    counts = {}
    for failure in report["failures"]:
        counts[failure["domain"]] = counts.get(failure["domain"], 0) + 1
    return [(label_for(k), counts[k]) for k in _domain_order(counts)]


def agent_prompt(path, repo=None):
    """The paste-at-Claude text for a report ON DISK. Never empty, never raises.

    Built by READING the `.json` so a report stays actionable days later. It
    names the report path and the failing areas, caps the node-ID list, and
    carries NO tracebacks — those live in the report.
    """
    report = load_report(path)
    json_rel = report.get("report_path") or report_relpath(path, repo)
    md_rel = json_rel[:-5] + ".md" if json_rel.endswith(".json") else json_rel

    out = []
    if report["kind"] == "domain":
        out.append(
            f"The editor re-ran one area ({label_for(report['domain'])}). "
            "This is NOT a gate.")
    elif report["cancelled"]:
        out.append("The editor's test run was CANCELLED before it finished. "
                   "This is NOT a gate.")
    elif report["passed"]:
        out.append("The editor ran the test suite. It passed.")
    else:
        out.append("The editor ran the test suite. It failed.")
    out.append("")

    if report["gate_line"]:
        out.append(f"  {report['gate_line']}")
        out.append("")

    out.append("Report (JSON + Markdown, gitignored):")
    out.append(f"  {json_rel}")
    out.append(f"  {md_rel}")
    out.append("")

    areas = _failing_areas(report)
    if areas:
        out.append("Failing areas: "
                   + ", ".join(f"{label} ({n} failed)" for label, n in areas) + ".")
        out.append("")
        out.append("Failing tests:")
        nodeids = [f["nodeid"] + f["params"] for f in report["failures"]]
        for nodeid in nodeids[:PROMPT_NODEID_CAP]:
            out.append(f"  {nodeid}")
        if len(nodeids) > PROMPT_NODEID_CAP:
            out.append(f"  ... and {len(nodeids) - PROMPT_NODEID_CAP} more "
                       "(full list + messages in the report)")
        out.append("")
        out.append(
            "Please read the report, fix the failures, and re-check with a "
            "targeted run over the files you touched. Which tests you may run "
            "is role-scoped — root CLAUDE.md §\"Test Suite Policy\" is the "
            "only authority. Do not re-run the whole suite to reproduce this.")
    elif report["kind"] == "gate" and report["passed"]:
        out.append("Nothing to fix. This run is the handoff gate for this "
                   "working tree.")
    else:
        out.append("No failures were recorded. If that looks wrong, the run did "
                   "not finish — check the report's raw output tail before "
                   "trusting it.")

    if report["unknown_modules"]:
        out.append("")
        out.append("Test modules in no known domain (add them to "
                   "tools/test_domains.py): "
                   + ", ".join(report["unknown_modules"]) + ".")

    return "\n".join(out).rstrip("\n") + "\n"
