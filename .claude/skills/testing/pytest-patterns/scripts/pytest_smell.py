#!/usr/bin/env python3
"""
pytest_smell.py — L3 executable for the pytest-patterns skill.

Analyzes a Python test file (or all test files in a directory) for
deterministic test smells. Prose judgment (is the test design good?) stays
in the L2 SKILL.md; this script handles only pattern-matchable rules.

Input (file path as first arg, or '-'/no-arg for stdin):
  Python source text of one test file  — OR —
  A directory path: walks all test_*.py / *_test.py files under it.

Output (stdout):
  1. Ranked JSON object with `findings` list and `summary`.
  2. Human-readable markdown section.

Exit codes:
  0 — success (including zero findings, including empty input)
  1 — invalid input (file not found, not a .py file when checking single file,
      unreadable content)

Smell rules (each cites the authoritative reason for the threshold):
  SMELL-01  no_assert          — test function body has no assert/pytest.raises/
                                  assertRaises call.  A test without an assertion
                                  can never fail; it provides no value.
                                  (Source: pytest docs "assert" section; xUnit
                                  Patterns §4 "Assertion-Free Test" smell)
  SMELL-02  bare_except        — bare `except:` or `except Exception:` with no
                                  re-raise or specific assertion on the exception.
                                  (Source: PEP 8 "Programming Recommendations";
                                  xUnit Patterns "Erratic Test" category)
  SMELL-03  test_naming        — test function does not start with `test_`.
                                  pytest requires this prefix to collect the test.
                                  (Source: pytest collection docs — default
                                  python_functions = test_*)
  SMELL-04  magic_number       — numeric literal ≥ 1000 inside an assert
                                  expression not assigned to a named constant.
                                  (Source: Clean Code §17 "Magic Numbers" rule;
                                  threshold 1000 chosen as a conservative lower
                                  bound for numbers unlikely to be incidental
                                  small-integer arithmetic)
  SMELL-05  empty_test         — test function body is only `pass` or only a
                                  docstring (no executable statement at all).
                                  (Source: xUnit Patterns "Empty Test" smell)
  SMELL-06  sleep_in_test      — `time.sleep(` call inside a test function.
                                  Fixed sleeps cause intermittent failures;
                                  use polling helpers or fake timers.
                                  (Source: Google Testing Blog "Avoiding Flakey
                                  Tests" — sleep is the canonical flaky-test
                                  cause)
  SMELL-07  print_in_test      — `print(` call inside a test function (not in a
                                  fixture).  Tests should use captured output
                                  or logging, not print statements.
                                  (Source: pytest capfd/capsys docs — print
                                  is an anti-pattern that pollutes CI output)
  SMELL-08  mock_only_assertions — every assertion in the test is EITHER
                                  (a) a positive DB-SESSION mock-call
                                  verification, or (b) a tautological
                                  assertion (see below) — with at least one
                                  (a). A test meeting this bar proves nothing
                                  about whether the write path under test
                                  actually persisted correct data.

                                  Scope (v2 — narrowed from v1's "any mock"):
                                  a mock-call verification only counts
                                  toward (a) when the mock's ROLE is a DB
                                  session — determined structurally, not by
                                  "is it a Mock": either (i) the asserted
                                  method name is a session verb (`add`,
                                  `add_all`, `commit`, `flush`, `refresh`,
                                  `execute`, `delete`, `merge`, `begin`,
                                  `scalar`, `scalars`), or (ii) the mock's
                                  own variable name matches `db`/`session`/
                                  `sess`/`conn`/`connection` as a whole
                                  token. A mocked HTTP client, logger, event
                                  publisher, or callback prop is a legitimate
                                  observable in its own right and does NOT
                                  count toward (a) — if such a mock-call
                                  verification is present and positive, it
                                  is treated the same as a real assertion
                                  and BLOCKS the smell from firing.

                                  (b) tautological assertion: an `assert`
                                  comparison (`==`/`!=`/`is`/`is not`) where
                                  one side reads an attribute of an object
                                  the test itself constructed inline via a
                                  test-only container (`SimpleNamespace`,
                                  `Mock`, `MagicMock`, `AsyncMock`, a dict
                                  literal, or a locally `@dataclass`-
                                  decorated class) and the other side is a
                                  literal or a variable the test bound
                                  directly to a literal — e.g.
                                  `conversation.capture_notes == "Draft..."`
                                  where `conversation = SimpleNamespace(...)`
                                  was built two lines above. Also covers the
                                  narrower "round-trip identity" case: `assert
                                  result is conversation` where `result` was
                                  assigned from a call that itself received
                                  `conversation` (or an attribute of it) as
                                  an argument — this only proves the test got
                                  back the object it fed in, not that any
                                  field was computed correctly. Tautological
                                  assertions are NON-REDEEMING: they do not
                                  count as "real" and do not block firing.

                                  Does NOT fire when every session-mock
                                  assertion present is negative
                                  (`assert_not_called`/`assert_not_awaited` —
                                  proving "no write occurred" is legitimate),
                                  because that means zero positive (a)
                                  assertions exist at all.

                                  (Source: qa.md "NEVER use Mock when Stub
                                  suffices"; xUnit Patterns "Interaction
                                  Testing" — verifying calls instead of
                                  outcomes)

                                  KNOWN LIMITATIONS (documented, not
                                  fabricated coverage):
                                  - Session-role detection is name/verb
                                    heuristic, not type-aware: a session
                                    mock named unconventionally (no
                                    db/session/conn token) whose asserted
                                    method is also not a listed verb (e.g. a
                                    bare `mock_add_all.assert_called_once()`)
                                    is missed (under-fires).
                                  - The name heuristic only inspects the
                                    ULTIMATE root of a dotted chain (e.g.
                                    `self.db.flush` resolves root to `self`,
                                    not `db`) — verb matching is the primary
                                    signal and covers this in practice, but
                                    a session mock reached through an
                                    unconventionally-named outer object with
                                    a non-verb assertion could be missed.
                                  - Tautology detection (b) does real, sound
                                    AST-local dataflow within a single test
                                    function (container construction ->
                                    attribute read; container -> call-arg ->
                                    result identity) but does NOT do
                                    cross-function or cross-file dataflow,
                                    and does not know whether the production
                                    code in between merely copies the value
                                    (tautological in effect) vs genuinely
                                    computes/validates it (would be a real
                                    assertion). It only fires when the READ
                                    side is a bare attribute access (or bare
                                    identity) on a test-only container —
                                    if productioncode's return value is
                                    reassigned to a new variable before the
                                    attribute read, or wrapped in another
                                    call, tautology detection under-fires
                                    (treated as real, which is the safe
                                    direction).
                                  Under-fires in the above cases; treat
                                  findings as a lower bound, not a complete
                                  list.
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Severity constants — these are structural certainty levels, not risk bands.
# WARN  = the pattern is always undesirable but may have rare valid uses.
# ERROR = the pattern is never acceptable in a test suite.
# (Inspired by ESLint severity model; "error" vs "warn" maps 1:1 to actionability.)
# ---------------------------------------------------------------------------
SEV_ERROR = "ERROR"
SEV_WARN = "WARN"

SMELL_META = {
    "SMELL-01": ("no_assert", SEV_ERROR, "Test has no assertion — can never fail"),
    "SMELL-02": (
        "bare_except",
        SEV_WARN,
        "Bare except/except Exception without re-raise",
    ),
    "SMELL-03": ("test_naming", SEV_ERROR, "Test function does not start with `test_`"),
    "SMELL-04": ("magic_number", SEV_WARN, "Large magic number (>=1000) in assert"),
    "SMELL-05": ("empty_test", SEV_ERROR, "Empty test body (only pass or docstring)"),
    "SMELL-06": ("sleep_in_test", SEV_WARN, "time.sleep() call inside test — flaky"),
    "SMELL-07": (
        "print_in_test",
        SEV_WARN,
        "print() call inside test — pollutes CI output",
    ),
    "SMELL-08": (
        "mock_only_assertions",
        SEV_WARN,
        "All assertions are DB-session mock-call verifications and/or tautological reads — test can pass regardless of real behavior",
    ),
}

# Mock/AsyncMock call-verification methods (unittest.mock).  Named
# `assert_<verb>` (snake_case) — deliberately does not overlap with
# unittest.TestCase's camelCase `assertEqual`/`assertTrue`/etc., which are
# real assertions and must not be classified as mock verifications.
MOCK_ASSERT_METHODS = {
    "assert_called",
    "assert_called_once",
    "assert_called_with",
    "assert_called_once_with",
    "assert_any_call",
    "assert_has_calls",
    "assert_not_called",
    "assert_awaited",
    "assert_awaited_once",
    "assert_awaited_with",
    "assert_awaited_once_with",
    "assert_any_await",
    "assert_has_awaits",
    "assert_not_awaited",
}

# The subset of MOCK_ASSERT_METHODS that assert an interaction did NOT
# happen. Proving "no write occurred" (e.g. on an authorization-deny path)
# has no other observable and is a legitimate test on its own.
NEGATIVE_MOCK_ASSERT_METHODS = {"assert_not_called", "assert_not_awaited"}

# ---------------------------------------------------------------------------
# SMELL-08 v2: DB-session mock scoping (E1) + tautology detection (E2)
# ---------------------------------------------------------------------------
# A mock-call verification only counts as a "DB-session" verification (the
# defect class this rule targets: a write path verified against a mocked DB
# session) when the mock's ROLE is structurally a session, not merely "any
# Mock." Two independent signals, either sufficient:
#   (i)  the asserted METHOD is a session verb (strong signal — works
#        regardless of what the mock variable happens to be named)
#   (ii) the mock's own variable name is/contains db/session/sess/conn/
#        connection as a whole token (covers a bare mock, e.g.
#        `mock_session.assert_called_once()`, where there is no verb)
# A mocked HTTP client (`mock_client.post`), logger (`logger.warning`),
# event publisher (`mock_publish`), or React callback prop (`onClick`) has
# neither signal and is deliberately NOT scoped in — see MUST-NOT-FIRE cases
# in test_pytest_smell.py.
SESSION_VERBS = {
    "add",
    "add_all",
    "commit",
    "flush",
    "refresh",
    "execute",
    "delete",
    "merge",
    "begin",
    "scalar",
    "scalars",
}

_SESSION_NAME_TOKENS = {"db", "session", "sess", "conn", "connection"}

# Test-only container constructors (E2): objects with no independent
# validation — any attribute assigned to one is freely settable and simply
# echoes back whatever was assigned, so reading it back proves nothing about
# whether a real write occurred. Plain dict literals get the same treatment.
TEST_ONLY_CONTAINER_CONSTRUCTORS = {"SimpleNamespace", "Mock", "MagicMock", "AsyncMock"}


def _looks_like_session_name(name: str | None) -> bool:
    """Whole-token match against db/session/sess/conn/connection (case-
    insensitive), split on non-alphanumeric boundaries so `mock_db` and
    `db_session` match but `conversations` (contains "conv", not "conn")
    does not."""
    if not name:
        return False
    tokens = re.findall(r"[A-Za-z0-9]+", name.lower())
    return any(t in _SESSION_NAME_TOKENS for t in tokens)


def _root_name_and_depth(node: ast.AST) -> tuple[str | None, int]:
    """Walk an Attribute chain down to its root Name. Returns (root_id,
    attribute_depth) — depth 0 means `node` IS the root Name itself."""
    depth = 0
    cur = node
    while isinstance(cur, ast.Attribute):
        depth += 1
        cur = cur.value
    if isinstance(cur, ast.Name):
        return cur.id, depth
    return None, depth


def _mock_target_root_and_verb(value_node: ast.AST) -> tuple[str | None, str | None]:
    """Given the receiver expression of a `.assert_*` call (e.g. `db.flush`
    in `db.flush.assert_called_once()`, or bare `mock_x` in
    `mock_x.assert_called_once()`), return (root_variable_name, verb) where
    verb is the last attribute name if the receiver itself is an attribute
    access, else None for a bare mock."""
    root, _depth = _root_name_and_depth(value_node)
    verb = value_node.attr if isinstance(value_node, ast.Attribute) else None
    return root, verb


def _is_session_mock(root: str | None, verb: str | None) -> bool:
    if verb is not None and verb in SESSION_VERBS:
        return True
    return _looks_like_session_name(root)


def _call_func_name(call: ast.Call) -> str | None:
    fn = call.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return None


def _collect_module_dataclass_names(tree: ast.AST) -> set[str]:
    """Names of classes in this file decorated with @dataclass — treated as
    additional test-only containers when constructed inline in a test."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            dec_name = None
            if isinstance(target, ast.Name):
                dec_name = target.id
            elif isinstance(target, ast.Attribute):
                dec_name = target.attr
            if dec_name == "dataclass":
                names.add(node.name)
    return names


