"""Contract schemaVersion 4, done-block registration, the Unverified gate, and task review."""
import json

import pytest

from tc import api
from tc.db.exceptions import ValidationError
from tc.services.done_block import parse_done_block
from tc.services.qa import check_task_qa
from tc.services.qa_contract import validate_contract

CRIT = [{"id": "DONE", "expected": "A Word SOW I can send"}]


def v4(**kw):
    return {"schemaVersion": 4, "kind": "document", "criteria": CRIT, **kw}


class TestValidation:
    def test_software_needs_sources(self):
        with pytest.raises(ValidationError):
            validate_contract(v4(kind="software"))
        with pytest.raises(ValidationError):
            validate_contract(v4(kind="software", sources=[]))
        validate_contract(v4(kind="software", sources=["a.txt"]))

    @pytest.mark.parametrize("kind", ["document", "design", "research", "automation"])
    def test_non_software_sources_optional(self, kind):
        validate_contract(v4(kind=kind))
        validate_contract(v4(kind=kind, sources=[]))
        validate_contract(v4(kind=kind, sources=["a.txt"]))

    def test_kind_required_and_known(self):
        for bad in (None, "hardware"):
            c = v4()
            c["kind"] = bad
            with pytest.raises(ValidationError):
                validate_contract(c)

    def test_bad_source_still_rejected(self):
        with pytest.raises(ValidationError):
            validate_contract(v4(sources=["../x"]))

    @pytest.mark.parametrize("lane", [
        {"focused": "a", "affected": "b"},
        {"focused": "a", "affected": "b", "cap_seconds": 0},
        {"focused": "a", "affected": "b", "cap_seconds": "9"},
        {"focused": "", "affected": "b", "cap_seconds": 5},
        "fast",
    ])
    def test_bad_lane(self, lane):
        with pytest.raises(ValidationError):
            validate_contract(v4(lane=lane))

    def test_good_optional_fields(self):
        validate_contract(v4(lane={"focused": "a", "affected": "b", "cap_seconds": 60}, excluded=["x"], assumptions=["y"], provenBy="p", firstExample="e", doneBlock="Done means: z"))

    @pytest.mark.parametrize("key,val", [("excluded", "x"), ("excluded", [1]), ("assumptions", [""]), ("provenBy", 3), ("surprise", 1)])
    def test_bad_optional_fields(self, key, val):
        with pytest.raises(ValidationError):
            validate_contract(v4(**{key: val}))

    def test_v2_still_requires_sources_and_rejects_v1(self):
        with pytest.raises(ValidationError):
            validate_contract({"schemaVersion": 2, "criteria": CRIT, "sources": []})
        with pytest.raises(ValidationError):
            validate_contract({"schemaVersion": 5, "criteria": CRIT})


BLOCK = """> **Done means:** the deals page shows totals.
> **Proven by:** loading staging and one SQL query.
> **Not in scope:** the dashboard; MCP server, full e2e suite
> **Assumptions:** (1) "won" means closed-won. I will check the enum. (2) One currency. I will check deals.
> **First example:** the page rendered with real data.
> Yes, or edit?
"""


class TestParse:
    def test_bold_blockquote_and_numbering(self):
        p = parse_done_block(BLOCK)
        assert p["done"] == "the deals page shows totals."
        assert p["provenBy"] == "loading staging and one SQL query."
        assert p["excluded"] == ["the dashboard", "MCP server, full e2e suite"]
        assert p["assumptions"] == ['"won" means closed-won. I will check the enum.', "One currency. I will check deals."]
        assert p["firstExample"] == "the page rendered with real data."

    def test_plain_case_insensitive_comma_split_and_dotted_numbers(self):
        p = parse_done_block("DONE MEANS: ready\nnot in scope: a, b, ,c\nAssumptions: 1. first thing 2. second thing\n")
        assert p["excluded"] == ["a", "b", "c"]
        assert p["assumptions"] == ["first thing", "second thing"]
        assert "provenBy" not in p

    def test_done_means_required(self):
        with pytest.raises(ValidationError):
            parse_done_block("Proven by: x")


def _project_task(cli, db_path):
    created = json.loads(cli(["task", "create", "--title", "T", "--json"]).output)
    return created["id"]


