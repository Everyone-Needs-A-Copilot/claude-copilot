#!/usr/bin/env python3
"""
jest_smell.py — L3 executable for the jest-patterns skill.

Analyzes a JavaScript/TypeScript test file for deterministic test smells
using regex-based pattern matching (stdlib only — no npm, no babel).

Input (file path as first arg, or '-'/no-arg for stdin):
  JS/TS source text of one test file.

Output (stdout):
  1. Ranked JSON object with `findings` list and `summary`.
  2. Human-readable markdown section.

Exit codes:
  0 — success (including zero findings, including empty input)
  1 — invalid input (file not found, not a .js/.ts/.jsx/.tsx file for
      named files, unreadable content)

Smell rules (each cites authoritative source):

  SMELL-01  test_only       — `.only(` left in test file.
                               .only focuses the test runner on one test,
                               causing the entire rest of the suite to be
                               skipped silently in CI.
                               (Source: Jest docs "test.only" — explicitly
                               warns this should not be committed)

  SMELL-02  test_skip       — `.skip(` left in test file.
                               .skip silently disables tests; skipped tests
                               do not appear as failures in CI.
                               (Source: Jest docs "test.skip" — "do not
                               commit skipped tests to source control")

  SMELL-03  no_expect       — describe/it/test block with no `expect(` call.
                               A test without an expect can never fail.
                               (Source: Jest docs "expect" — the only way
                               to make assertions in Jest; xUnit Patterns
                               "Assertion-Free Test" smell)

  SMELL-04  async_no_await  — async arrow/function test body that contains
                               no `await` keyword. An async test that never
                               awaits will complete before promises resolve,
                               silently passing.
                               (Source: Jest docs "async/await" — missing
                               await is the documented cause of false-green
                               async tests)

  SMELL-05  setTimeout_zero — `setTimeout(` with 0 ms delay inside a test.
                               Used to defer assertion past the microtask
                               queue; indicates the test is racing with async
                               code rather than controlling it.
                               (Source: Jest docs "Timer Mocks" — use
                               jest.useFakeTimers() instead of
                               setTimeout(fn, 0) hacks)

  SMELL-06  console_log     — `console.log(` call inside a test block.
                               Log statements pollute CI output and indicate
                               debugging code left in.
                               (Source: Jest config docs "verbose" — use
                               --verbose or jest-circus reporter, not console.log)

  SMELL-07  done_callback   — `done` callback pattern: `(done) =>` in a
                               test body.  The done() pattern is error-prone
                               (an uncaught error swallows the done call);
                               async/await is the modern replacement.
                               (Source: Jest docs migration guide — done
                               callbacks are a "common source of flaky tests")

  SMELL-08  mock_only_assertions — every expect(...) in the test block is
                               EITHER (a) a positive mock-call verification
                               on a mocked ORM/DB CLIENT (`mockPrisma.*`,
                               `prisma.*`, a mocked repository/db module),
                               asserted via `toHaveBeenCalled*` on a write
                               verb (`create`, `update`, `delete`, `upsert`,
                               `createMany`, `updateMany`, `deleteMany`,
                               `transaction`, `save`), OR (b) a tautological
                               assertion (see below) — with at least one
                               (a). Under this bar the test proves nothing
                               about whether the write path actually
                               persisted correct data.

                               Scope (v2 — narrowed from v1's "any mock"):
                               a mock-call verification only counts toward
                               (a) when the asserted RECEIVER looks like an
                               ORM/DB client — root identifier matching
                               `(mock)?(prisma|db|database|repo(sitory)?|
                               orm)...` AND the asserted method a write
                               verb from the list above. A mocked HTTP
                               client, logger, event emitter, or React
                               callback prop (`expect(onClick).
                               toHaveBeenCalledTimes(1)`) has neither signal
                               and does NOT count toward (a) — if positive
                               and present, it blocks firing the same as a
                               real assertion (see MUST-NOT-FIRE cases in
                               test_jest_smell.py).

                               (b) tautological assertion, two narrow forms:
                               (b1) asserting on a field of an object that
                               was passed, by the same test, as the
                               argument to `.mockResolvedValue(...)` on any
                               mock — e.g. `const fake = {...}; x.
                               mockResolvedValue(fake); ...
                               expect(fake.field).toBe('literal')` reads
                               back exactly what the test supplied.
                               (b2) a bare HTTP status-code assertion —
                               `expect(response.status).toBe(200)` or
                               `.statusCode` — with no assertion on the
                               response BODY. Documented as a distinct,
                               narrower heuristic than (b1): NOT dataflow-
                               traced back to a literal the test supplied,
                               justified instead because a 2xx/3xx/4xx/5xx
                               status check alone, when the entire
                               persistence layer is mocked to always
                               succeed, proves the handler didn't throw —
                               nothing about whether it wrote the right
                               data. Tautological assertions are NON-
                               REDEEMING: they do not block firing.

                               Does NOT fire when every ORM-mock assertion
                               present is negative (`.not.toHaveBeenCalled*`
                               — proving "no write occurred" is legitimate),
                               because that means zero positive (a)
                               assertions exist at all.
                               (Source: qa.md "NEVER use Mock when Stub
                               suffices"; xUnit Patterns "Interaction
                               Testing" — verifying calls instead of
                               outcomes)

                               KNOWN LIMITATIONS (documented, not fabricated
                               coverage):
                               - ORM-role detection is name/verb regex, not
                                 type-aware: a DB client mock reached
                                 through an unconventionally-named variable
                                 (no prisma/db/repo token) is missed
                                 (under-fires — safe direction).
                               - Tautology (b1) only recognizes a container
                                 var passed DIRECTLY as the sole argument to
                                 `.mockResolvedValue(...)` within the SAME
                                 block — no cross-block, cross-file, or
                                 multi-hop dataflow tracing (e.g. through an
                                 intermediate variable reassignment).
                               - Tautology (b2) is a blunt regex on the
                                 `expect()` chain text (stdlib-only, no
                                 parser); a status check wrapped in extra
                                 whitespace/parens beyond what the regex
                                 tolerates is treated as real (safe
                                 direction, under-fires).
                               Under-fires in the above cases; treat
                               findings as a lower bound, not a complete
                               list.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Severity constants — ERROR = always broken; WARN = should fix
# ---------------------------------------------------------------------------
SEV_ERROR = "ERROR"
SEV_WARN = "WARN"

SMELL_META = {
    "SMELL-01": (
        "test_only",
        SEV_ERROR,
        ".only() left in — silently skips rest of suite",
    ),
    "SMELL-02": ("test_skip", SEV_WARN, ".skip() left in — tests silently disabled"),
    "SMELL-03": ("no_expect", SEV_ERROR, "Test block has no expect() call"),
    "SMELL-04": (
        "async_no_await",
        SEV_ERROR,
        "async test body has no await — promise not awaited",
    ),
    "SMELL-05": (
        "setTimeout_zero",
        SEV_WARN,
        "setTimeout(fn, 0) in test — use fake timers",
    ),
    "SMELL-06": (
        "console_log",
        SEV_WARN,
        "console.log() left in test — pollutes CI output",
    ),
    "SMELL-07": (
        "done_callback",
        SEV_WARN,
        "done callback pattern — use async/await instead",
    ),
    "SMELL-08": (
        "mock_only_assertions",
        SEV_WARN,
        "All expect() calls are ORM/DB-mock call verifications and/or tautological reads — test can pass regardless of real behavior",
    ),
}

VALID_EXTENSIONS = {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"}

# ---------------------------------------------------------------------------
# Regex patterns (compiled once)
# ---------------------------------------------------------------------------
# Lines that contain .only( — covers it.only, test.only, describe.only, fit, fdescribe
RE_ONLY = re.compile(r"\b(?:it|test|describe|fit|fdescribe)\.only\s*\(")

# Lines that contain .skip(
RE_SKIP = re.compile(r"\b(?:it|test|describe|xit|xdescribe)\.skip\s*\(")

# Line that starts a test block: it(, test(, it.each(, test.each( etc.
RE_TEST_OPEN = re.compile(
    r"^\s*(?:it|test)(?:\.each\([^)]*\))?\s*\(" r'|^\s*(?:it|test)\s*\(\s*[\'"`]',
    re.MULTILINE,
)

# setTimeout with 0
RE_SETTIMEOUT_ZERO = re.compile(r"\bsetTimeout\s*\(\s*\w+\s*,\s*0\s*\)")

# console.log
RE_CONSOLE_LOG = re.compile(r"\bconsole\.log\s*\(")

# done callback: (done) => or function(done)
RE_DONE_CALLBACK = re.compile(r"(?:async\s+)?\([^)]*\bdone\b[^)]*\)\s*(?:=>|{)")

# async test: async () => or async function
RE_ASYNC_TEST = re.compile(r"\basync\s+(?:\([^)]*\)\s*=>|\bfunction\b)")

# await keyword
RE_AWAIT = re.compile(r"\bawait\b")

# expect( call
RE_EXPECT = re.compile(r"\bexpect\s*\(")

# Mock call-verification matchers (jest + jest-extended aliases).
# Group 1 captures an optional immediately-preceding `not.` negation.
RE_MOCK_MATCHER = re.compile(
    r"\.(not\.)?(toHaveBeenCalled\w*|toBeCalled\w*|toHaveBeenNthCalledWith|"
    r"toHaveBeenLastCalledWith)\b"
)

# ---------------------------------------------------------------------------
# SMELL-08 v2: ORM/DB-client mock scoping (E1) + tautology detection (E2)
# ---------------------------------------------------------------------------
# Write verbs that, on an ORM/DB client, represent a persistence mutation.
ORM_WRITE_VERBS = {
    "create",
    "update",
    "delete",
    "upsert",
    "createMany",
    "updateMany",
    "deleteMany",
    "transaction",
    "save",
}

# Root identifier of the asserted receiver must look like an ORM/DB client —
# e.g. mockPrisma, prisma, db, mockDb, database, repo, repository, orm.
# Deliberately does NOT match generic mocks (mockClient, mockFetch,
# mockAxios, mockLogger, mockEmitter, onClick, ...).
RE_ORM_ROOT = re.compile(r"(?i)^(mock)?(prisma|database|db|repository|repo|orm)\w*$")

# Extract the root identifier (first dotted segment) and the verb (last
# dotted segment, stripped of any trailing call parens) of the expression
# passed to expect(...), e.g. "mockPrisma.force.update" -> root="mockPrisma",
# verb="update".
RE_RECEIVER_ROOT = re.compile(r"^\s*([A-Za-z_$][\w$]*)")
RE_RECEIVER_VERB = re.compile(r"([A-Za-z_$][\w$]*)\s*$")

# (b1) tautology: a variable passed as the sole argument to
# `<mock>.mockResolvedValue(<name>)` — that name is a test-only container;
# reading one of its fields back and comparing to a literal is a read-back
# of a value the test itself supplied.
RE_MOCK_RESOLVED_VALUE_VAR = re.compile(
    r"\.mockResolvedValue\s*\(\s*([A-Za-z_$][\w$]*)\s*\)"
)

# (b2) tautology: a bare HTTP status-code assertion with nothing else in the
# chain — expect(<expr>.status).toBe(<3-digit literal>) or `.statusCode`.
# Regex-only (stdlib, no parser); tolerates `.not.` and toEqual/toBe.
RE_STATUS_ONLY_CHAIN = re.compile(
    r"^expect\s*\(\s*[\w.$]+\.(status|statusCode)\s*\)"
    r"\s*\.(not\.)?(toBe|toEqual|toStrictEqual)\s*\(\s*\d{3}\s*\)\s*;?\s*$"
)


# ---------------------------------------------------------------------------
# Per-file analysis
# ---------------------------------------------------------------------------


def extract_test_blocks(source: str) -> list[tuple[int, str]]:
    """
    Return a list of (start_line_number, block_source) for each top-level
    it()/test() invocation.  Line numbers are 1-indexed.

    Strategy: find each line matching RE_TEST_OPEN, then collect lines until
    the brace depth returns to zero (crude but stdlib-only).  This handles
    the common case; deeply nested or template-literal blocks may not parse
    perfectly, but false negatives are acceptable (we only ever false-negative,
    never false-positive on the block extraction).
    """
    lines = source.splitlines()
    blocks = []

    i = 0
    while i < len(lines):
        line = lines[i]
        if RE_TEST_OPEN.match(line):
            start = i
            block_lines = [line]
            depth = line.count("{") - line.count("}")
            j = i + 1
            while j < len(lines) and depth > 0:
                block_lines.append(lines[j])
                depth += lines[j].count("{") - lines[j].count("}")
                j += 1
            blocks.append((start + 1, "\n".join(block_lines)))
            i = j
        else:
            i += 1

    return blocks


def _extract_expect_chains(block: str) -> list[tuple[str, str]]:
    """
    Return (receiver_text, full_chain_text) for each top-level
    `expect(...)` statement in a block. `receiver_text` is the argument
    passed to `expect(...)` (e.g. `mockPrisma.force.update`);
    `full_chain_text` is `expect(x).matcher(...)`, including any
    `.not.`/`.resolves.`/`.rejects.` modifiers, up to (but not including)
    the next `expect(` call.

    Crude but stdlib-only, consistent with extract_test_blocks() above:
    false negatives (missed chains) are acceptable, false positives are not.
    """
    chains = []
    for m in re.finditer(r"\bexpect\s*\(", block):
        open_paren = m.end() - 1
        depth = 0
        j = open_paren
        while j < len(block):
            if block[j] == "(":
                depth += 1
            elif block[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        else:
            # Unbalanced parens (truncated block) — skip this occurrence.
            continue
        receiver = block[open_paren + 1 : j]
        next_expect = block.find("expect(", j)
        boundary = next_expect if next_expect != -1 else len(block)
        full_chain = block[m.start() : j + 1] + block[j + 1 : boundary]
        chains.append((receiver.strip(), full_chain))
    return chains


def _is_orm_write_mock_chain(receiver: str) -> bool:
    """
    SMELL-08 (E1): True if `receiver` (the expression passed to expect())
    looks like an ORM/DB client write call — e.g. `mockPrisma.force.update`,
    `prisma.user.create`, `db.transaction`, `userRepository.save`. Requires
    BOTH the trailing verb to be a write verb (ORM_WRITE_VERBS) AND the
    leading identifier to look like an ORM/DB client (RE_ORM_ROOT) — this
    dual requirement is what keeps a mocked HTTP client, logger, event
    emitter, or React callback prop out of scope.
    """
    root_m = RE_RECEIVER_ROOT.match(receiver)
    verb_m = RE_RECEIVER_VERB.search(receiver)
    root = root_m.group(1) if root_m else None
    verb = verb_m.group(1) if verb_m else None
    if verb not in ORM_WRITE_VERBS:
        return False
    return bool(root and RE_ORM_ROOT.match(root))


# (b1) tautology: expect(<containerVar>.<field...>).matcher(<literal>) where
# <containerVar> was passed as the sole argument to `.mockResolvedValue(...)`
# earlier in the same block.
RE_CONTAINER_FIELD_LITERAL = re.compile(
    r"^expect\s*\(\s*([A-Za-z_$][\w$]*)((?:\.[A-Za-z_$][\w$]*)+)\s*\)"
    r"\s*\.(not\.)?(toBe|toEqual|toStrictEqual)\s*\("
    r"\s*(['\"].*?['\"]|-?\d+(?:\.\d+)?|true|false|null|undefined)\s*\)\s*;?\s*$",
    re.DOTALL,
)


def _is_tautological_chain(chain: str, container_vars: set[str]) -> bool:
    """
    SMELL-08 (E2): a NON-REDEEMING (tautological) expect() chain, two
    narrow forms — see module docstring for the full justification and
    documented limitations of each:

    (b1) reads a field off a variable the same test passed directly to
    `.mockResolvedValue(...)`, compared to a literal.

    (b2) a bare HTTP status-code assertion (`.status`/`.statusCode`
    compared to a 3-digit literal) with nothing else checked in the chain.
    """
    stripped = chain.strip()
    if RE_STATUS_ONLY_CHAIN.match(stripped):
        return True
    m = RE_CONTAINER_FIELD_LITERAL.match(stripped)
    if m and m.group(1) in container_vars:
        return True
    return False


def _classify_expect_chains(block: str) -> dict[str, int]:
    """
    Classify every expect(...) assertion chain in a test block into six
    buckets — see _classify_assertions() in pytest_smell.py for the
    parallel Python design; buckets have identical semantics here:
      real, tautological, orm_pos, orm_neg, other_mock_pos, other_mock_neg
    """
    counts = {
        "real": 0,
        "tautological": 0,
        "orm_pos": 0,
        "orm_neg": 0,
        "other_mock_pos": 0,
        "other_mock_neg": 0,
    }
    container_vars = set(RE_MOCK_RESOLVED_VALUE_VAR.findall(block))

    for receiver, chain in _extract_expect_chains(block):
        matches = list(RE_MOCK_MATCHER.finditer(chain))
        if matches:
            # Positive if any matcher occurrence in the chain lacks `.not.`.
            is_positive = any(m.group(1) is None for m in matches)
            if _is_orm_write_mock_chain(receiver):
                counts["orm_pos" if is_positive else "orm_neg"] += 1
            else:
                counts["other_mock_pos" if is_positive else "other_mock_neg"] += 1
            continue
        if _is_tautological_chain(chain, container_vars):
            counts["tautological"] += 1
        else:
            counts["real"] += 1
    return counts


def analyze_source(source: str, filename: str = "<input>") -> list[dict]:
    """Parse source and return list of smell finding dicts."""
    findings = []

    if not source.strip():
        return findings

    lines = source.splitlines()

    # SMELL-01: .only() — line-level scan
    for lineno, line in enumerate(lines, 1):
        if RE_ONLY.search(line):
            findings.append(
                _make_finding(
                    "SMELL-01",
                    filename,
                    lineno,
                    "<suite>",
                    f".only() found at line {lineno} — silently skips all other tests",
                )
            )

    # SMELL-02: .skip() — line-level scan
    for lineno, line in enumerate(lines, 1):
        if RE_SKIP.search(line):
            findings.append(
                _make_finding(
                    "SMELL-02",
                    filename,
                    lineno,
                    "<suite>",
                    f".skip() found at line {lineno} — test silently disabled",
                )
            )

    # Block-level smells
    blocks = extract_test_blocks(source)
    for start_line, block in blocks:
        func_name = _extract_test_name(block)

        # SMELL-03: no expect
        if not RE_EXPECT.search(block):
            findings.append(
                _make_finding(
                    "SMELL-03",
                    filename,
                    start_line,
                    func_name,
                    f"Test '{func_name}' has no expect() call — can never fail",
                )
            )

        # SMELL-04: async with no await
        if RE_ASYNC_TEST.search(block) and not RE_AWAIT.search(block):
            findings.append(
                _make_finding(
                    "SMELL-04",
                    filename,
                    start_line,
                    func_name,
                    f"Test '{func_name}' is async but has no await — promise not awaited",
                )
            )

        # SMELL-05: setTimeout(fn, 0)
        if RE_SETTIMEOUT_ZERO.search(block):
            findings.append(
                _make_finding(
                    "SMELL-05",
                    filename,
                    start_line,
                    func_name,
                    f"Test '{func_name}' uses setTimeout(fn, 0) — use jest.useFakeTimers()",
                )
            )

        # SMELL-06: console.log
        if RE_CONSOLE_LOG.search(block):
            findings.append(
                _make_finding(
                    "SMELL-06",
                    filename,
                    start_line,
                    func_name,
                    f"Test '{func_name}' contains console.log() — remove before committing",
                )
            )

        # SMELL-07: done callback
        if RE_DONE_CALLBACK.search(block):
            findings.append(
                _make_finding(
                    "SMELL-07",
                    filename,
                    start_line,
                    func_name,
                    f"Test '{func_name}' uses done callback — rewrite with async/await",
                )
            )

        # SMELL-08: every expect() is a positive ORM/DB-write mock-call
        # verification and/or tautological (E1 + E2 — see module docstring)
        counts = _classify_expect_chains(block)
        if counts["real"] == 0 and counts["other_mock_pos"] == 0 and counts["orm_pos"] > 0:
            findings.append(
                _make_finding(
                    "SMELL-08",
                    filename,
                    start_line,
                    func_name,
                    f"Test '{func_name}' only verifies an ORM/DB-write mock call "
                    "and/or a tautological read-back — it can pass regardless of "
                    "whether the write actually persisted",
                )
            )

    return findings


def _extract_test_name(block: str) -> str:
    """Extract the test description string from the opening line of a block."""
    m = re.search(r'(?:it|test)\s*\(\s*([\'"`])(.*?)\1', block[:300])
    if m:
        return m.group(2)[:60]
    return "<unnamed>"


def _make_finding(
    smell_id: str, filename: str, line: int, function: str, message: str
) -> dict:
    meta = SMELL_META[smell_id]
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
    Returns list of (filename, source_text) pairs.
    source=None or '-' → stdin.
    source is a directory → walk *.test.* / *.spec.* files.
    source is a file → read that file.
    """
    if source is None or source == "-":
        return [("<stdin>", sys.stdin.read())]

    path = Path(source)

    if not path.exists():
        raise ValueError(f"Path not found: {source}")

    if path.is_dir():
        pairs = []
        for p in sorted(path.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix not in VALID_EXTENSIONS:
                continue
            stem = p.stem
            if (
                ".test" in stem
                or ".spec" in stem
                or stem.endswith("test")
                or stem.endswith("spec")
            ):
                try:
                    pairs.append((str(p), p.read_text(encoding="utf-8")))
                except OSError as exc:
                    raise ValueError(f"Cannot read '{p}': {exc}") from exc
        return pairs

    if path.suffix not in VALID_EXTENSIONS:
        raise ValueError(
            f"Input file must be a JS/TS file "
            f"({', '.join(sorted(VALID_EXTENSIONS))}), got: {source}"
        )

    try:
        return [(str(path), path.read_text(encoding="utf-8"))]
    except OSError as exc:
        raise ValueError(f"Cannot read '{source}': {exc}") from exc


# ---------------------------------------------------------------------------
# Output
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

    # Sort: ERROR first, then file + line
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
    print("## Jest Test Smell Report\n")
    print(render_markdown(all_findings))
    print(
        "**Severity:** ERROR = must fix (test is broken/useless) | "
        "WARN = should fix (flaky/noisy)"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Detect test smells in Jest JS/TS test files. "
            "Reads one test file, a directory of test files, or stdin."
        ),
        epilog=(
            "Smells detected: test_only (SMELL-01), test_skip (SMELL-02), "
            "no_expect (SMELL-03), async_no_await (SMELL-04), "
            "setTimeout_zero (SMELL-05), console_log (SMELL-06), "
            "done_callback (SMELL-07), mock_only_assertions (SMELL-08)."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help=(
            "Path to a JS/TS test file, a directory, or '-' for stdin "
            "(default: stdin)"
        ),
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