def _resolve_simple_bindings(func_node: ast.FunctionDef) -> dict[str, ast.AST]:
    """Map `name -> assigned value expression` for every `name = <expr>`
    assignment anywhere in the function (last write wins on reassignment).
    AST-local, single-function scope only — no cross-function tracing."""
    bindings: dict[str, ast.AST] = {}
    for node in ast.walk(func_node):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            bindings[node.targets[0].id] = node.value
    return bindings


def _is_container_constructor(value_node: ast.AST, dataclass_names: set[str]) -> bool:
    if isinstance(value_node, ast.Dict):
        return True
    if isinstance(value_node, ast.Call):
        name = _call_func_name(value_node)
        return name in TEST_ONLY_CONTAINER_CONSTRUCTORS or name in dataclass_names
    return False


def _collect_container_vars(
    bindings: dict[str, ast.AST], dataclass_names: set[str]
) -> set[str]:
    return {
        name
        for name, value in bindings.items()
        if _is_container_constructor(value, dataclass_names)
    }


def _is_literalish(node: ast.AST, bindings: dict[str, ast.AST], _depth: int = 0) -> bool:
    """True if `node` is a Constant, a collection literal built entirely of
    Constants, or a Name bound (in this function) directly to such a value."""
    if _depth > 6:
        return False
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Dict):
        return all(_is_literalish(v, bindings, _depth + 1) for v in node.values) and all(
            k is None or _is_literalish(k, bindings, _depth + 1) for k in node.keys
        )
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_literalish(e, bindings, _depth + 1) for e in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _is_literalish(node.operand, bindings, _depth + 1)
    if isinstance(node, ast.Name):
        bound = bindings.get(node.id)
        if bound is None:
            return False
        return _is_literalish(bound, bindings, _depth + 1)
    return False


