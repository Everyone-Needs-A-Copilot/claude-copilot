"""Unit tests for the pure `tc.evidence` package -- no database.

New file (task 27/B5 territory would author the full regression suite; this
file covers only the code introduced by this task, per the "add tests only
for what would otherwise be untested" scope for the implementing agent).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tc.evidence import EVIDENCE_SCHEMA_VERSION, is_valid_artifact_type, parse_packet, validate_packet
from tc.evidence.parse import is_legacy_shaped
from tc.evidence.schema import render_packet


PASS_V1 = """\
CRITERION: task completes only with valid evidence
EXPECTED: completion is blocked without a passing packet
OBSERVED: completion was blocked as expected
IDENTITY: checkout deadbee, clean
BASELINE: unavailable, fresh fixture
ARTIFACT: test-run|pytest tests/test_x.py exit=0 "3 passed"
UNTESTED: none
VERDICT: APPROVED
"""


# ---------------------------------------------------------------------------
# Fitness function: tc.evidence.validate must stay pure (wp-a-evidence.md
# section 5.4, item 3). Uses AST inspection of actual import statements,
# not a substring scan, so this module's own docstring (which names every
# forbidden module) cannot produce a false positive.
# ---------------------------------------------------------------------------


def test_validate_module_imports_nothing_forbidden():
    import tc.evidence.validate as validate_module

    forbidden = ("tc.db", "tc.services", "subprocess", "os")
    source = Path(validate_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    for name in imported:
        for bad in forbidden:
            assert name != bad and not name.startswith(bad + "."), (
                f"tc.evidence.validate imports forbidden module {name!r} "
                f"(matches {bad!r}); this module must stay pure"
            )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_packet_extracts_all_fields():
    packet = parse_packet(PASS_V1)
    assert packet["records"] == [
        {
            "criterion": "task completes only with valid evidence",
            "expected": "completion is blocked without a passing packet",
            "observed": "completion was blocked as expected",
        }
    ]
    assert packet["identity"] == "checkout deadbee, clean"
    assert packet["baseline"] == "unavailable, fresh fixture"
    assert packet["artifacts"] == ['test-run|pytest tests/test_x.py exit=0 "3 passed"']
    assert packet["untested"] == "none"
    assert packet["verdicts"] == ["APPROVED"]


def test_parse_packet_pairs_multiple_criteria_positionally():
    text = (
        "CRITERION: one\nEXPECTED: e1\nOBSERVED: o1\n"
        "CRITERION: two\nEXPECTED: e2\nOBSERVED: o2\n"
        "IDENTITY: rev1\nBASELINE: unavailable\n"
        "ARTIFACT: test-run|cmd exit=0\nVERDICT: APPROVED\n"
    )
    packet = parse_packet(text)
    assert len(packet["records"]) == 2
    assert packet["records"][0] == {"criterion": "one", "expected": "e1", "observed": "o1"}
    assert packet["records"][1] == {"criterion": "two", "expected": "e2", "observed": "o2"}


def test_field_matching_is_case_insensitive():
    """Defect 8: tc was case-sensitive while the Claude hook was not."""
    text = PASS_V1.replace("VERDICT:", "verdict:").replace("ARTIFACT:", "Artifact:")
    packet = parse_packet(text)
    assert packet["verdicts"] == ["APPROVED"]
    assert packet["artifacts"]


def test_quoted_verdict_inside_fence_is_not_authoritative():
    """Defect 6: a quoted VERDICT example inside a fenced block must never
    be counted as (or conflict with) the packet's real verdict."""
    text = PASS_V1 + (
        "\nExample format:\n```\nVERDICT: REJECTED\n```\n"
    )
    packet = parse_packet(text)
    assert packet["verdicts"] == ["APPROVED"]

    result = validate_packet(packet)
    assert result["valid"] is True, result["errors"]


def test_quoted_verdict_inside_indented_block_is_not_authoritative():
    text = PASS_V1 + "\n    VERDICT: REJECTED (quoted example, indented)\n"
    packet = parse_packet(text)
    assert packet["verdicts"] == ["APPROVED"]


