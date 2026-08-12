"""Tests for `.claude/quality-gates.json`: config must not claim behavior the
repo does not implement.

Background (see AUDIT-claims.md finding 3): the `gates` object (tests_pass,
lint_clean, build_success, type_check, format_check, unit_tests,
integration_tests) mapped to npm commands (`npm test`, `npm run lint`,
`npm run build`, ...). Two independent problems:

  1. Nothing in this repo reads `gates` -- the only consumer of this file,
     `tools/cc/src/cc/commands/eval.py::_load_threshold`, reads exactly one
     field: `eval.pass_rate_threshold`.
  2. Even a hypothetical future reader of `gates.<name>.command` would fail
     immediately: root `package.json` defines only one script
     (`generate-summary`) -- `npm test` / `npm run lint` / `npm run build`
     do not exist as scripts.

This repo is Python/shell, not a Node project with test/lint/build scripts,
so "wire the gates to something real" is not the honest fix here -- deleting
the dead keys is. This test enforces the invariant going forward: any
`gates.<name>.command` of the form `npm run <script>` (or the bare `npm
test`/`npm run test` form) must name a script that actually exists in
package.json, and the file must not carry keys nothing in the repo reads.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
QUALITY_GATES_JSON = REPO_ROOT / ".claude" / "quality-gates.json"
PACKAGE_JSON = REPO_ROOT / "package.json"


def _npm_script_name(command: str) -> str | None:
    """Extract the script name from an `npm test` / `npm run <script>` command.

    Returns None for commands that aren't npm-script invocations (e.g. a bare
    `tsc --noEmit`), which this check does not attempt to validate.
    """
    command = command.strip()
    if command in ("npm test", "npm t"):
        return "test"
    match = re.match(r"^npm run\s+([\w:.-]+)", command)
    if match:
        return match.group(1)
    return None


class TestQualityGatesConfigMatchesReality:
    def test_no_dead_gate_commands(self):
        """Every npm-script command any `gates` entry references must exist
        in package.json's `scripts`. This is the literal defect: the old
        `gates` block referenced `npm test`/`npm run lint`/`npm run build`
        while package.json defines only `generate-summary`. Passes vacuously
        (and correctly) once `gates` no longer references npm scripts that
        don't exist -- including the honest fix of removing `gates` entirely.
        """
        config = json.loads(QUALITY_GATES_JSON.read_text(encoding="utf-8"))
        pkg = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
        defined_scripts = set(pkg.get("scripts", {}).keys())

        gates = config.get("gates", {})
        broken = []
        for gate_name, gate in gates.items():
            command = gate.get("command", "")
            script = _npm_script_name(command)
            if script is not None and script not in defined_scripts:
                broken.append((gate_name, command))

        assert not broken, (
            f"quality-gates.json gate(s) reference npm scripts that don't "
            f"exist in package.json: {broken}. Defined scripts: {sorted(defined_scripts)}"
        )

    def test_no_unread_top_level_keys(self):
        """Every top-level key in quality-gates.json must be referenced by
        some consumer in the repo. `eval.pass_rate_threshold` is read by
        eval.py; a `gates`/`defaultGates` block that nothing reads is dead
        config that misleadingly implies automated enforcement exists.
        """
        config = json.loads(QUALITY_GATES_JSON.read_text(encoding="utf-8"))
        known_read_keys = {"version", "description", "eval"}
        unread = set(config.keys()) - known_read_keys
        assert not unread, (
            f"quality-gates.json has top-level key(s) {unread} not known to be "
            f"read by any consumer in the repo. If a new gate runner reads "
            f"these, add them to known_read_keys in this test; otherwise "
            f"remove them from the config."
        )

    def test_eval_pass_rate_threshold_is_still_the_real_consumed_field(self):
        """Regression guard: eval.py's actual consumer field must survive any
        edit to this file."""
        config = json.loads(QUALITY_GATES_JSON.read_text(encoding="utf-8"))
        assert "eval" in config
        assert "pass_rate_threshold" in config["eval"]
        assert isinstance(config["eval"]["pass_rate_threshold"], (int, float))

    def test_package_json_has_no_test_lint_build_scripts(self):
        """Documents *why* npm-command gates were wrong at the repo root:
        this is a Python/shell project, not a Node project with
        test/lint/build scripts. If this ever changes (scripts get added),
        wiring real gates to them becomes the honest option instead of
        deletion -- revisit this file's `gates` decision then."""
        pkg = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
        scripts = pkg.get("scripts", {})
        assert "test" not in scripts
        assert "lint" not in scripts
        assert "build" not in scripts


class TestQualityGatesConfigIsValidJson:
    def test_parses_as_json(self):
        json.loads(QUALITY_GATES_JSON.read_text(encoding="utf-8"))

    def test_eval_py_reads_the_same_file_this_test_checks(self):
        """Cross-check against the one real consumer: run `cc eval --help`-
        adjacent behavior indirectly by importing the loader function and
        confirming it resolves the threshold this file declares."""
        import sys

        sys.path.insert(0, str(REPO_ROOT / "tools" / "cc" / "src"))
        from cc.commands.eval import _load_threshold  # type: ignore

        threshold = _load_threshold(REPO_ROOT)
        config = json.loads(QUALITY_GATES_JSON.read_text(encoding="utf-8"))
        assert threshold == config["eval"]["pass_rate_threshold"]