def _references_name(node: ast.AST, target_root: str) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id == target_root:
            return True
    return False


def _collect_derived_map(
    bindings: dict[str, ast.AST], container_vars: set[str]
) -> dict[str, set[str]]:
    """Map `name -> {container roots referenced in the call that produced
    it}` — e.g. `result = await service.update_conversation(db,
    conversation.id, ...)` records `result -> {"conversation"}` (and `db` if
    `db` were itself a container). Used for the round-trip identity
    tautology case: `assert result is conversation`."""
    derived: dict[str, set[str]] = {}
    for name, value in bindings.items():
        if name in container_vars:
            continue
        call_node = value.value if isinstance(value, ast.Await) else value
        if not isinstance(call_node, ast.Call):
            continue
        refs = set()
        for arg in list(call_node.args) + [kw.value for kw in call_node.keywords]:
            for container in container_vars:
                if _references_name(arg, container):
                    refs.add(container)
        if refs:
            derived[name] = refs
    return derived


def _is_tautological_compare(
    test_expr: ast.AST,
    container_vars: set[str],
    bindings: dict[str, ast.AST],
    derived_map: dict[str, set[str]],
) -> bool:
    """
    SMELL-08 (E2): an `assert` comparison is NON-REDEEMING (tautological)
    when either:

    Case A (literal read-back): one side is an attribute-access chain
    rooted at a test-only container var (depth >= 1, e.g.
    `conversation.capture_notes`), and the other side is a literal or a
    variable the test bound directly to a literal (e.g. `"Draft..."`).

    Case B (round-trip identity): one side is a BARE reference to a
    test-only container var (depth 0, e.g. `conversation`), and the other
    side is a Name whose assignment called a function that itself received
    that same container (or an attribute of it) as an argument (e.g.
    `result = await service.update_conversation(db, conversation.id, ...)`)
    — this only proves the object came back unchanged in identity, not that
    any field was computed correctly.

    Only handles a single binary comparison (`==`/`!=`/`is`/`is not`);
    chained comparisons (`a == b == c`) are left classified as real (safe
    direction — never over-fires).
    """
    if not isinstance(test_expr, ast.Compare):
        return False
    if len(test_expr.ops) != 1 or len(test_expr.comparators) != 1:
        return False
    if not isinstance(test_expr.ops[0], (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)):
        return False

    left = test_expr.left
    right = test_expr.comparators[0]
    for a, b in ((left, right), (right, left)):
        root, depth = _root_name_and_depth(a)
        if root is None or root not in container_vars:
            continue
        if depth >= 1 and _is_literalish(b, bindings):
            return True
        if depth == 0 and isinstance(b, ast.Name):
            refs = derived_map.get(b.id)
            if refs and root in refs:
                return True
    return False

