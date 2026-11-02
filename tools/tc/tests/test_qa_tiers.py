"""Verification tiers: recorded tier, diff classifier, attestation, check-qa branch.

Real SQLite and a real git repository per test. Negative controls: a diff that
needs a higher tier is refused, a lowered tier needs stored authority, a
hand-typed receipt never approves, and a stale attestation stops approving.
"""
from __future__ import annotations

import json
import subprocess
import time

import pytest

from tc import api
from tc.db.exceptions import ValidationError
from tc.services import tiers
from tc.services.qa import check_task_qa
from .qa_fixtures import bind_packet

DOC = "# Plan\n\nWe offer the OLD title today.\n"
PAGE = '<html><body><h1 class="a">Old heading</h1><p>Body</p></body></html>\n'


def git(root, *args):
    return subprocess.check_output(["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", *args], cwd=root, stderr=subprocess.DEVNULL, text=True)


@pytest.fixture
def repo(db_path):
    root = db_path.parent.parent
    git(root, "init", "-q")
    (root / "doc.md").write_text(DOC)
    (root / "page.html").write_text(PAGE)
    (root / "logic.py").write_text("def f():\n    return 1\n")
    (root / "package.json").write_text('{"name": "x"}\n')
    git(root, "add", "-A")
    git(root, "commit", "-qm", "baseline")
    return root


def shot(root, name="load.png"):
    time.sleep(0.02)
    path = root / ".copilot" / "evidence" / name  # evidence lives under .copilot/, outside the diff
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"png")
    return ".copilot/evidence/" + name


def verify_run(root, run="run1", status="passed"):
    d = root / ".copilot" / "verification" / run
    d.mkdir(parents=True)
    (d / "status.json").write_text(json.dumps({"status": status}))
    return run


def make_task(db_path, tier="T1"):
    task = api.create_task(title="Edit", db_path=db_path)
    api.set_tier(task_id=task["id"], tier=tier, reason="copy edit", db_path=db_path)
    return task["id"]


def t1(db_path, tid, **over):
    inputs = {"in": "doc.md", "present": ["NEW title"], "absent": ["OLD title"], "load": ".copilot/evidence/load.png"}
    inputs.update(over)
    return api.attest(task_id=tid, tier="T1", inputs=inputs, db_path=db_path)


def approved(db_path, tid):
    return check_task_qa(task_id=tid, db_path=db_path)


def test_t1_copy_edit_is_approved_by_attestation(db_path, repo):
    tid = make_task(db_path)
    assert not approved(db_path, tid)["approved"]
    (repo / "doc.md").write_text(DOC.replace("OLD", "NEW"))
    shot(repo)
    result = t1(db_path, tid)
    assert result["minimum"] == "T1"
    qa = approved(db_path, tid)
    assert qa["approved"] and qa["work_product_id"] == result["work_product_id"]
    assert "ATTEST-RECEIPT: " + result["receipt"] in api.get_wp(wp_id=result["work_product_id"], db_path=db_path)["content"]
    assert api.update_task(task_id=tid, status="completed", db_path=db_path)["status"] == "completed"


def test_t1_refused_while_old_text_remains_or_new_text_missing(db_path, repo):
    tid = make_task(db_path)
    (repo / "doc.md").write_text(DOC.replace("OLD title", "NEW title and the OLD title"))
    shot(repo)
    with pytest.raises(ValidationError, match="Old text still present"):
        t1(db_path, tid)
    with pytest.raises(ValidationError, match="New text missing"):
        t1(db_path, tid, present=["absent words"], absent=["zzz"])
    assert not approved(db_path, tid)["approved"]


def test_t1_needs_a_load_artifact_newer_than_the_edit(db_path, repo):
    tid = make_task(db_path)
    shot(repo)
    time.sleep(0.05)
    (repo / "doc.md").write_text(DOC.replace("OLD", "NEW"))
    with pytest.raises(ValidationError, match="predates"):
        t1(db_path, tid)
    with pytest.raises(ValidationError, match="not found"):
        t1(db_path, tid, load=".copilot/evidence/missing.png")