def test_genuine_duplicate_conflicting_verdicts_still_fail():
    """A second, non-quoted VERDICT with a DIFFERENT value is a real
    conflict, distinct from the quoted-example case above."""
    text = PASS_V1 + "\nVERDICT: REJECTED\n"
    packet = parse_packet(text)
    assert set(packet["verdicts"]) == {"APPROVED", "REJECTED"}
    result = validate_packet(packet)
    assert result["valid"] is False
    assert "conflicting" in result["reason"].lower()


def test_is_legacy_shaped_true_without_identity():
    legacy = "ARTIFACT: test-run|pytest exit=0\nVERDICT: APPROVED\n"
    assert is_legacy_shaped(legacy) is True


def test_is_legacy_shaped_false_with_identity():
    assert is_legacy_shaped(PASS_V1) is False


def test_is_legacy_shaped_false_for_non_evidence_text():
    assert is_legacy_shaped("just some unrelated work product content") is False


def test_render_packet_round_trips_readable_form():
    packet = parse_packet(PASS_V1)
    rendered = render_packet(packet)
    reparsed = parse_packet(rendered)
    assert reparsed["verdicts"] == packet["verdicts"]
    assert reparsed["artifacts"] == packet["artifacts"]
    assert reparsed["identity"] == packet["identity"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_valid_packet_passes():
    result = validate_packet(parse_packet(PASS_V1))
    assert result["valid"] is True, result["errors"]
    assert result["verdict"] == "APPROVED"


@pytest.mark.parametrize(
    "mutate,expected_fragment",
    [
        (lambda t: t.replace("CRITERION: task completes only with valid evidence\n", ""), "CRITERION"),
        (lambda t: t.replace("IDENTITY: checkout deadbee, clean\n", ""), "IDENTITY"),
        (lambda t: t.replace("BASELINE: unavailable, fresh fixture\n", ""), "BASELINE"),
        (lambda t: t.replace('ARTIFACT: test-run|pytest tests/test_x.py exit=0 "3 passed"\n', ""), "ARTIFACT"),
        (lambda t: t.replace("VERDICT: APPROVED\n", ""), "VERDICT"),
    ],
)
def test_missing_required_field_fails(mutate, expected_fragment):
    """Defect 2: previously only ARTIFACT and VERDICT were checked at all."""
    text = mutate(PASS_V1)
    result = validate_packet(parse_packet(text))
    assert result["valid"] is False
    assert any(expected_fragment in e for e in result["errors"]), result["errors"]


def test_untested_required_case_fails():
    text = PASS_V1.replace("UNTESTED: none", "UNTESTED: dark-mode toggle not exercised")
    result = validate_packet(parse_packet(text))
    assert result["valid"] is False
    assert "untested" in result["reason"].lower()


def test_rejected_verdict_never_valid():
    text = PASS_V1.replace("VERDICT: APPROVED", "VERDICT: REJECTED")
    result = validate_packet(parse_packet(text))
    assert result["valid"] is False


def test_approved_with_minor_fixes_passes_when_all_criteria_met():
    text = PASS_V1.replace("VERDICT: APPROVED", "VERDICT: APPROVED-WITH-MINOR-FIXES")
    result = validate_packet(parse_packet(text))
    assert result["valid"] is True, result["errors"]


def test_unrecognized_artifact_type_fails():
    """Defect 1: artifact types must come from the shared registry."""
    text = PASS_V1.replace("test-run|", "totally-made-up-type|")
    result = validate_packet(parse_packet(text))
    assert result["valid"] is False
    assert any("unrecognized" in e.lower() for e in result["errors"])


@pytest.mark.parametrize("artifact_type", ["adversarial-run", "screenshot-check", "a11y-check", "design-fidelity-check"])
def test_registry_accepts_every_documented_type(artifact_type):
    """Defect 1: the registry must accept the full union documented across
    tc, the Claude hook and qa.md -- not tc's old subset."""
    assert is_valid_artifact_type(artifact_type)


def test_stale_identity_by_revision_fails():
    """Defect 4: staleness is bound to a live revision comparison, not just
    work-product ordering."""
    current_identity = {"revision": "abc1234", "dirty": False, "dirty_fingerprint": None}
    result = validate_packet(parse_packet(PASS_V1), current_identity=current_identity)
    assert result["valid"] is False
    assert "stale" in result["reason"].lower()


def test_matching_revision_in_identity_passes():
    text = PASS_V1.replace("IDENTITY: checkout deadbee, clean", "IDENTITY: checkout abc1234, clean")
    current_identity = {"revision": "abc1234", "dirty": False, "dirty_fingerprint": None}
    result = validate_packet(parse_packet(text), current_identity=current_identity)
    assert result["valid"] is True, result["errors"]


def test_dirty_tree_contradicts_claimed_clean_identity():
    current_identity = {"revision": None, "dirty": True, "dirty_fingerprint": "deadbeefcafe"}
    result = validate_packet(parse_packet(PASS_V1), current_identity=current_identity)
    assert result["valid"] is False
    assert "clean" in result["reason"].lower() or "stale" in result["reason"].lower()


def test_missing_current_identity_skips_staleness_check():
    """When the caller cannot determine current identity, structural
    validity alone governs -- staleness comparison is skipped, not failed
    closed on an environment that cannot supply the signal."""
    result = validate_packet(parse_packet(PASS_V1), current_identity=None)
    assert result["valid"] is True, result["errors"]


def test_evidence_schema_version_is_stable_int():
    assert isinstance(EVIDENCE_SCHEMA_VERSION, int)
    assert EVIDENCE_SCHEMA_VERSION >= 1


# ---------------------------------------------------------------------------
# QA-authored additions (task 27/B5): independent adversarial cases beyond
# the implementing agent's own scoped coverage above. These specifically
# target the handoff's acceptance list ("bare markers fail", quoted
# approval, missing criteria) at the boundaries the parametrized cases above
# do not reach: a packet that is bare from the start (not PASS_V1 minus one
# field), whitespace-as-absence, and multi-artifact partial failure.
# ---------------------------------------------------------------------------


def test_bare_verdict_marker_alone_fails():
    """The exact shape the OLD predicate accepted: nothing but a VERDICT
    line. This is the literal 'bare marker' the handoff names -- it must
    fail on every required field, not merely on the ones the parametrized
    single-field-removal cases above happen to exercise."""
    result = validate_packet(parse_packet("VERDICT: APPROVED\n"))
    assert result["valid"] is False
    for field in ("CRITERION", "IDENTITY", "BASELINE", "ARTIFACT"):
        assert any(field in e for e in result["errors"]), (field, result["errors"])


def test_bare_artifact_and_verdict_old_contract_shape_fails_structurally():
    """The exact free-text shape the pre-B3 `tc` predicate accepted in
    full (ARTIFACT + VERDICT, nothing else). `validate_packet` itself
    (independent of `tc.services.qa`'s legacy carve-out for
    already-completed tasks) must reject it on structural grounds -- this
    is what makes the legacy carve-out an explicit, narrow policy decision
    rather than the validator silently continuing to accept the old shape."""
    text = "ARTIFACT: test-run|pytest exit=0\nVERDICT: APPROVED\n"
    result = validate_packet(parse_packet(text))
    assert result["valid"] is False
    assert any("CRITERION" in e for e in result["errors"])
    assert any("IDENTITY" in e for e in result["errors"])
    assert any("BASELINE" in e for e in result["errors"])


def test_whitespace_only_criterion_counts_as_missing():
    """A field line present but empty/whitespace must not count as
    'supplied' -- otherwise `CRITERION: \\n` would silently satisfy the
    presence check."""
    text = PASS_V1.replace(
        "CRITERION: task completes only with valid evidence", "CRITERION:    "
    )
    result = validate_packet(parse_packet(text))
    assert result["valid"] is False
    assert any("CRITERION" in e for e in result["errors"])


def test_whitespace_only_identity_counts_as_missing():
    text = PASS_V1.replace("IDENTITY: checkout deadbee, clean", "IDENTITY:   ")
    result = validate_packet(parse_packet(text))
    assert result["valid"] is False
    assert any("IDENTITY" in e for e in result["errors"])


def test_one_invalid_artifact_among_several_still_fails():
    """Multiple ARTIFACT lines: even one recognized type does not rescue a
    packet that also carries an unrecognized one -- every recorded
    artifact is checked, not just the first."""
    text = PASS_V1.replace(
        'ARTIFACT: test-run|pytest tests/test_x.py exit=0 "3 passed"\n',
        'ARTIFACT: test-run|pytest tests/test_x.py exit=0 "3 passed"\n'
        "ARTIFACT: made-up-type|nonsense\n",
    )
    result = validate_packet(parse_packet(text))
    assert result["valid"] is False
    assert any("unrecognized" in e.lower() for e in result["errors"])


def test_untested_none_variants_all_pass_the_untested_gate():
    """`UNTESTED: none/n/a/na/<empty>` are all "no gap" -- not just the
    literal string 'none' the other tests happen to use."""
    for value in ("none", "n/a", "na", "None", "N/A"):
        text = PASS_V1.replace("UNTESTED: none", f"UNTESTED: {value}")
        result = validate_packet(parse_packet(text))
        assert result["valid"] is True, (value, result["errors"])


def test_missing_untested_field_entirely_does_not_fail_gate():
    """UNTESTED is not in REQUIRED_FIELDS (a packet can omit it entirely,
    as distinct from stating it explicitly as 'none') -- only a NAMED gap
    fails the gate."""
    text = PASS_V1.replace("UNTESTED: none\n", "")
    result = validate_packet(parse_packet(text))
    assert result["valid"] is True, result["errors"]


def test_unsupported_verdict_value_fails():
    """A verdict token outside {APPROVED, APPROVED-WITH-MINOR-FIXES,
    REJECTED} (e.g. a typo or an ad hoc value) must fail closed, not be
    silently treated as a pass."""
    text = PASS_V1.replace("VERDICT: APPROVED", "VERDICT: LOOKS-GOOD-TO-ME")
    result = validate_packet(parse_packet(text))
    assert result["valid"] is False


def test_dirty_fingerprint_mismatch_with_explicit_token_fails():
    """Defect 4's narrow fingerprint check: when IDENTITY embeds a
    `dirty:<hex>` token that does not match the current dirty fingerprint,
    that is a real, checkable contradiction distinct from the generic
    'claims clean but tree is dirty' case."""
    text = PASS_V1.replace(
        "IDENTITY: checkout deadbee, clean", "IDENTITY: checkout deadbee, dirty:aaaaaaaaaaaa"
    )
    current_identity = {"revision": "deadbee", "dirty": True, "dirty_fingerprint": "bbbbbbbbbbbb"}
    result = validate_packet(parse_packet(text), current_identity=current_identity)
    assert result["valid"] is False
    assert "stale" in result["reason"].lower()


def test_dirty_fingerprint_match_with_explicit_token_passes():
    text = PASS_V1.replace(
        "IDENTITY: checkout deadbee, clean", "IDENTITY: checkout deadbee, dirty:aaaaaaaaaaaa"
    )
    current_identity = {"revision": "deadbee", "dirty": True, "dirty_fingerprint": "aaaaaaaaaaaa"}
    result = validate_packet(parse_packet(text), current_identity=current_identity)
    assert result["valid"] is True, result["errors"]


@pytest.mark.parametrize("noise", ["", "   ", "\n\n\n", "no evidence fields at all, just prose"])
def test_empty_or_non_evidence_text_fails_every_required_field(noise):
    """Property: for ANY text that carries none of the required fields, the
    validator must fail -- never pass by accident on absence."""
    result = validate_packet(parse_packet(noise))
    assert result["valid"] is False


def test_render_parse_round_trip_is_idempotent_for_any_valid_packet():
    """Property (QuickCheck-style): re-rendering and re-parsing an already
    valid packet must not change its validity -- render/parse is a fixed
    point once a packet is well-formed, for the whole documented verdict
    space, not just APPROVED."""
    for verdict in ("APPROVED", "APPROVED-WITH-MINOR-FIXES"):
        text = PASS_V1.replace("VERDICT: APPROVED", f"VERDICT: {verdict}")
        packet = parse_packet(text)
        rendered = render_packet(packet)
        twice = validate_packet(parse_packet(rendered))
        once = validate_packet(packet)
        assert twice["valid"] == once["valid"] is True, (verdict, twice["errors"])