# Threshold for SMELL-04: magic number lower bound.
# Chosen as the smallest value that is unlikely to be meaningful arithmetic in
# a test (e.g., HTTP status codes are 3-digit; UUIDs/IDs are typically larger).
# Source: Clean Code §17 — "avoid magic numbers in any context."
MAGIC_NUMBER_THRESHOLD = 1000


# ---------------------------------------------------------------------------
# AST-based smell detectors
# ---------------------------------------------------------------------------


def _has_assertion(func_node: ast.FunctionDef) -> bool:
    """Return True if the function contains any form of assertion."""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assert):
            return True
        # pytest.raises(...) — Call where attr is 'raises' on name 'pytest'
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in (
                "raises",
                "warns",
                "approx",
            ):
                return True
            # assertRaises, assertEqual, etc. — unittest style
            if isinstance(fn, ast.Attribute) and fn.attr.startswith("assert"):
                return True
            # assert_called_*, assert_any_call, assert_called_once, etc.
            if isinstance(fn, ast.Attribute) and "assert" in fn.attr.lower():
                return True
    return False


def _is_empty_body(func_node: ast.FunctionDef) -> bool:
    """Return True if the body is only pass and/or a docstring (no real code)."""
    body = func_node.body
    real_stmts = 0
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            # docstring
            continue
        real_stmts += 1
    return real_stmts == 0