@pytest.mark.parametrize("path,content,trigger", [
    ("logic.py", "def f():\n    return 2\n", "code logic"),
    ("package.json", '{"name": "x", "dependencies": {"y": "1"}}\n', "dependency"),
    ("auth/login.md", "# Login\n", "security"),
    (".claude/hooks/gate.sh", "echo hi\n", "framework"),
    ("data.csv", "a,b\n1,2\n", "new file"),
])
def test_t1_refused_when_diff_needs_t3(db_path, repo, path, content, trigger):
    tid = make_task(db_path)
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    shot(repo)
    assert api.check_tier(task_id=tid, db_path=db_path)["minimum"] == "T3"
    with pytest.raises(ValidationError, match="T3") as err:
        t1(db_path, tid, **{"in": path if path.endswith(".md") else "doc.md"})
    assert not approved(db_path, tid)["approved"]
    assert trigger in " ".join(api.check_tier(task_id=tid, db_path=db_path)["triggers"])


def test_string_literal_only_code_edit_is_t2_not_t1(db_path, repo):
    (repo / "logic.py").write_text("def f():\n    return 1\nLABEL = 'old'\n")
    git(repo, "add", "logic.py"); git(repo, "commit", "-qm", "label")
    (repo / "logic.py").write_text("def f():\n    return 1\nLABEL = 'new'\n")
    tid = make_task(db_path, "T2")
    assert api.check_tier(task_id=tid, base="HEAD", db_path=db_path)["minimum"] == "T2"
    (repo / "logic.py").write_text("def f():\n    return 1\nLABEL = 'new'\nX = 5\n")
    assert api.check_tier(task_id=tid, base="HEAD", db_path=db_path)["minimum"] == "T3"


def test_markup_change_is_t2_and_t2_attestation_approves(db_path, repo):
    tid = make_task(db_path, "T1")
    (repo / "page.html").write_text(PAGE.replace('class="a"', 'class="b"'))
    assert api.check_tier(task_id=tid, db_path=db_path)["minimum"] == "T2"
    shot(repo, "r1.png"); shot(repo, "r2.png")
    run = verify_run(repo)
    with pytest.raises(ValidationError, match="needs at least T2"):
        t1(db_path, tid, **{"in": "page.html", "present": ["Old heading"], "absent": ["zzz"]})
    with pytest.raises(ValidationError, match="did not pass"):
        api.attest(task_id=tid, tier="T2", inputs={"render": [".copilot/evidence/r1.png"], "checks": verify_run(repo, "bad", "failed")}, db_path=db_path)
    with pytest.raises(ValidationError, match="one or two"):
        api.attest(task_id=tid, tier="T2", inputs={"render": [], "checks": run}, db_path=db_path)
    api.attest(task_id=tid, tier="T2", inputs={"render": [".copilot/evidence/r1.png", ".copilot/evidence/r2.png"], "checks": run}, db_path=db_path)
    assert approved(db_path, tid)["approved"]
    assert tiers.effective_tier(json.loads(api.get_task(task_id=tid, db_path=db_path)["metadata"])) == "T2"


def test_html_text_only_is_t1_and_script_change_is_t3(db_path, repo):
    tid = make_task(db_path)
    (repo / "page.html").write_text(PAGE.replace("Old heading", "Fresh heading"))
    assert api.check_tier(task_id=tid, db_path=db_path)["minimum"] == "T1"
    (repo / "page.html").write_text(PAGE.replace("</body>", "<script>run()</script></body>"))
    assert api.check_tier(task_id=tid, db_path=db_path)["minimum"] == "T3"


