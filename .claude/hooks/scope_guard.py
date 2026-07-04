#!/usr/bin/env python
"""PreToolUse file-scope guard for the branch+lock domain workflow (T-1).

Runs on Edit|Write|MultiEdit. Reads the current domain from
``.claude/active_domain`` (written by /start-domain, cleared by /merge-domain)
and blocks edits that fall outside that domain's allowed file scope (mirrors the
router table + game/<domain> layout of How To Be Human — Full Production).

Behaviour:
  - active_domain ABSENT  -> fail-open (allow) so setup/meta/doc tasks aren't
                             blocked, but print a warning to stderr.
  - active_domain PRESENT -> allow if the target path matches the domain's scope
                             or an always-allowed path; otherwise emit a
                             PreToolUse deny decision naming the domain + scope.

Robust to Windows paths. Root is resolved from this file's location, so cwd /
env quirks can't break it. This is pure stdlib (no engine/editor imports) so it
stays trivially runnable as a hook.
"""
import sys, os, json

# <root>/.claude/hooks/scope_guard.py  ->  root
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Domain -> list of allowed path globs (relative to repo root, forward slashes).
# New-layout mapping (D-10 domains): game/<domain>/** is the domain's game code,
# data/balancing/<domain>.json its tunables, data/schemas/<domain>.schema.json
# its schema. Cross-cutting allowances mirror the prototype's shared-file rule:
# buildings + enemies legitimately register into the shared game host (game/core),
# and the map domain owns the map files under data/maps.
DOMAIN_SCOPE = {
    "buildings": [
        "game/buildings/**",
        "data/balancing/buildings.json", "data/schemas/buildings.schema.json",
        "game/core/**",
    ],
    "enemies": [
        "game/enemies/**",
        "data/balancing/enemies.json", "data/schemas/enemies.schema.json",
        "game/core/**",
    ],
    "map": [
        "game/map/**",
        "data/balancing/map.json", "data/schemas/map.schema.json",
        "data/maps/**",
    ],
    "ui": [
        "game/ui/**",
        "data/balancing/ui.json", "data/schemas/ui.schema.json",
    ],
    "core": [
        "game/core/**",
        "data/balancing/core.json", "data/schemas/core.schema.json",
    ],
}

# Always allowed regardless of domain (meta / docs / fallback). The matcher only
# supports exact + '/**'-suffix forms, so the package docs are enumerated.
ALWAYS_ALLOWED = [
    ".claude/**",
    "CLAUDE.md",
    "engine/CLAUDE.md", "game/CLAUDE.md", "editor/CLAUDE.md", "data/CLAUDE.md",
]


def _norm(p):
    """Absolute path -> repo-relative, forward-slash, lower-cased for matching."""
    try:
        rel = os.path.relpath(os.path.abspath(p), ROOT)
    except ValueError:
        rel = p  # different drive — keep as-is
    rel = rel.replace("\\", "/")
    if rel.startswith("./"):  # strip a leading "./" only — NOT a leading dotdir
        rel = rel[2:]
    return rel.lower()


def _match(rel, pattern):
    pat = pattern.replace("\\", "/").lower()
    if pat.endswith("/**"):
        base = pat[:-3]
        return rel == base or rel.startswith(base + "/")
    return rel == pat


def _allow():
    sys.exit(0)  # silent allow — defer to the normal permission flow


def _deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        _allow()
        return

    tool_input = data.get("tool_input", {}) or {}
    path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not path:
        _allow()
        return

    rel = _norm(path)

    # Always-allowed paths bypass the domain gate.
    if any(_match(rel, p) for p in ALWAYS_ALLOWED):
        _allow()
        return

    domain_file = os.path.join(ROOT, ".claude", "active_domain")
    if not os.path.exists(domain_file):
        sys.stderr.write(
            "[scope_guard] No .claude/active_domain set — allowing edit "
            "(run /start-domain <domain> to scope this session).\n")
        _allow()
        return

    with open(domain_file, "r", encoding="utf-8") as fh:
        domain = fh.read().strip().lower()

    if not domain:
        sys.stderr.write(
            "[scope_guard] .claude/active_domain is blank — allowing "
            "(run /start-domain <domain> to scope this session).\n")
        _allow()
        return

    scope = DOMAIN_SCOPE.get(domain)
    if scope is None:
        sys.stderr.write(
            f"[scope_guard] Unknown domain '{domain}' in active_domain — allowing.\n")
        _allow()
        return

    if any(_match(rel, p) for p in scope):
        _allow()
        return

    _deny(
        f"Out of scope for the '{domain}' domain. '{rel}' is not in this domain's "
        f"allowed file scope: {', '.join(scope)}. Edit only your domain's files "
        f"(see CLAUDE.md). If the task truly spans domains, ask the user."
    )


if __name__ == "__main__":
    main()