def _has_bare_except(func_node: ast.FunctionDef) -> bool:
    """Return True if the function contains a bare except or except Exception without re-raise."""
    for node in ast.walk(func_node):
        if not isinstance(node, ast.ExceptHandler):
            continue
        # bare except:
        if node.type is None:
            # Check there's no raise inside this handler
            for child in ast.walk(node):
                if isinstance(child, ast.Raise):
                    break
            else:
                return True
        # except Exception:
        if isinstance(node.type, ast.Name) and node.type.id == "Exception":
            for child in ast.walk(node):
                if isinstance(child, ast.Raise):
                    break
            else:
                return True
    return False


def _has_magic_number_in_assert(func_node: ast.FunctionDef) -> bool:
    """Return True if any assert contains a numeric literal >= MAGIC_NUMBER_THRESHOLD."""
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Assert):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(
                child.value, (int, float)
            ):
                if abs(child.value) >= MAGIC_NUMBER_THRESHOLD:
                    return True
    return False


def _has_sleep(func_node: ast.FunctionDef) -> bool:
    """Return True if the function calls time.sleep(...)."""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            fn = node.func
            # time.sleep(...)
            if (
                isinstance(fn, ast.Attribute)
                and fn.attr == "sleep"
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "time"
            ):
                return True
            # from time import sleep; sleep(...)
            if isinstance(fn, ast.Name) and fn.id == "sleep":
                return True
    return False