def test_changed_number_needs_a_checked_source_not_t3(db_path, repo):
    tid = make_task(db_path)
    (repo / "doc.md").write_text(DOC.replace("OLD title", "NEW title for 42% of buyers"))
    (repo / "research.md").write_text("line one\nSurvey: 42% of buyers agreed\n")
    shot(repo)
    check = api.check_tier(task_id=tid, db_path=db_path)
    assert check["minimum"] == "T1" and "42%" in check["numbers"]
    base = {"present": ["NEW title"], "absent": ["OLD title"]}
    with pytest.raises(ValidationError, match="need a source"):
        t1(db_path, tid, **base)
    with pytest.raises(ValidationError, match="does not appear"):
        t1(db_path, tid, source=["42%=research.md:1"], **base)
    with pytest.raises(ValidationError, match="not found"):
        t1(db_path, tid, source=["42%=nope.md:1"], **base)
    t1(db_path, tid, source=["42%=research.md:2"], **base)
    assert approved(db_path, tid)["approved"]


def test_frontmatter_date_and_list_markers_are_not_claims(db_path, repo):
    tid = make_task(db_path)
    (repo / "doc.md").write_text("---\nupdated: 2026-11-02\n---\n" + DOC.replace("OLD", "NEW") + "\n1. step\n")
    check = api.check_tier(task_id=tid, db_path=db_path)
    assert check["numbers"] == [] and check["minimum"] == "T2"  # frontmatter field change


def test_lowering_a_tier_needs_authority_and_it_is_stored_verbatim(db_path, repo):
    tid = make_task(db_path, "T2")
    api.set_tier(task_id=tid, tier="T3", reason="raised", db_path=db_path)
    with pytest.raises(ValidationError, match="verbatim"):
        api.set_tier(task_id=tid, tier="T1", reason="trim", db_path=db_path)
    with pytest.raises(ValidationError, match="verbatim"):
        api.set_tier(task_id=tid, tier="T1", reason="trim", authority="  ", db_path=db_path)
    quote = "Yes, treat this as a copy edit"
    entry = api.set_tier(task_id=tid, tier="T1", reason="trim", authority=quote, db_path=db_path)
    assert entry["tier"] == "T1" and entry["history"][-1]["authority"] == quote
    assert [h["to"] for h in entry["history"]] == ["T2", "T3", "T1"]


def test_tier_cannot_be_lowered_or_history_erased_through_raw_metadata(db_path, repo):
    tid = make_task(db_path, "T3")
    meta = json.loads(api.get_task(task_id=tid, db_path=db_path)["metadata"])
    lowered = {**meta["verificationTier"], "tier": "T1"}
    with pytest.raises(ValidationError, match="verbatim"):
        api.update_task(task_id=tid, metadata={"verificationTier": lowered}, db_path=db_path)
    with pytest.raises(ValidationError, match="append-only"):
        api.update_task(task_id=tid, metadata={"verificationTier": {**lowered, "history": []}}, db_path=db_path)
    assert tiers.effective_tier(json.loads(api.get_task(task_id=tid, db_path=db_path)["metadata"])) == "T3"


def test_untiered_task_is_t3_and_cannot_be_attested(db_path, repo):
    task = api.create_task(title="Plain", db_path=db_path)
    (repo / "doc.md").write_text(DOC.replace("OLD", "NEW"))
    shot(repo)
    with pytest.raises(ValidationError, match="no recorded tier"):
        t1(db_path, task["id"])
    with pytest.raises(ValidationError, match="T3"):
        api.attest(task_id=task["id"], tier="T3", inputs={}, db_path=db_path)
    assert tiers.effective_tier({}) == "T3"


def test_hand_typed_receipt_never_approves(db_path, repo):
    tid = make_task(db_path)
    (repo / "doc.md").write_text(DOC.replace("OLD", "NEW"))
    api.store_wp(task_id=tid, type_="test", title="fake", content="TIER: T1\nRESULT: PASSED\nATTEST-RECEIPT: " + "a" * 64, db_path=db_path)
    qa = approved(db_path, tid)
    assert not qa["approved"] and "Forged" in qa["reason"]
    with pytest.raises(ValidationError, match="QA gate"):
        api.update_task(task_id=tid, status="completed", db_path=db_path)


