"""
Tests for react_patterns.py — React anti-pattern checker.

Run with:  python3 -m pytest .claude/skills/code/react-patterns/scripts/test_react_patterns.py -v
Or from within this directory: python3 -m pytest test_react_patterns.py -v
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load the module under test (works regardless of cwd)
# ---------------------------------------------------------------------------
SCRIPT = Path(__file__).parent / "react_patterns.py"

spec = importlib.util.spec_from_file_location("react_patterns", SCRIPT)
react_patterns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(react_patterns)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_script(args=(), stdin_text=None):
    """Run react_patterns.py as a subprocess. Returns (returncode, stdout, stderr)."""
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def check(source: str) -> list[dict]:
    """Check source and return findings list."""
    return react_patterns.check_source(source)


def rules(source: str) -> list[str]:
    """Return just the rule names from findings."""
    return [f["rule"] for f in check(source)]


# ---------------------------------------------------------------------------
# INDEX_AS_KEY — HIGH
# ---------------------------------------------------------------------------


class TestIndexAsKey:
    def test_key_index_flagged(self):
        src = "{items.map((item, index) => <Item key={index} />)}"
        assert "INDEX_AS_KEY" in rules(src)

    def test_key_i_flagged(self):
        src = "{items.map((item, i) => <Item key={i} />)}"
        assert "INDEX_AS_KEY" in rules(src)

    def test_key_idx_flagged(self):
        src = "{items.map((item, idx) => <Item key={idx} />)}"
        assert "INDEX_AS_KEY" in rules(src)

    def test_key_numeric_literal_flagged(self):
        src = "<Item key={0} />"
        assert "INDEX_AS_KEY" in rules(src)

    def test_stable_key_clean(self):
        src = "{items.map(item => <Item key={item.id} />)}"
        assert "INDEX_AS_KEY" not in rules(src)

    def test_key_uuid_clean(self):
        src = "{items.map(item => <Item key={item.uuid} />)}"
        assert "INDEX_AS_KEY" not in rules(src)

    def test_severity_is_high(self):
        src = "{items.map((item, index) => <Item key={index} />)}"
        findings = [f for f in check(src) if f["rule"] == "INDEX_AS_KEY"]
        assert all(f["severity"] == "HIGH" for f in findings)

    def test_line_number_reported(self):
        src = "\n\n{items.map((item, index) => <Item key={index} />)}"
        findings = [f for f in check(src) if f["rule"] == "INDEX_AS_KEY"]
        assert findings[0]["line"] == 3


# ---------------------------------------------------------------------------
# MISSING_KEY — MEDIUM
# ---------------------------------------------------------------------------


class TestMissingKey:
    def test_map_without_key_flagged(self):
        src = (
            "{items.map(item => (\n" "  <div className='item'>{item.name}</div>\n" "))}"
        )
        assert "MISSING_KEY" in rules(src)

    def test_map_with_key_clean(self):
        src = (
            "{items.map(item => (\n"
            "  <div key={item.id} className='item'>{item.name}</div>\n"
            "))}"
        )
        assert "MISSING_KEY" not in rules(src)

    def test_map_without_jsx_clean(self):
        # .map that returns a string, not JSX — should not flag
        src = "{items.map(item => item.name)}"
        assert "MISSING_KEY" not in rules(src)

    def test_severity_is_medium(self):
        src = "{items.map(item => (\n" "  <div>{item.name}</div>\n" "))}"
        findings = [f for f in check(src) if f["rule"] == "MISSING_KEY"]
        assert all(f["severity"] == "MEDIUM" for f in findings)

    def test_missing_key_lookahead_constant(self):
        # Verify the lookahead window is 5 lines as documented
        assert react_patterns.MISSING_KEY_LOOKAHEAD_LINES == 5

    def test_key_within_window_clears_finding(self):
        # key= appears on a later line within the window
        src = (
            "{items.map(item => (\n"
            "  <UserCard\n"
            "    key={item.id}\n"
            "    name={item.name}\n"
            "  />\n"
            "))}"
        )
        assert "MISSING_KEY" not in rules(src)


# ---------------------------------------------------------------------------
# HOOK_IN_CONDITIONAL — HIGH
# ---------------------------------------------------------------------------


class TestHookInConditional:
    def test_use_state_in_if_flagged(self):
        src = (
            "function Comp({ show }) {\n"
            "  if (show) {\n"
            "    const [x, setX] = useState(0);\n"
            "  }\n"
            "  return null;\n"
            "}\n"
        )
        assert "HOOK_IN_CONDITIONAL" in rules(src)

    def test_use_effect_in_if_flagged(self):
        src = (
            "function Comp({ active }) {\n"
            "  if (active) {\n"
            "    useEffect(() => {}, []);\n"
            "  }\n"
            "  return null;\n"
            "}\n"
        )
        assert "HOOK_IN_CONDITIONAL" in rules(src)

    def test_hook_at_top_level_clean(self):
        src = (
            "function Comp() {\n"
            "  const [x, setX] = useState(0);\n"
            "  useEffect(() => {}, []);\n"
            "  return <div>{x}</div>;\n"
            "}\n"
        )
        assert "HOOK_IN_CONDITIONAL" not in rules(src)

    def test_severity_is_high(self):
        src = "if (flag) {\n" "  const x = useCustomHook();\n" "}\n"
        findings = [f for f in check(src) if f["rule"] == "HOOK_IN_CONDITIONAL"]
        assert all(f["severity"] == "HIGH" for f in findings)

    def test_hook_name_in_message(self):
        src = "if (show) {\n" "  const data = useFetch('/api');\n" "}\n"
        findings = [f for f in check(src) if f["rule"] == "HOOK_IN_CONDITIONAL"]
        assert findings, "Expected a HOOK_IN_CONDITIONAL finding"
        assert "useFetch" in findings[0]["message"]


# ---------------------------------------------------------------------------
# Sorting: HIGH before MEDIUM
# ---------------------------------------------------------------------------


class TestSortOrder:
    def test_high_before_medium(self):
        src = (
            "{items.map(item => <div>{item.name}</div>)}\n"  # MISSING_KEY MEDIUM
            "{items.map((item, index) => <div key={index}>{item.name}</div>)}\n"  # INDEX_AS_KEY HIGH
        )
        findings = check(src)
        severities = [f["severity"] for f in findings]
        high_indices = [i for i, s in enumerate(severities) if s == "HIGH"]
        medium_indices = [i for i, s in enumerate(severities) if s == "MEDIUM"]
        if high_indices and medium_indices:
            assert max(high_indices) < min(medium_indices)


# ---------------------------------------------------------------------------
# Empty and edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_source_no_findings(self):
        assert check("") == []

    def test_whitespace_only_no_findings(self):
        assert check("   \n\n   ") == []

    def test_clean_component_no_findings(self):
        src = (
            "export function UserList({ users }) {\n"
            "  const [selected, setSelected] = useState(null);\n"
            "  return (\n"
            "    <ul>\n"
            "      {users.map(user => (\n"
            "        <li key={user.id}>{user.name}</li>\n"
            "      ))}\n"
            "    </ul>\n"
            "  );\n"
            "}\n"
        )
        assert check(src) == []


# ---------------------------------------------------------------------------
# Script I/O via subprocess
# ---------------------------------------------------------------------------


class TestScriptSubprocess:
    def test_stdin_empty_exits_zero(self):
        rc, out, err = run_script(["-"], stdin_text="")
        assert rc == 0

    def test_stdin_valid_exits_zero(self):
        src = "{items.map((item, index) => <Item key={index} />)}\n"
        rc, out, err = run_script(["-"], stdin_text=src)
        assert rc == 0

    def test_stdout_contains_json_block(self):
        src = "{items.map((item, index) => <Item key={index} />)}\n"
        rc, out, err = run_script(["-"], stdin_text=src)
        json_text = out.split("\n\n")[0]
        data = json.loads(json_text)
        assert "findings" in data
        assert "summary" in data

    def test_stdout_contains_markdown_section(self):
        src = "{items.map((item, index) => <Item key={index} />)}\n"
        rc, out, err = run_script(["-"], stdin_text=src)
        assert "## React Anti-Pattern Findings" in out

    def test_file_not_found_exits_one(self):
        rc, out, err = run_script(["/nonexistent/Component.tsx"])
        assert rc == 1
        assert "ERROR" in err

    def test_summary_counts_correct(self):
        src = (
            "{items.map((item, index) => <Item key={index} />)}\n"  # HIGH
            "{items.map(item => <div>{item.name}</div>)}\n"  # MEDIUM
        )
        rc, out, err = run_script(["-"], stdin_text=src)
        json_text = out.split("\n\n")[0]
        data = json.loads(json_text)
        assert data["summary"]["high"] >= 1
        assert data["summary"]["medium"] >= 1

    def test_file_argument_works(self, tmp_path):
        f = tmp_path / "Component.tsx"
        f.write_text("{items.map((item, index) => <Item key={index} />)}\n")
        rc, out, err = run_script([str(f)])
        assert rc == 0
        json_text = out.split("\n\n")[0]
        data = json.loads(json_text)
        assert data["summary"]["high"] >= 1