def _classify_assertions(func_node: ast.FunctionDef, dataclass_names: set[str]) -> dict[str, int]:
    """
    Walk every assertion-like statement in a test function and classify it
    into one of six buckets:

      real            — a genuine, non-tautological assertion. Blocks firing.
      tautological     — E2 non-redeeming assertion (see _is_tautological_
                          compare). Does NOT block firing.
      session_pos      — positive DB-session mock-call verification (E1).
      session_neg      — negative DB-session mock-call verification.
      other_mock_pos   — positive mock-call verification on a NON-session
                          mock (HTTP client, logger, publisher, callback
                          prop, ...). Treated like `real`: blocks firing,
                          since it is a legitimate observable in its own
                          right, not evidence this rule should fire on.
      other_mock_neg   — negative mock-call verification on a non-session
                          mock. Does not block firing (proves nothing
                          happened, which this rule doesn't police).
    """
    bindings = _resolve_simple_bindings(func_node)
    container_vars = _collect_container_vars(bindings, dataclass_names)
    derived_map = _collect_derived_map(bindings, container_vars)

    counts = {
        "real": 0,
        "tautological": 0,
        "session_pos": 0,
        "session_neg": 0,
        "other_mock_pos": 0,
        "other_mock_neg": 0,
    }

    for node in ast.walk(func_node):
        if isinstance(node, ast.Assert):
            if _is_tautological_compare(node.test, container_vars, bindings, derived_map):
                counts["tautological"] += 1
            else:
                counts["real"] += 1
            continue
        if isinstance(node, ast.Call):
            fn = node.func
            if not isinstance(fn, ast.Attribute):
                continue
            attr = fn.attr
            if attr in MOCK_ASSERT_METHODS:
                root, verb = _mock_target_root_and_verb(fn.value)
                negative = attr in NEGATIVE_MOCK_ASSERT_METHODS
                if _is_session_mock(root, verb):
                    counts["session_neg" if negative else "session_pos"] += 1
                else:
                    counts["other_mock_neg" if negative else "other_mock_pos"] += 1
            elif attr in ("raises", "warns"):
                counts["real"] += 1
            elif attr.startswith("assert"):
                # unittest.TestCase-style assertion (assertEqual, assertTrue,
                # assertRaises, ...) or an unrecognized assert_* method.
                # NOTE: tautology detection (E2) only covers plain `assert`
                # comparisons, not unittest-style assertEqual(a, b) calls —
                # documented limitation, classified as real (safe direction).
                counts["real"] += 1
    return counts


def _is_mock_only_assertions(func_node: ast.FunctionDef, dataclass_names: set[str]) -> bool:
    """
    SMELL-08 v2: fires when every assertion in the function is either
    (a) a positive DB-session mock-call verification, or (b) a
    tautological assertion — with at least one (a) present. A positive
    mock-call verification on a non-session mock (HTTP client, logger,
    event publisher, callback prop) blocks firing, same as a real
    assertion — see E1 in the module docstring.
    """
    counts = _classify_assertions(func_node, dataclass_names)
    if counts["real"] > 0:
        return False
    if counts["other_mock_pos"] > 0:
        return False
    return counts["session_pos"] > 0


