"""
Tests for pytest_smell.py.

Run with:
  python3 -m pytest .claude/skills/testing/pytest-patterns/scripts/test_pytest_smell.py -v
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Load module under test
# ---------------------------------------------------------------------------
SCRIPT = Path(__file__).parent / "pytest_smell.py"

spec = importlib.util.spec_from_file_location("pytest_smell", SCRIPT)
pytest_smell = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pytest_smell)

analyze_source = pytest_smell.analyze_source
MAGIC_NUMBER_THRESHOLD = pytest_smell.MAGIC_NUMBER_THRESHOLD
SEV_ERROR = pytest_smell.SEV_ERROR
SEV_WARN = pytest_smell.SEV_WARN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_script(args=(), stdin_text=None):
    """Run pytest_smell.py as a subprocess; return (returncode, stdout, stderr)."""
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def findings_with_smell(source: str, smell_id: str) -> list[dict]:
    return [f for f in analyze_source(source) if f["smell_id"] == smell_id]


# ---------------------------------------------------------------------------
# SMELL-01: no_assert
# ---------------------------------------------------------------------------


class TestNoAssert:
    def test_detects_function_with_no_assertion(self):
        source = "def test_foo():\n    x = 1 + 1\n"
        hits = findings_with_smell(source, "SMELL-01")
        assert len(hits) == 1
        assert hits[0]["function"] == "test_foo"

    def test_passes_when_assert_present(self):
        source = "def test_foo():\n    assert 1 == 1\n"
        hits = findings_with_smell(source, "SMELL-01")
        assert hits == []

    def test_passes_with_pytest_raises(self):
        source = (
            "import pytest\n"
            "def test_foo():\n"
            "    with pytest.raises(ValueError):\n"
            "        raise ValueError('x')\n"
        )
        hits = findings_with_smell(source, "SMELL-01")
        assert hits == []

    def test_passes_with_unittest_assertequal(self):
        source = (
            "class TestBar:\n"
            "    def test_foo(self):\n"
            "        self.assertEqual(1, 1)\n"
        )
        hits = findings_with_smell(source, "SMELL-01")
        assert hits == []

    def test_no_false_positive_on_helper_function(self):
        # Non-test function without assertion should not trigger SMELL-01
        source = "def helper():\n    x = 1\n"
        hits = findings_with_smell(source, "SMELL-01")
        assert hits == []


# ---------------------------------------------------------------------------
# SMELL-02: bare_except
# ---------------------------------------------------------------------------


class TestBareExcept:
    def test_detects_bare_except(self):
        source = (
            "def test_foo():\n"
            "    try:\n"
            "        pass\n"
            "    except:\n"
            "        pass\n"
        )
        hits = findings_with_smell(source, "SMELL-02")
        assert len(hits) == 1

    def test_detects_except_exception(self):
        source = (
            "def test_foo():\n"
            "    try:\n"
            "        pass\n"
            "    except Exception:\n"
            "        assert False\n"
        )
        hits = findings_with_smell(source, "SMELL-02")
        assert len(hits) == 1

    def test_passes_with_reraise(self):
        source = (
            "def test_foo():\n"
            "    try:\n"
            "        pass\n"
            "    except Exception:\n"
            "        raise\n"
        )
        hits = findings_with_smell(source, "SMELL-02")
        assert hits == []

    def test_passes_with_specific_exception(self):
        source = (
            "def test_foo():\n"
            "    try:\n"
            "        pass\n"
            "    except ValueError:\n"
            "        pass\n"
        )
        hits = findings_with_smell(source, "SMELL-02")
        assert hits == []


# ---------------------------------------------------------------------------
# SMELL-04: magic_number
# ---------------------------------------------------------------------------


class TestMagicNumber:
    def test_threshold_constant_is_1000(self):
        """MAGIC_NUMBER_THRESHOLD is defined in the module, not guessed."""
        assert MAGIC_NUMBER_THRESHOLD == 1000

    def test_detects_large_magic_number_in_assert(self):
        source = "def test_foo():\n    assert result == 12345\n"
        hits = findings_with_smell(source, "SMELL-04")
        assert len(hits) == 1

    def test_no_flag_below_threshold(self):
        source = "def test_foo():\n    assert status == 200\n"
        hits = findings_with_smell(source, "SMELL-04")
        assert hits == []

    def test_boundary_at_threshold(self):
        # 1000 exactly should trigger
        source = "def test_foo():\n    assert val == 1000\n"
        hits = findings_with_smell(source, "SMELL-04")
        assert len(hits) == 1

    def test_boundary_just_below(self):
        # 999 should not trigger
        source = "def test_foo():\n    assert val == 999\n"
        hits = findings_with_smell(source, "SMELL-04")
        assert hits == []

    def test_negative_large_number_triggers(self):
        source = "def test_foo():\n    assert val == -5000\n"
        hits = findings_with_smell(source, "SMELL-04")
        assert len(hits) == 1


# ---------------------------------------------------------------------------
# SMELL-05: empty_test
# ---------------------------------------------------------------------------


class TestEmptyTest:
    def test_detects_pass_only(self):
        source = "def test_foo():\n    pass\n"
        hits = findings_with_smell(source, "SMELL-05")
        assert len(hits) == 1

    def test_detects_docstring_only(self):
        source = 'def test_foo():\n    """This will be implemented later."""\n'
        hits = findings_with_smell(source, "SMELL-05")
        assert len(hits) == 1

    def test_passes_with_real_code(self):
        source = "def test_foo():\n    assert True\n"
        hits = findings_with_smell(source, "SMELL-05")
        assert hits == []

    def test_empty_test_does_not_also_trigger_no_assert(self):
        """Empty test should report SMELL-05 only, not both SMELL-05 and SMELL-01."""
        source = "def test_foo():\n    pass\n"
        all_findings = analyze_source(source)
        smell_ids = {f["smell_id"] for f in all_findings}
        assert "SMELL-05" in smell_ids
        assert "SMELL-01" not in smell_ids


# ---------------------------------------------------------------------------
# SMELL-06: sleep_in_test
# ---------------------------------------------------------------------------


class TestSleepInTest:
    def test_detects_time_sleep(self):
        source = (
            "import time\n"
            "def test_foo():\n"
            "    time.sleep(1)\n"
            "    assert True\n"
        )
        hits = findings_with_smell(source, "SMELL-06")
        assert len(hits) == 1

    def test_detects_bare_sleep(self):
        source = (
            "from time import sleep\n"
            "def test_foo():\n"
            "    sleep(0.5)\n"
            "    assert True\n"
        )
        hits = findings_with_smell(source, "SMELL-06")
        assert len(hits) == 1

    def test_no_false_positive_without_sleep(self):
        source = "def test_foo():\n    assert True\n"
        hits = findings_with_smell(source, "SMELL-06")
        assert hits == []


# ---------------------------------------------------------------------------
# SMELL-07: print_in_test
# ---------------------------------------------------------------------------


class TestPrintInTest:
    def test_detects_print_call(self):
        source = "def test_foo():\n" "    print('debug')\n" "    assert True\n"
        hits = findings_with_smell(source, "SMELL-07")
        assert len(hits) == 1

    def test_no_false_positive_without_print(self):
        source = "def test_foo():\n    assert True\n"
        hits = findings_with_smell(source, "SMELL-07")
        assert hits == []


# ---------------------------------------------------------------------------
# SMELL-08: mock_only_assertions
# ---------------------------------------------------------------------------


class TestMockOnlyAssertions:
    def test_detects_sync_mock_only(self):
        source = (
            "from unittest.mock import Mock\n"
            "def test_foo():\n"
            "    db = Mock()\n"
            "    db.flush()\n"
            "    db.flush.assert_called_once()\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert len(hits) == 1
        assert hits[0]["function"] == "test_foo"

    def test_detects_async_mock_only(self):
        source = (
            "from unittest.mock import AsyncMock\n"
            "async def test_foo():\n"
            "    db = AsyncMock()\n"
            "    await db.flush()\n"
            "    db.flush.assert_awaited_once()\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert len(hits) == 1

    def test_detects_assert_has_calls(self):
        source = (
            "def test_foo():\n"
            "    db = Mock()\n"
            "    db.flush.assert_has_calls([call(1), call(2)])\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert len(hits) == 1

    def test_no_false_positive_when_all_mock_assertions_negative(self):
        # assert_not_called / assert_not_awaited alone is legitimate — it's
        # the only observable for "no write occurred" on a deny path.
        source = (
            "def test_foo():\n"
            "    db = Mock()\n"
            "    create_requests = Mock()\n"
            "    create_requests.assert_not_called()\n"
            "    db.commit.assert_not_called()\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert hits == []

    def test_no_false_positive_with_real_assertion_alongside_mock(self):
        # A mock-call assertion alongside a real assertion is fine.
        source = (
            "def test_foo():\n"
            "    db = Mock()\n"
            "    result = 5\n"
            "    assert result == 5\n"
            "    db.flush.assert_called_once()\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert hits == []

    def test_no_false_positive_with_pytest_raises_alongside_mock(self):
        source = (
            "import pytest\n"
            "def test_foo():\n"
            "    db = Mock()\n"
            "    with pytest.raises(ValueError):\n"
            "        raise ValueError('x')\n"
            "    db.flush.assert_called_once()\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert hits == []

    def test_no_false_positive_with_unittest_style_assertion(self):
        # unittest.TestCase-style assertEqual is a real assertion, not a
        # mock-call verification — must not collide with MOCK_ASSERT_METHODS.
        source = (
            "class TestFoo:\n"
            "    def test_foo(self):\n"
            "        db = Mock()\n"
            "        self.assertEqual(1, 1)\n"
            "        db.flush.assert_called_once()\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert hits == []

    def test_no_false_positive_on_test_with_no_mocks_at_all(self):
        source = "def test_foo():\n    assert 1 == 1\n"
        hits = findings_with_smell(source, "SMELL-08")
        assert hits == []

    def test_mixed_positive_and_negative_mock_assertions_still_fires(self):
        # Every assertion is mock-call, and at least one is positive.
        source = (
            "def test_foo():\n"
            "    db = Mock()\n"
            "    db.flush.assert_called_once()\n"
            "    db.commit.assert_not_called()\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert len(hits) == 1

    def test_severity_is_warn(self):
        source = (
            "def test_foo():\n"
            "    db = Mock()\n"
            "    db.flush.assert_called_once()\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert hits[0]["severity"] == SEV_WARN

    # -----------------------------------------------------------------------
    # E1: DB-session scoping — a mock-call verification only counts toward
    # firing when the mock's ROLE is a DB session (session verb or
    # db/session/sess/conn/connection variable name). A mocked HTTP client,
    # logger, or event publisher is a legitimate observable in its own right
    # and must NOT fire — this is the v2 narrowing from v1's "any mock".
    # These tests fail if someone reverts to v1 "any mock" behavior.
    # -----------------------------------------------------------------------

    def test_no_false_positive_on_mocked_http_client(self):
        # E1: an outbound HTTP client mock is a legitimate, owned boundary —
        # neither its variable name nor "post" is a DB-session signal.
        source = (
            "def test_foo():\n"
            "    http_client = Mock()\n"
            "    send_notification()\n"
            "    http_client.post.assert_called_once()\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert hits == []

    def test_no_false_positive_on_mocked_logger(self):
        # E1: a logger mock is a legitimate observable, not a DB session —
        # neither "logger" nor "warning" is a session signal.
        source = (
            "def test_foo():\n"
            "    logger = Mock()\n"
            "    do_thing()\n"
            "    logger.warning.assert_called_once()\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert hits == []

    def test_no_false_positive_on_mocked_event_publisher(self):
        # E1: an event publisher mock is a legitimate observable, not a DB
        # session — neither "publisher" nor "publish" is a session signal.
        source = (
            "def test_foo():\n"
            "    publisher = Mock()\n"
            "    emit_event()\n"
            "    publisher.publish.assert_called_once()\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert hits == []

    def test_no_false_positive_when_session_positive_alongside_other_mock_positive(
        self,
    ):
        # E1: a positive non-session mock verification (e.g. an event
        # publisher) is a legitimate observable in its own right — it
        # blocks firing exactly like a real assertion would, even when a
        # positive session-mock verification is also present.
        source = (
            "def test_foo():\n"
            "    db = Mock()\n"
            "    publisher = Mock()\n"
            "    db.commit.assert_called_once()\n"
            "    publisher.publish.assert_called_once()\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert hits == []

    # -----------------------------------------------------------------------
    # E2: tautological assertions — an assertion that reads back a value the
    # test itself supplied is NON-REDEEMING: it does not block firing (does
    # not count as "real"). These tests fail if the v2 tautology detection
    # is reverted/removed, since the tautological assertion would then be
    # misclassified as "real" and block SMELL-08 from firing.
    # -----------------------------------------------------------------------

    def test_detects_tautological_simplenamespace_readback(self):
        # E2 case (a): reading an attribute off a SimpleNamespace the test
        # built inline, compared to a literal the test itself supplied, is
        # tautological — it does not block firing alongside a positive
        # session-mock verification.
        source = (
            "from types import SimpleNamespace\n"
            "def test_foo():\n"
            "    db = Mock()\n"
            "    conversation = SimpleNamespace(capture_notes='Draft notes')\n"
            "    db.commit.assert_called_once()\n"
            "    assert conversation.capture_notes == 'Draft notes'\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert len(hits) == 1

    def test_detects_tautological_mock_container_readback(self):
        # E2 case (a): the same read-back tautology, but the test-only
        # container is a plain Mock() rather than a SimpleNamespace.
        source = (
            "def test_foo():\n"
            "    db = Mock()\n"
            "    fake_record = Mock()\n"
            "    fake_record.status = 'draft'\n"
            "    db.flush.assert_called_once()\n"
            "    assert fake_record.status == 'draft'\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert len(hits) == 1

    def test_detects_tautological_roundtrip_identity(self):
        # E2 case (b): `assert result is conversation` where `result` was
        # assigned from a call that itself received `conversation` (or an
        # attribute of it) as an argument — this only proves the test got
        # back the object it fed in, not that any field was computed
        # correctly. Non-redeeming — does not block firing.
        source = (
            "from types import SimpleNamespace\n"
            "async def test_foo():\n"
            "    db = Mock()\n"
            "    conversation = SimpleNamespace(id=1)\n"
            "    result = await service.update_conversation(db, conversation.id)\n"
            "    db.commit.assert_called_once()\n"
            "    assert result is conversation\n"
        )
        hits = findings_with_smell(source, "SMELL-08")
        assert len(hits) == 1


# ---------------------------------------------------------------------------
# SMELL-09: bare_mock_truthiness
# ---------------------------------------------------------------------------


class TestBareMockTruthiness:
    def test_detects_bare_called_truthiness(self):
        source = (
            "def test_foo():\n"
            "    mock_db = Mock()\n"
            "    do_write()\n"
            "    assert mock_db.commit.called\n"
        )
        hits = findings_with_smell(source, "SMELL-09")
        assert len(hits) == 1
        assert hits[0]["function"] == "test_foo"

    def test_detects_bare_call_count_truthiness(self):
        source = (
            "def test_foo():\n"
            "    mock_db = Mock()\n"
            "    do_write()\n"
            "    assert mock_db.add.call_count\n"
        )
        hits = findings_with_smell(source, "SMELL-09")
        assert len(hits) == 1

    def test_no_false_positive_on_negative_bare_truthiness(self):
        # `assert not x.called` is the legitimate equivalent of
        # `.assert_not_called()` — not flagged.
        source = (
            "def test_foo():\n"
            "    mock_db = Mock()\n"
            "    do_thing()\n"
            "    assert not mock_db.commit.called\n"
        )
        hits = findings_with_smell(source, "SMELL-09")
        assert hits == []

    def test_no_false_positive_on_call_count_comparison(self):
        # A real comparison (exact count) is informative, not bare
        # truthiness — not flagged.
        source = (
            "def test_foo():\n"
            "    mock_db = Mock()\n"
            "    do_write()\n"
            "    assert mock_db.commit.call_count == 2\n"
        )
        hits = findings_with_smell(source, "SMELL-09")
        assert hits == []

    def test_no_false_positive_on_assert_called_once(self):
        source = (
            "def test_foo():\n"
            "    mock_db = Mock()\n"
            "    do_write()\n"
            "    mock_db.commit.assert_called_once()\n"
        )
        hits = findings_with_smell(source, "SMELL-09")
        assert hits == []

    def test_evades_smell_08_when_alone(self):
        # Documents the exact evasion QA found: a bare `.called` truthiness
        # check is classified as "real" by SMELL-08's assertion classifier
        # (it's not an ast.Compare node), so it blocks SMELL-08 from firing
        # even though it verifies nothing about call shape. SMELL-09 is
        # what catches this case; SMELL-08 must not be made to fire here.
        source = (
            "def test_foo():\n"
            "    db = Mock()\n"
            "    do_write()\n"
            "    assert db.commit.called\n"
        )
        smell_08_hits = findings_with_smell(source, "SMELL-08")
        smell_09_hits = findings_with_smell(source, "SMELL-09")
        assert smell_08_hits == []
        assert len(smell_09_hits) == 1

    def test_severity_is_warn(self):
        source = (
            "def test_foo():\n"
            "    mock_db = Mock()\n"
            "    do_write()\n"
            "    assert mock_db.commit.called\n"
        )
        hits = findings_with_smell(source, "SMELL-09")
        assert hits[0]["severity"] == SEV_WARN


# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------


class TestSeverityLevels:
    def test_no_assert_is_error(self):
        source = "def test_foo():\n    x = 1\n"
        hits = findings_with_smell(source, "SMELL-01")
        assert hits[0]["severity"] == SEV_ERROR

    def test_empty_test_is_error(self):
        source = "def test_foo():\n    pass\n"
        hits = findings_with_smell(source, "SMELL-05")
        assert hits[0]["severity"] == SEV_ERROR

    def test_sleep_is_warn(self):
        source = (
            "import time\n"
            "def test_foo():\n"
            "    time.sleep(1)\n"
            "    assert True\n"
        )
        hits = findings_with_smell(source, "SMELL-06")
        assert hits[0]["severity"] == SEV_WARN

    def test_bare_except_is_warn(self):
        source = (
            "def test_foo():\n"
            "    try:\n"
            "        pass\n"
            "    except:\n"
            "        pass\n"
        )
        hits = findings_with_smell(source, "SMELL-02")
        assert hits[0]["severity"] == SEV_WARN


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------


class TestOutputStructure:
    def test_json_block_present_in_stdout(self):
        rc, stdout, _ = run_script(stdin_text="def test_foo():\n    pass\n")
        assert rc == 0
        # First block should be parseable JSON
        json_part = stdout.split("\n\n")[0]
        data = json.loads(json_part)
        assert "findings" in data
        assert "summary" in data

    def test_markdown_section_present(self):
        rc, stdout, _ = run_script(stdin_text="def test_foo():\n    pass\n")
        assert rc == 0
        assert "## pytest Test Smell Report" in stdout

    def test_summary_counts_correct(self):
        source = (
            "def test_foo():\n    pass\n"  # SMELL-05 ERROR
            "def test_bar():\n    x = 1\n"  # SMELL-01 ERROR
            "import time\n"
            "def test_baz():\n    time.sleep(1)\n    assert True\n"  # SMELL-06 WARN
        )
        rc, stdout, _ = run_script(stdin_text=source)
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        assert data["summary"]["error"] >= 2
        assert data["summary"]["warn"] >= 1

    def test_empty_input_exits_0(self):
        rc, stdout, _ = run_script(stdin_text="")
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        assert data["summary"]["total"] == 0

    def test_empty_input_produces_no_findings(self):
        rc, stdout, _ = run_script(stdin_text="")
        data = json.loads(stdout.split("\n\n")[0])
        assert data["findings"] == []


# ---------------------------------------------------------------------------
# stdin and file-path argument parsing
# ---------------------------------------------------------------------------


class TestInputModes:
    def test_stdin_dash_arg(self, tmp_path):
        """Passing '-' explicitly reads stdin."""
        rc, stdout, _ = run_script(
            args=["-"],
            stdin_text="def test_foo():\n    pass\n",
        )
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        assert data["summary"]["total"] >= 1

    def test_file_path_arg(self, tmp_path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_foo():\n    pass\n")
        rc, stdout, _ = run_script(args=[str(test_file)])
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        assert data["summary"]["total"] >= 1

    def test_invalid_file_exits_1(self):
        rc, _, stderr = run_script(args=["/nonexistent/path/test_x.py"])
        assert rc == 1
        assert "ERROR" in stderr

    def test_non_python_file_exits_1(self, tmp_path):
        f = tmp_path / "test_file.txt"
        f.write_text("not python")
        rc, _, stderr = run_script(args=[str(f)])
        assert rc == 1
        assert "ERROR" in stderr

    def test_directory_walks_test_files(self, tmp_path):
        (tmp_path / "test_a.py").write_text("def test_foo():\n    pass\n")
        (tmp_path / "helper.py").write_text("def helper():\n    pass\n")
        rc, stdout, _ = run_script(args=[str(tmp_path)])
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        # Only test_a.py is analyzed (helper.py is skipped)
        assert data["summary"]["files_analyzed"] == 1