def test_altered_attestation_row_is_rejected(db_path, repo):
    tid = make_task(db_path)
    (repo / "doc.md").write_text(DOC.replace("OLD", "NEW"))
    shot(repo)
    t1(db_path, tid)
    import sqlite3
    conn = sqlite3.connect(db_path)
    payload = json.loads(conn.execute("SELECT payload FROM attestations").fetchone()[0])
    payload["tier"] = "T2"
    conn.execute("UPDATE attestations SET payload=?", (json.dumps(payload, sort_keys=True),))
    conn.commit(); conn.close()
    assert "altered" in approved(db_path, tid)["reason"]


def test_edit_after_attestation_makes_it_stale(db_path, repo):
    tid = make_task(db_path)
    (repo / "doc.md").write_text(DOC.replace("OLD", "NEW"))
    shot(repo)
    t1(db_path, tid)
    assert approved(db_path, tid)["approved"]
    (repo / "doc.md").write_text(DOC.replace("OLD", "NEW") + "More.\n")
    qa = approved(db_path, tid)
    assert not qa["approved"] and "stale" in qa["reason"]


def test_logic_change_after_attestation_stops_approving(db_path, repo):
    tid = make_task(db_path)
    (repo / "doc.md").write_text(DOC.replace("OLD", "NEW"))
    shot(repo)
    t1(db_path, tid)
    (repo / "logic.py").write_text("def f():\n    return 99\n")
    assert not approved(db_path, tid)["approved"]


def test_delta_after_approved_t3_carries_forward(db_path, repo):
    contract = {"schemaVersion": 2, "criteria": [{"id": "C1", "expected": "Doc reads right"}], "sources": ["doc.md", "page.html"]}
    task = api.create_task(title="Feature", metadata={"requiresQa": True, "acceptanceContract": contract}, db_path=db_path)
    tid = task["id"]
    identity = api.capture_qa_identity(task_id=tid, db_path=db_path)["identity_line"]
    packet = f"CRITERION: C1\nEXPECTED: Doc reads right\nOBSERVED: it does\n{identity}\nBASELINE: none\nARTIFACT: test-run|ok\nUNTESTED: none\nVERDICT: APPROVED\n"
    api.store_wp(task_id=tid, type_="test", title="QA", content=packet, db_path=db_path)
    assert approved(db_path, tid)["approved"]
    # Title change after approval: full identity is stale, the delta is copy only.
    (repo / "doc.md").write_text(DOC.replace("OLD", "NEW"))
    assert not approved(db_path, tid)["approved"]
    api.set_tier(task_id=tid, tier="T1", reason="title change after approval", db_path=db_path)
    shot(repo)
    result = t1(db_path, tid)
    assert result["files"] == ["doc.md"]
    assert approved(db_path, tid)["approved"]
    # A logic-bearing delta is not carried.
    (repo / "page.html").write_text(PAGE.replace("</body>", "<script>x()</script></body>"))
    assert not approved(db_path, tid)["approved"]
    assert api.check_tier(task_id=tid, db_path=db_path)["minimum"] == "T3"


def test_test_map_can_mark_paths_always_t3(db_path, repo):
    (repo / ".copilot" / "test-map.json").write_text(json.dumps({"doc.md": {"focused": "true", "tier": "T3"}}))
    tid = make_task(db_path)
    (repo / "doc.md").write_text(DOC.replace("OLD", "NEW"))
    check = api.check_tier(task_id=tid, db_path=db_path)
    assert check["minimum"] == "T3" and "test-map" in " ".join(check["triggers"])
    (repo / ".copilot" / "test-map.json").write_text(json.dumps({"doc.md": {"focused": "true", "tier": "T2"}}))
    with pytest.raises(ValidationError, match="T3"):
        api.check_tier(task_id=tid, db_path=db_path)


