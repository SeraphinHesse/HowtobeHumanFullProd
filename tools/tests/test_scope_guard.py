"""T-1 enforcement: the PreToolUse scope guard allows in-domain edits and
denies out-of-domain ones based on .claude/active_domain.

The guard resolves the repo ROOT from its own file location and reads
<ROOT>/.claude/active_domain, so these tests drive it the way Claude Code does
— as a subprocess fed the PreToolUse JSON on stdin — and toggle the real
active_domain file (gitignored, normally absent), restoring it on cleanup.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".claude" / "hooks" / "scope_guard.py"
ACTIVE_DOMAIN = REPO / ".claude" / "active_domain"


def run_guard(file_path):
    """Feed a PreToolUse Edit payload to the guard; return (returncode, stdout)."""
    payload = json.dumps({
        "tool_name": "Edit",
        "tool_input": {"file_path": str(file_path)},
    })
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload, capture_output=True, text=True,
    )
    return result.returncode, result.stdout


def is_deny(stdout):
    if not stdout.strip():
        return False
    doc = json.loads(stdout)
    return (doc.get("hookSpecificOutput", {}).get("permissionDecision")
            == "deny")


class ScopeGuardCase(unittest.TestCase):
    """Sets active_domain around each test, restoring prior state on cleanup."""

    def set_domain(self, domain):
        prior = ACTIVE_DOMAIN.read_text(encoding="utf-8") \
            if ACTIVE_DOMAIN.exists() else None

        def restore():
            if prior is None:
                ACTIVE_DOMAIN.unlink(missing_ok=True)
            else:
                ACTIVE_DOMAIN.write_text(prior, encoding="utf-8")
        self.addCleanup(restore)
        if domain is None:
            ACTIVE_DOMAIN.unlink(missing_ok=True)
        else:
            ACTIVE_DOMAIN.write_text(domain, encoding="utf-8")


class TestFailOpen(ScopeGuardCase):
    def test_absent_active_domain_allows(self):
        self.set_domain(None)
        code, out = run_guard(REPO / "game" / "enemies" / "raider.py")
        self.assertEqual(code, 0)
        self.assertFalse(is_deny(out))

    def test_blank_active_domain_allows(self):
        self.set_domain("")  # cleared but present
        code, out = run_guard(REPO / "game" / "enemies" / "raider.py")
        self.assertFalse(is_deny(out))

    def test_unknown_domain_allows(self):
        self.set_domain("wizards")
        code, out = run_guard(REPO / "game" / "enemies" / "raider.py")
        self.assertFalse(is_deny(out))


class TestDomainScope(ScopeGuardCase):
    def test_in_domain_edit_allowed(self):
        self.set_domain("buildings")
        code, out = run_guard(REPO / "game" / "buildings" / "defender.py")
        self.assertEqual(code, 0)
        self.assertFalse(is_deny(out))

    def test_in_domain_balancing_allowed(self):
        self.set_domain("buildings")
        _, out = run_guard(REPO / "data" / "balancing" / "buildings.json")
        self.assertFalse(is_deny(out))

    def test_shared_core_allowed_for_buildings(self):
        self.set_domain("buildings")
        _, out = run_guard(REPO / "game" / "core" / "game.py")
        self.assertFalse(is_deny(out))

    def test_map_domain_owns_map_files(self):
        self.set_domain("map")
        _, out = run_guard(REPO / "data" / "maps" / "first_light.json")
        self.assertFalse(is_deny(out))

    def test_out_of_domain_edit_denied(self):
        self.set_domain("buildings")
        code, out = run_guard(REPO / "game" / "enemies" / "raider.py")
        self.assertEqual(code, 0)  # deny is signalled by JSON, not exit code
        self.assertTrue(is_deny(out))

    def test_out_of_domain_balancing_denied(self):
        self.set_domain("ui")
        _, out = run_guard(REPO / "data" / "balancing" / "core.json")
        self.assertTrue(is_deny(out))


class TestAlwaysAllowed(ScopeGuardCase):
    def test_dot_claude_always_allowed(self):
        self.set_domain("buildings")
        _, out = run_guard(REPO / ".claude" / "active_domain")
        self.assertFalse(is_deny(out))

    def test_root_claude_md_always_allowed(self):
        self.set_domain("buildings")
        _, out = run_guard(REPO / "CLAUDE.md")
        self.assertFalse(is_deny(out))

    def test_package_doc_always_allowed(self):
        self.set_domain("buildings")
        _, out = run_guard(REPO / "engine" / "CLAUDE.md")
        self.assertFalse(is_deny(out))


class TestMalformedInput(ScopeGuardCase):
    def test_no_path_allows(self):
        self.set_domain("buildings")
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps({"tool_input": {}}),
            capture_output=True, text=True,
        )
        self.assertFalse(is_deny(result.stdout))

    def test_unparseable_stdin_allows(self):
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not json", capture_output=True, text=True,
        )
        self.assertFalse(is_deny(result.stdout))


if __name__ == "__main__":
    unittest.main()
