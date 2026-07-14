"""Agent-dispatch form specs + handoff payloads (AD-1). Pure — stdlib and
engine.data_io only, no Qt/pygame — so it reads and writes through the
validating loader/writer exactly like an agent would, and stays in
`test_editor_viewport.TestPurity`.

Two data formats meet here:

- **form spec** — `data/agent_forms/<id>.json`, validated against
  `data/schemas/agent_form.schema.json` (the THIRD `tools/smoke.py`
  directory exception, so every committed spec is exit-gate checked for
  free). One spec per game thing-type; the editor renders its dialog from
  the spec, never from hardcoded widgets.
- **handoff** — `.claude/dispatch/<YYYYMMDD-HHMMSS>-<form-id>.json`
  (gitignored, transient agent I/O), validated against
  `data/schemas/dispatch_handoff.schema.json`. Written on submit, then read
  by the `/dispatch` skill, which sets up git and drives the target skill.

The dialog's free-text description box is built into the dialog, not a spec
field — every form gets it for free.
"""
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from engine import data_io

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DATA = REPO / "data"
FORMS_SUBDIR = "agent_forms"
SCHEMA_VERSION = 1

GIT_MODES = ("branch", "current")

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def _data_dir(data_dir=None):
    return Path(data_dir) if data_dir is not None else DEFAULT_DATA


def _repo(repo=None):
    return Path(repo) if repo is not None else REPO


def forms_dir(data_dir=None):
    """<data_dir>/agent_forms — no I/O, no mkdir."""
    return _data_dir(data_dir) / FORMS_SUBDIR


def _schema(name, data_dir=None):
    return _data_dir(data_dir) / "schemas" / name


def load_form_specs(data_dir=None):
    """Every form spec on disk, schema-validated, sorted by id.

    Read fresh on every call — a newly written spec shows up without an
    editor restart. Missing directory -> []. An invalid spec raises
    jsonschema.ValidationError (loud); an id that disagrees with its
    filename stem raises ValueError (the cross-check the schema cannot
    express — the engine/tilemap.py precedent).
    """
    directory = forms_dir(data_dir)
    if not directory.is_dir():
        return []
    schema = _schema("agent_form.schema.json", data_dir)
    specs = []
    for path in sorted(directory.glob("*.json")):
        spec = data_io.load_validated(path, schema)
        if spec["id"] != path.stem:
            raise ValueError(
                f"{path.name}: form id {spec['id']!r} != filename stem {path.stem!r}")
        specs.append(spec)
    return sorted(specs, key=lambda s: s["id"])


def slugify(text, max_len=32):
    """Branch-safe slug: lowercase ascii words joined by single dashes."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    slug = _NON_SLUG.sub("-", text).strip("-")
    if max_len is not None and len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug


def default_branch_name(spec, values, free_text):
    """agent/<form-id>-<slug>, slug from the spec's slug_field or the free text."""
    key = spec.get("slug_field", "name")
    slug = slugify((values or {}).get(key)) or slugify(free_text)
    return f"agent/{spec['id']}-{slug}" if slug else f"agent/{spec['id']}"


def _current_branch(repo=None):
    """Branch name from <repo>/.git/HEAD, or None. Pure file read, no subprocess.

    None on detached HEAD, on a worktree pointer file, or with no .git at all
    — which is why the handoff's `spawned_from` is optional: it is purely
    informational and a temp test repo has none.
    """
    head = _repo(repo) / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    prefix = "ref: refs/heads/"
    if text.startswith(prefix):
        return text[len(prefix):].strip() or None
    return None


def build_payload(spec, values, free_text, git_mode, branch=None, repo=None):
    """The dispatch_handoff payload for one form submission. Touches no disk."""
    if git_mode not in GIT_MODES:
        raise ValueError(f"git_mode must be one of {GIT_MODES}, got {git_mode!r}")
    values = dict(values or {})
    free_text = (free_text or "").strip()
    git = {"mode": git_mode, "base": "Development"}
    if git_mode == "branch":
        git["branch"] = branch or default_branch_name(spec, values, free_text)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "form_id": spec["id"],
        "skill": spec["skill"],
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "free_text": free_text,
        "values": values,
        "git": git,
        "context": list(spec.get("context", [])),
    }
    on = _current_branch(repo)
    if on:
        payload["spawned_from"] = {"branch": on}
    return payload


def dispatch_dir(repo=None):
    return _repo(repo) / ".claude" / "dispatch"


def write_handoff(payload, repo=None, data_dir=None):
    """Write the payload through write_validated; return the file path."""
    stamp = payload["created_at"].replace("-", "").replace(":", "")
    stamp = stamp.replace("T", "-").rstrip("Z")
    directory = dispatch_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{stamp}-{payload['form_id']}"
    path = directory / f"{stem}.json"
    n = 2
    while path.exists():
        path = directory / f"{stem}-{n}.json"
        n += 1
    data_io.write_validated(
        payload, path, _schema("dispatch_handoff.schema.json", data_dir))
    return path


def handoff_relpath(path, repo=None):
    """Repo-relative POSIX path — what `/dispatch <relpath>` consumes."""
    path = Path(path).resolve()
    root = _repo(repo).resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        raise ValueError(f"{path} is not inside the repo {root}") from None


def _prune(directory, cutoff):
    deleted = 0
    if not directory.is_dir():
        return 0
    for path in directory.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                deleted += 1
        except OSError:
            pass  # best-effort housekeeping; a locked file is not an error
    return deleted


def prune_done(repo=None, days=30, live_days=1):
    """Delete archived handoffs older than `days` and unconsumed live ones
    older than `live_days`. Returns how many files went. Never raises."""
    now = datetime.now(timezone.utc).timestamp()
    live = dispatch_dir(repo)
    return (_prune(live / "done", now - days * 86400)
            + _prune(live, now - live_days * 86400))