def test_qa_packet_prefills_identity_and_exact_criteria_and_passes(db_path, repo):
    contract = {"schemaVersion": 2, "criteria": [{"id": "C1", "expected": "First holds"}, {"id": "C2", "expected": "Second holds"}], "sources": ["doc.md"]}
    task = api.create_task(title="T3 work", metadata={"requiresQa": True, "acceptanceContract": contract}, db_path=db_path)
    tid = task["id"]
    earlier = f"CRITERION: C1\nEXPECTED: First holds\nOBSERVED: seen working\n{api.capture_qa_identity(task_id=tid, db_path=db_path)['identity_line']}\nBASELINE: none\nARTIFACT: test-run|ok\nVERDICT: REJECTED\n"
    wp = api.store_wp(task_id=tid, type_="test", title="Round 1", content=earlier, db_path=db_path)
    packet = api.qa_packet(task_id=tid, carry=[f"WP-{wp['id']}:C1"], db_path=db_path)
    assert "EXPECTED: First holds" in packet and "EXPECTED: Second holds" in packet and "IDENTITY: {" in packet
    assert f"OBSERVED: Carried forward from WP-{wp['id']}: seen working" in packet and "OBSERVED: <fill>" in packet
    filled = packet.replace("OBSERVED: <fill>", "OBSERVED: second seen").replace("BASELINE: <fill>", "BASELINE: none").replace("ARTIFACT: <fill>", "ARTIFACT: test-run|ok").replace("UNTESTED: <fill, or none>", "UNTESTED: none").replace("VERDICT: <APPROVED | REJECTED>", "VERDICT: APPROVED")
    api.store_wp(task_id=tid, type_="test", title="Round 2", content=filled, db_path=db_path)
    assert approved(db_path, tid)["approved"]
    with pytest.raises(ValidationError, match="no result for criterion"):
        api.qa_packet(task_id=tid, carry=[f"WP-{wp['id']}:C2"], db_path=db_path)


def test_t3_packet_path_is_unchanged_for_tiered_t3_task(db_path, repo):
    task = api.create_task(title="Strict", metadata={"requiresQa": True}, db_path=db_path)
    api.set_tier(task_id=task["id"], tier="T3", reason="new feature", db_path=db_path)
    text = ("CRITERION: guarded behavior holds\nEXPECTED: completion is blocked without evidence\nOBSERVED: blocked\nIDENTITY: fixture\nBASELINE: none\n"
            "ARTIFACT: test-run|pytest exit=0\nUNTESTED: none\nVERDICT: APPROVED\n")
    api.store_wp(task_id=task["id"], type_="test", title="QA", content=bind_packet(task, db_path, text), db_path=db_path)
    assert approved(db_path, task["id"])["approved"]


def test_cli_tier_check_attest_and_done_block(cli, db_path, repo):
    created = json.loads(cli(["task", "create", "--title", "CLI", "--json"]).output)
    tid = str(created["id"])
    assert cli(["task", "tier", tid, "T1", "--reason", "copy"]).exit_code == 0
    (repo / "doc.md").write_text(DOC.replace("OLD", "NEW"))
    shot(repo)
    out = cli(["task", "tier", tid, "--check", "--json"])
    assert json.loads(out.output)["minimum"] == "T1"
    low = cli(["task", "tier", tid, "T1", "--reason", "x"])
    assert low.exit_code == 0
    att = cli(["task", "attest", tid, "--tier", "T1", "--in", "doc.md", "--present", "NEW title", "--absent", "OLD title", "--load", ".copilot/evidence/load.png", "--json"])
    assert att.exit_code == 0, att.output
    assert check_task_qa(task_id=int(tid), db_path=db_path)["approved"]
    refused = cli(["task", "attest", tid, "--tier", "T1", "--in", "doc.md", "--present", "gone", "--absent", "OLD title", "--load", ".copilot/evidence/load.png"])
    assert refused.exit_code != 0
    block = repo / "block.txt"
    block.write_text("Done means: title changed\nTier: T2 structural\n")
    other = json.loads(cli(["task", "create", "--title", "DB", "--json"]).output)["id"]
    reg = cli(["task", "contract", str(other), "--from-done-block", str(block), "--kind", "document", "--source", "doc.md"])
    assert reg.exit_code == 0, reg.output
    meta = json.loads(api.get_task(task_id=other, db_path=db_path)["metadata"])
    assert meta["verificationTier"]["tier"] == "T2" and "tier" not in meta["acceptanceContract"]
