# Root conftest.py for the claude-copilot test suite.
#
# tests/tui/ is a vendored sub-project (claude_monitor) with its own CI
# and its own pyproject.toml [tool.pytest.ini_options] pointing at src/tests/.
# Collecting it here would pull in its fixtures, coverage gate (--cov-fail-under=70),
# and unrelated dependencies — so we exclude it entirely.
collect_ignore_glob = ["tests/tui/*", "tests/unit/*", "tests/integration/*"]