def _has_print(func_node: ast.FunctionDef) -> bool:
    """Return True if the function calls print(...)."""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == "print":
                return True
    return False


# ---------------------------------------------------------------------------
# Per-file analysis
# ---------------------------------------------------------------------------


def analyze_source(source: str, filename: str = "<input>") -> list[dict]:
    """
    Parse source and return a list of finding dicts.
    Each finding: { smell_id, name, severity, message, file, line, function }
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        # SyntaxError is not a smell — report as an error finding
        return [
            {
                "smell_id": "PARSE-ERROR",
                "name": "parse_error",
                "severity": SEV_ERROR,
                "message": f"SyntaxError: {exc.msg} (line {exc.lineno})",
                "file": filename,
                "line": exc.lineno or 0,
                "function": "<module>",
            }
        ]

    findings = []
    dataclass_names = _collect_module_dataclass_names(tree)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        name = node.name
        line = node.lineno

        # SMELL-03: naming
        if not name.startswith("test_") and not name.startswith("test"):
            # Only flag functions that look like they should be tests
            # (decorated with @pytest.mark.* or inside a Test* class at module level
            # is hard to detect with simple AST; so we only flag functions inside
            # classes named Test* or at module-level with "test" substring in name)
            parent_classes = [
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef)
                and any(
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child is node
                    for child in ast.walk(n)
                )
            ]
            is_in_test_class = any(c.name.startswith("Test") for c in parent_classes)
            # Only flag if it's in a Test* class and doesn't start with test_
            if is_in_test_class and not name.startswith("test"):
                findings.append(
                    _make_finding(
                        "SMELL-03",
                        filename,
                        line,
                        name,
                        f"Function '{name}' in a Test class does not start with 'test_'",
                    )
                )

        # Skip non-test functions for further checks
        if not (name.startswith("test_") or name.startswith("test")):
            continue
        if not (name.lower().startswith("test")):
            continue

        # SMELL-05: empty body (check before no_assert to avoid double-reporting)
        if _is_empty_body(node):
            findings.append(
                _make_finding(
                    "SMELL-05",
                    filename,
                    line,
                    name,
                    f"Test '{name}' has an empty body (only pass or docstring)",
                )
            )
            continue  # empty → no assertion by definition; don't double-report

        # SMELL-01: no assertion
        if not _has_assertion(node):
            findings.append(
                _make_finding(
                    "SMELL-01",
                    filename,
                    line,
                    name,
                    f"Test '{name}' has no assertion — it can never fail",
                )
            )

        # SMELL-02: bare except
        if _has_bare_except(node):
            findings.append(
                _make_finding(
                    "SMELL-02",
                    filename,
                    line,
                    name,
                    f"Test '{name}' uses bare except / except Exception without re-raise",
                )
            )

        # SMELL-04: magic number in assert
        if _has_magic_number_in_assert(node):
            findings.append(
                _make_finding(
                    "SMELL-04",
                    filename,
                    line,
                    name,
                    f"Test '{name}' contains a magic number (>={MAGIC_NUMBER_THRESHOLD}) in an assert",
                )
            )

        # SMELL-06: sleep
        if _has_sleep(node):
            findings.append(
                _make_finding(
                    "SMELL-06",
                    filename,
                    line,
                    name,
                    f"Test '{name}' calls time.sleep() — use polling helpers or fake timers",
                )
            )

        # SMELL-07: print
        if _has_print(node):
            findings.append(
                _make_finding(
                    "SMELL-07",
                    filename,
                    line,
                    name,
                    f"Test '{name}' calls print() — use capfd/capsys or logging instead",
                )
            )

        # SMELL-08: every assertion is a session-mock-call verification
        # and/or tautological
        if _is_mock_only_assertions(node, dataclass_names):
            findings.append(
                _make_finding(
                    "SMELL-08",
                    filename,
                    line,
                    name,
                    f"Test '{name}' only verifies a DB-session mock call and/or "
                    "reads back a value it supplied itself — it can pass "
                    "regardless of whether the write actually persisted",
                )
            )

    return findings


def _make_finding(
    smell_id: str, filename: str, line: int, function: str, message: str
) -> dict:
    meta = SMELL_META.get(smell_id, (smell_id, SEV_WARN, message))
    return {
        "smell_id": smell_id,
        "name": meta[0],
        "severity": meta[1],
        "message": message,
        "file": filename,
        "line": line,
        "function": function,
    }


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


def load_sources(source: str | None) -> list[tuple[str, str]]:
    """
    Returns a list of (filename, source_text) pairs.
    source=None or '-' → read stdin as a single file named '<stdin>'.
    source is a directory → walk test_*.py / *_test.py recursively.
    source is a .py file → read that file.
    """
    if source is None or source == "-":
        return [("<stdin>", sys.stdin.read())]

    path = Path(source)

    if not path.exists():
        raise ValueError(f"Path not found: {source}")

    if path.is_dir():
        pairs = []
        for p in sorted(path.rglob("*.py")):
            if p.name.startswith("test_") or p.name.endswith("_test.py"):
                try:
                    pairs.append((str(p), p.read_text(encoding="utf-8")))
                except OSError as exc:
                    raise ValueError(f"Cannot read '{p}': {exc}") from exc
        return pairs

    if path.suffix != ".py":
        raise ValueError(f"Input file must be a .py file, got: {source}")

    try:
        return [(str(path), path.read_text(encoding="utf-8"))]
    except OSError as exc:
        raise ValueError(f"Cannot read '{source}': {exc}") from exc


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------


def render_markdown(findings: list[dict]) -> str:
    if not findings:
        return "_No test smells detected._\n"

    lines = [
        "| File | Line | Function | Smell | Severity | Message |",
        "|------|------|----------|-------|----------|---------|",
    ]
    for f in findings:
        fname = Path(f["file"]).name
        lines.append(
            f"| {fname} | {f['line']} | `{f['function']}` "
            f"| {f['smell_id']} | {f['severity']} | {f['message']} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(source: str | None) -> int:
    try:
        sources = load_sources(source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    all_findings: list[dict] = []
    for filename, text in sources:
        if not text.strip():
            continue
        all_findings.extend(analyze_source(text, filename))

    # Sort: ERROR first, then by file+line
    all_findings.sort(
        key=lambda f: (0 if f["severity"] == SEV_ERROR else 1, f["file"], f["line"])
    )

    summary = {
        "total": len(all_findings),
        "error": sum(1 for f in all_findings if f["severity"] == SEV_ERROR),
        "warn": sum(1 for f in all_findings if f["severity"] == SEV_WARN),
        "files_analyzed": len(sources),
    }

    output = {"findings": all_findings, "summary": summary}
    print(json.dumps(output, indent=2))
    print()
    print("## pytest Test Smell Report\n")
    print(render_markdown(all_findings))
    print(
        "**Severity:** ERROR = must fix (test is broken/useless) | "
        "WARN = should fix (flaky/noisy)"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Detect test smells in pytest test files. "
            "Reads one .py file, a directory of test files, or stdin."
        ),
        epilog=(
            "Smells detected: no_assert (SMELL-01), bare_except (SMELL-02), "
            "test_naming (SMELL-03), magic_number (SMELL-04), empty_test (SMELL-05), "
            "sleep_in_test (SMELL-06), print_in_test (SMELL-07), "
            "mock_only_assertions (SMELL-08)."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to a .py test file, a directory, or '-' for stdin (default: stdin)",
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