class TestRegistration:
    def test_document_no_sources(self, cli, db_path, tmp_path):
        tid = _project_task(cli, db_path)
        f = tmp_path / "block.txt"
        f.write_text(BLOCK)
        r = cli(["task", "contract", str(tid), "--from-done-block", str(f), "--kind", "document", "--criterion", "SHEET=prices match the sheet"])
        assert r.exit_code == 0, r.output
        assert "Registered execution limits" in r.output
        meta = api.get_task(task_id=tid, db_path=db_path)["metadata"]
        meta = json.loads(meta) if isinstance(meta, str) else meta
        c = meta["acceptanceContract"]
        assert meta["requiresQa"] is True and c["schemaVersion"] == 4 and c["kind"] == "document"
        assert [x["id"] for x in c["criteria"]] == ["DONE", "SHEET"]
        assert c["doneBlock"] == BLOCK.strip() and "sources" not in c
        again = cli(["task", "contract", str(tid), "--from-done-block", str(f), "--kind", "document", "--criterion", "SHEET=prices match the sheet"])
        assert again.exit_code == 0, again.output
        assert "already registered" in again.output

    def test_software_without_source_fails_and_exclusive_flags(self, cli, db_path, tmp_path):
        tid = _project_task(cli, db_path)
        f = tmp_path / "block.txt"
        f.write_text(BLOCK)
        assert cli(["task", "contract", str(tid), "--from-done-block", str(f)]).exit_code != 0
        assert cli(["task", "contract", str(tid), "--from-done-block", str(f), "--file", str(f)]).exit_code != 0
        assert cli(["task", "contract", str(tid)]).exit_code != 0
        assert cli(["task", "contract", str(tid), "--from-done-block", str(f), "--kind", "document", "--lane-focused", "x"]).exit_code != 0

    def test_software_with_source_and_lane(self, cli, db_path, tmp_path):
        root = db_path.parent.parent
        (root / "app.txt").write_text("x\n")
        tid = _project_task(cli, db_path)
        f = tmp_path / "block.txt"
        f.write_text(BLOCK)
        r = cli(["task", "contract", str(tid), "--from-done-block", str(f), "--source", "app.txt", "--lane-focused", "pytest -q", "--lane-affected", "pytest", "--cap-seconds", "60"])
        assert r.exit_code == 0, r.output


def _packet(identity, untested="UNTESTED: none\n"):
    return (
        "CRITERION: DONE\nEXPECTED: A Word SOW I can send\nOBSERVED: reviewed, sendable\n"
        f"{identity}\nBASELINE: unavailable, new document\n"
        'ARTIFACT: test-run|pytest tests/x.py exit=0 "1 passed"\n' + untested + "VERDICT: APPROVED\n"
    )


class TestUnverifiedGate:
    def _task(self, db_path):
        t = api.create_task(title="SOW", db_path=db_path)
        api.update_task(task_id=t["id"], metadata={"requiresQa": True, "acceptanceContract": v4()}, db_path=db_path)
        return t["id"]

    def test_approves_without_sources(self, db_path):
        tid = self._task(db_path)
        ident = api.capture_qa_identity(task_id=tid, db_path=db_path)
        assert ident["identity"]["source_count"] == 0
        api.store_wp(task_id=tid, type_="test", title="QA", content=_packet(ident["identity_line"]), db_path=db_path)
        res = check_task_qa(task_id=tid, db_path=db_path)
        assert res["approved"], res["reason"]
        assert api.update_task(task_id=tid, status="completed", db_path=db_path)["status"] == "completed"

    def test_refuses_without_untested_line(self, db_path):
        tid = self._task(db_path)
        ident = api.capture_qa_identity(task_id=tid, db_path=db_path)
        api.store_wp(task_id=tid, type_="test", title="QA", content=_packet(ident["identity_line"], untested=""), db_path=db_path)
        res = check_task_qa(task_id=tid, db_path=db_path)
        assert not res["approved"] and "UNTESTED" in res["reason"]
        with pytest.raises(ValidationError, match="UNTESTED"):
            api.update_task(task_id=tid, status="completed", db_path=db_path)

    def test_v2_without_untested_unchanged(self, db_path):
        t = api.create_task(title="old", db_path=db_path)
        (db_path.parent.parent / "f.txt").write_text("x\n")
        api.update_task(task_id=t["id"], metadata={"requiresQa": True, "acceptanceContract": {"schemaVersion": 2, "criteria": CRIT, "sources": ["f.txt"]}}, db_path=db_path)
        ident = api.capture_qa_identity(task_id=t["id"], db_path=db_path)
        api.store_wp(task_id=t["id"], type_="test", title="QA", content=_packet(ident["identity_line"], untested=""), db_path=db_path)
        res = check_task_qa(task_id=t["id"], db_path=db_path)
        assert res["approved"], res["reason"]


class TestReview:
    def test_record_and_summary(self, cli, db_path):
        a = _project_task(cli, db_path)
        b = _project_task(cli, db_path)
        _project_task(cli, db_path)
        for t in (a, b):
            assert cli(["task", "update", str(t), "--status", "completed"]).exit_code == 0
        r = cli(["task", "review", str(a), "--authorization-repeated", "--note", "asked twice", "--json"])
        assert r.exit_code == 0, r.output
        meta = json.loads(api.get_task(task_id=a, db_path=db_path)["metadata"])
        rev = meta["review"]
        assert rev["authorizationRepeated"] is True and rev["scopeRecovered"] is False
        assert rev["note"] == "asked twice" and rev["recordedAt"]
        s = json.loads(cli(["task", "review", "--summary", "--json"]).output)
        assert s["tasksCompleted"] == 2 and s["tasksReviewed"] == 1 and s["authorizationRepeated"] == 1 and s["scopeRecovered"] == 0
        future = json.loads(cli(["task", "review", "--summary", "--since", "2999-01-01", "--json"]).output)
        assert future["tasksCompleted"] == 0 and future["tasksReviewed"] == 0
        assert "Task reviews" in cli(["task", "review", "--summary"]).output

    def test_errors(self, cli, db_path):
        assert cli(["task", "review", "999"]).exit_code != 0
        assert cli(["task", "review"]).exit_code != 0
        assert cli(["task", "review", "--summary", "--since", "yesterday"]).exit_code != 0
