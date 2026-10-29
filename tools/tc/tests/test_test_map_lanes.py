"""tc tests map, contract lane derivation, lane gate, and replay-by-default (--live)."""
import json
import subprocess
import sys

import pytest

from tc import api
from tc.db.exceptions import ValidationError
from tc.evidence import parse_packet
from tc.services.qa import check_task_qa

CRIT = [{"id": "DONE", "expected": "Totals show"}]
BLOCK = "Done means: totals show\n"


def j(res):
    assert res.exit_code == 0, res.output
    return json.loads(res.output)


@pytest.fixture
def mapped(cli):
    j(cli(["tests", "map", "set", "src/pages/**", "--focused", "vitest src/pages", "--affected", "playwright all"]))
    j(cli(["tests", "map", "set", "src/pages/deals/**", "--focused", "vitest deals", "--affected", "playwright deals", "--lane", "focused", "--cap-seconds", "90"]))
    j(cli(["tests", "map", "set", "db/**", "--focused", "pytest mig", "--affected", "pytest all", "--lane", "broad"]))
    return cli


class TestMap:
    def test_show_empty_set_remove(self, cli, db_path):
        assert j(cli(["tests", "map", "show", "--json"])) == {}
        assert "No test map" in cli(["tests", "map", "show"]).output
        j(cli(["tests", "map", "set", "a/**", "--focused", "f"]))
        shown = j(cli(["tests", "map", "show", "--json"]))
        assert shown == {"a/**": {"focused": "f", "affected": "f"}}
        j(cli(["tests", "map", "set", "release", "--broad", "make all"]))
        assert j(cli(["tests", "map", "show", "--json"]))["release"] == {"broad": "make all"}
        assert (db_path.parent / "test-map.json").exists()
        assert cli(["tests", "map", "remove", "a/**"]).exit_code == 0
        assert "a/**" not in j(cli(["tests", "map", "show", "--json"]))
        assert cli(["tests", "map", "remove", "a/**"]).exit_code != 0

    @pytest.mark.parametrize("args", [
        ["set", "a/**", "--focused", " "], ["set", "a/**"], ["set", "a/**", "--focused", "f", "--lane", "huge"],
        ["set", "a/**", "--focused", "f", "--cap-seconds", "0"], ["set", "release", "--focused", "f"], ["set", "/abs/**", "--focused", "f"],
        ["set", "../up/**", "--focused", "f"],
    ])
    def test_rejects_bad_entries(self, cli, args):
        assert cli(["tests", "map", *args]).exit_code != 0

    def test_most_specific_wins_and_defaults(self, mapped):
        r = j(mapped(["tests", "map", "select", "src/pages/deals/Header.tsx", "--json"]))
        assert r["matches"] == [{"path": "src/pages/deals/Header.tsx", "glob": "src/pages/deals/**"}]
        assert r["focused"] == ["vitest deals"] and r["lane"] == "focused" and r["cap_seconds"] == 90
        r = j(mapped(["tests", "map", "select", "src/pages/Home.tsx", "--json"]))
        assert r["lane"] == "affected" and r["cap_seconds"] == 180 and r["unmatched"] == []

    def test_union_dedupes_and_takes_widest_lane_and_cap(self, mapped):
        r = j(mapped(["tests", "map", "select", "src/pages/deals/a.tsx", "src/pages/deals/b.tsx", "src/pages/Home.tsx", "--json"]))
        assert r["focused"] == ["vitest deals", "vitest src/pages"]
        assert r["lane"] == "affected" and r["cap_seconds"] == 180
        r = j(mapped(["tests", "map", "select", "src/pages/Home.tsx", "db/001.sql", "--json"]))
        assert r["lane"] == "broad" and r["cap_seconds"] == 900

    def test_no_match_selects_broad(self, mapped):
        r = j(mapped(["tests", "map", "select", "docs/readme.md", "--json"]))
        assert r["lane"] == "broad" and r["cap_seconds"] == 900 and r["unmatched"] == ["docs/readme.md"]
        assert "broad lane" in r["note"] and r["focused"] == []
        out = mapped(["tests", "map", "select", "docs/readme.md"]).output
        assert "lane: broad" in out and "docs/readme.md" in out

    def test_no_map_at_all_is_broad(self, cli):
        assert j(cli(["tests", "map", "select", "x.py", "--json"]))["lane"] == "broad"

    def test_select_args(self, mapped):
        assert mapped(["tests", "map", "select"]).exit_code != 0
        assert mapped(["tests", "map", "select", "a", "--diff"]).exit_code != 0

    def test_diff(self, mapped, db_path):
        root = db_path.parent.parent
        run = lambda *a: subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=t", *a], cwd=root, check=True, capture_output=True)
        run("init", "-q")
        (root / "src/pages/deals").mkdir(parents=True)
        (root / "src/pages/deals/H.tsx").write_text("1\n")
        run("add", "-A")
        run("commit", "-qm", "base")
        (root / "src/pages/deals/H.tsx").write_text("2\n")
        r = j(mapped(["tests", "map", "select", "--diff", "--json"]))
        assert r["paths"] == ["src/pages/deals/H.tsx"] and r["lane"] == "focused"
        (root / "db").mkdir()
        (root / "db/new.sql").write_text("x\n")
        assert j(mapped(["tests", "map", "select", "--diff", "--json"]))["lane"] == "broad"
        run("add", "-A")
        run("commit", "-qm", "two")
        assert j(mapped(["tests", "map", "select", "--diff", "--base", "HEAD~1", "--json"]))["paths"] == ["db/new.sql", "src/pages/deals/H.tsx"]
        assert mapped(["tests", "map", "select", "--diff", "--base", "nope"]).exit_code != 0


class TestContractDerivation:
    def _task(self, cli):
        return j(cli(["task", "create", "--title", "T", "--json"]))["id"]

    def _contract(self, db_path, tid):
        meta = api.get_task(task_id=tid, db_path=db_path)["metadata"]
        return (json.loads(meta) if isinstance(meta, str) else meta)["acceptanceContract"]

    def test_done_block_derives_lane(self, mapped, db_path, tmp_path):
        root = db_path.parent.parent
        (root / "src/pages/deals").mkdir(parents=True)
        (root / "src/pages/deals/H.tsx").write_text("x\n")
        tid = self._task(mapped)
        f = tmp_path / "b.txt"
        f.write_text(BLOCK)
        r = mapped(["task", "contract", str(tid), "--from-done-block", str(f), "--source", "src/pages/deals/H.tsx"])
        assert r.exit_code == 0, r.output
        assert "Lane derived from the test map: focused, cap 90 s" in r.output
        assert self._contract(db_path, tid)["lane"] == {"focused": "vitest deals", "affected": "playwright deals", "cap_seconds": 90, "lane": "focused"}

    def test_explicit_lane_wins(self, mapped, db_path, tmp_path):
        root = db_path.parent.parent
        (root / "src/pages/deals").mkdir(parents=True)
        (root / "src/pages/deals/H.tsx").write_text("x\n")
        tid = self._task(mapped)
        f = tmp_path / "b.txt"
        f.write_text(BLOCK)
        r = mapped(["task", "contract", str(tid), "--from-done-block", str(f), "--source", "src/pages/deals/H.tsx", "--lane-focused", "a", "--lane-affected", "b", "--cap-seconds", "30"])
        assert r.exit_code == 0, r.output
        assert self._contract(db_path, tid)["lane"] == {"focused": "a", "affected": "b", "cap_seconds": 30}

    def test_file_contract_and_directory_source(self, mapped, db_path, tmp_path):
        root = db_path.parent.parent
        (root / "src/pages/deals").mkdir(parents=True)
        (root / "src/pages/deals/H.tsx").write_text("x\n")
        tid = self._task(mapped)
        f = tmp_path / "c.json"
        f.write_text(json.dumps({"schemaVersion": 4, "kind": "software", "criteria": CRIT, "sources": ["src/pages/deals"]}))
        assert mapped(["task", "contract", str(tid), "--file", str(f)]).exit_code == 0
        assert self._contract(db_path, tid)["lane"]["lane"] == "focused"

    def test_no_map_or_v2_leaves_no_lane(self, cli, db_path, tmp_path):
        root = db_path.parent.parent
        (root / "a.txt").write_text("x\n")
        tid = self._task(cli)
        f = tmp_path / "b.txt"
        f.write_text(BLOCK)
        assert cli(["task", "contract", str(tid), "--from-done-block", str(f), "--source", "a.txt"]).exit_code == 0
        assert "lane" not in self._contract(db_path, tid)
        j(cli(["tests", "map", "set", "a.txt", "--focused", "f"]))
        t2 = self._task(cli)
        c = tmp_path / "v2.json"
        c.write_text(json.dumps({"schemaVersion": 2, "criteria": CRIT, "sources": ["a.txt"]}))
        assert cli(["task", "contract", str(t2), "--file", str(c)]).exit_code == 0
        assert "lane" not in self._contract(db_path, t2)

    def test_unmapped_source_without_release_command_leaves_no_lane(self, mapped, db_path, tmp_path):
        (db_path.parent.parent / "zzz.txt").write_text("x\n")
        tid = self._task(mapped)
        f = tmp_path / "b.txt"
        f.write_text(BLOCK)
        r = mapped(["task", "contract", str(tid), "--from-done-block", str(f), "--source", "zzz.txt"])
        assert r.exit_code == 0 and "broad lane" in r.output
        assert "lane" not in self._contract(db_path, tid)


class TestParsing:
    @pytest.mark.parametrize("text,name,el,cap", [
        ("LANE: focused + affected, 112 s of a 180 s cap", "focused + affected", 112.0, 180.0),
        ("lane: focused - 20.5 seconds of a 60 s cap", "focused", 20.5, 60.0),
        ("LANE: affected 90s of an 180s cap", "affected", 90.0, 180.0),
    ])
    def test_lane(self, text, name, el, cap):
        lane = parse_packet(text)["lanes"][0]
        assert (lane["name"], lane["elapsed_seconds"], lane["cap_seconds"]) == (name, el, cap)

    def test_lane_without_numbers(self):
        assert parse_packet("LANE: focused")["lanes"][0]["elapsed_seconds"] is None

    def test_outside(self):
        p = parse_packet("OUTSIDE LANE: none\nOUTSIDE LANE: full suite — release gate owns it\nOUTSIDE LANE: pytest -x - flaky\n"
                         "outside lane: e2e/a.spec.ts: shared fixture\nOUTSIDE LANE: npm test\nOUTSIDE LANE: e2e/a.spec.ts:12\n")["outside_lane"]
        assert p[0]["none"] is True
        assert (p[1]["what"], p[1]["reason"]) == ("full suite", "release gate owns it")
        assert (p[2]["what"], p[2]["reason"]) == ("pytest -x", "flaky")
        assert (p[3]["what"], p[3]["reason"]) == ("e2e/a.spec.ts", "shared fixture")
        assert p[4]["reason"] is None and p[5]["reason"] is None

    def test_quoted_examples_ignored_and_lane_not_confused_with_outside(self):
        p = parse_packet("```\nLANE: focused, 1 s of a 60 s cap\n```\n    LANE: x\nOUTSIDE LANE: none\n")
        assert p["lanes"] == [] and len(p["outside_lane"]) == 1


LANE = {"focused": "pytest -q", "affected": "pytest", "cap_seconds": 180}


def _packet(ident, extra):
    return (
        "CRITERION: DONE\nEXPECTED: Totals show\nOBSERVED: shown\n" f"{ident}\nBASELINE: unavailable, new\n"
        'ARTIFACT: test-run|pytest exit=0 "1 passed"\nUNTESTED: none\n' + extra + "VERDICT: APPROVED\n"
    )


class TestLaneGate:
    def _gate(self, db_path, extra, lane=LANE, version=4):
        t = api.create_task(title="x", db_path=db_path)
        (db_path.parent.parent / "f.txt").write_text("x\n")
        contract = {"schemaVersion": 4, "kind": "software", "criteria": CRIT, "sources": ["f.txt"]}
        if version == 4 and lane:
            contract["lane"] = lane
        if version == 2:
            contract = {"schemaVersion": 2, "criteria": CRIT, "sources": ["f.txt"]}
        api.update_task(task_id=t["id"], metadata={"requiresQa": True, "acceptanceContract": contract}, db_path=db_path)
        ident = api.capture_qa_identity(task_id=t["id"], db_path=db_path)
        api.store_wp(task_id=t["id"], type_="test", title="QA", content=_packet(ident["identity_line"], extra), db_path=db_path)
        return check_task_qa(task_id=t["id"], db_path=db_path)

    def test_approved(self, db_path):
        res = self._gate(db_path, "LANE: focused + affected, 112 s of a 180 s cap\nOUTSIDE LANE: none\n")
        assert res["approved"], res["reason"]

    def test_approved_with_reasoned_outside_entry(self, db_path):
        res = self._gate(db_path, "LANE: focused, 20 s of a 180 s cap\nOUTSIDE LANE: full suite — touches the shared schema\n")
        assert res["approved"], res["reason"]

    def test_missing_lane_line(self, db_path):
        res = self._gate(db_path, "OUTSIDE LANE: none\n")
        assert not res["approved"] and "add a LANE: line" in res["reason"]

    def test_lane_line_without_elapsed(self, db_path):
        res = self._gate(db_path, "LANE: focused\nOUTSIDE LANE: none\n")
        assert not res["approved"] and "no elapsed time" in res["reason"]

    def test_over_cap(self, db_path):
        res = self._gate(db_path, "LANE: focused + affected, 181 s of a 180 s cap\nOUTSIDE LANE: none\n")
        assert not res["approved"] and "QA run exceeded the lane cap" in res["reason"] and "incomplete, not complete" in res["reason"]

    def test_over_contract_cap_even_if_line_claims_bigger_cap(self, db_path):
        res = self._gate(db_path, "LANE: broad, 500 s of a 900 s cap\nOUTSIDE LANE: none\n")
        assert not res["approved"] and "exceeded the lane cap" in res["reason"]

    def test_missing_outside_lane(self, db_path):
        res = self._gate(db_path, "LANE: focused, 20 s of a 180 s cap\n")
        assert not res["approved"] and "add an OUTSIDE LANE: line" in res["reason"]

    def test_outside_entry_without_reason(self, db_path):
        res = self._gate(db_path, "LANE: focused, 20 s of a 180 s cap\nOUTSIDE LANE: full 11000-test suite\n")
        assert not res["approved"] and "full 11000-test suite" in res["reason"] and "no reason" in res["reason"]

    def test_unchanged_without_lane_or_v2(self, db_path):
        assert self._gate(db_path, "", lane=None)["approved"]
        assert self._gate(db_path, "", version=2)["approved"]


class TestLive:
    @pytest.fixture
    def task(self, cli, db_path):
        root = db_path.parent.parent
        (root / "code.py").write_text("x = 1\n")
        t = api.create_task(title="x", db_path=db_path)
        api.update_task(task_id=t["id"], metadata={"requiresQa": True, "acceptanceContract": {"schemaVersion": 2, "criteria": CRIT, "sources": ["code.py"]}}, db_path=db_path)
        assert cli(["execution", "register", str(t["id"])]).exit_code == 0
        return t["id"]

    def _run(self, cli, task, *flags):
        prog = "import os,json;print(json.dumps({k:os.environ.get(k) for k in ('APP_ENV','API_MODE','API_STUB_MISS_BUDGET','API_STUB_COST_CAP_USD')}))"
        return cli(["execution", "run", str(task), "--criterion", "DONE", *flags, "--", sys.executable, "-c", prog])

    def _env(self, res):
        return json.loads(open(json.loads(res.output)["artifact"].replace("result.json", "output.log")).read())

    def test_default_is_replay_only(self, cli, task):
        res = self._run(cli, task)
        assert res.exit_code == 0, res.output
        assert self._env(res) == {"APP_ENV": "test", "API_MODE": "stub_strict", "API_STUB_MISS_BUDGET": "0", "API_STUB_COST_CAP_USD": "0"}

    @pytest.mark.parametrize("flags", [["--calls", "1"], ["--usd", "0.5"], ["--calls", "1", "--usd", "0.5"]])
    def test_calls_or_usd_without_live_rejected(self, cli, task, flags):
        res = self._run(cli, task, *flags)
        assert res.exit_code != 0 and "--live" in res.output

    @pytest.mark.parametrize("flags", [[], ["--calls", "1"], ["--usd", "0.5"], ["--calls", "0", "--usd", "0.5"]])
    def test_live_requires_positive_calls_and_usd(self, cli, task, flags):
        res = self._run(cli, task, "--live", *flags)
        assert res.exit_code != 0 and "greater than 0" in res.output

    def test_live_over_budget_keeps_decision_message(self, cli, task):
        res = self._run(cli, task, "--live", "--calls", "1", "--usd", "0.5")
        assert res.exit_code != 0 and "DECISION NEEDED" in res.output

    def test_live_within_budget_sets_miss_budget(self, cli, task):
        assert cli(["execution", "budget", "set", "--calls", "5", "--usd", "2", "--authority", "owner said so"]).exit_code == 0
        res = self._run(cli, task, "--live", "--calls", "2", "--usd", "0.5")
        assert res.exit_code == 0, res.output
        env = self._env(res)
        assert env["API_STUB_MISS_BUDGET"] == "2" and env["API_STUB_COST_CAP_USD"] == "0.5"

    def test_budget_show_json_and_hint(self, cli, db_path):
        b = j(cli(["execution", "budget", "show", "--json"]))
        assert b["remaining_cost_usd"] == 0
        args = ["execution", "stub-miss-hint", "--provider", "openrouter:anthropic/claude-sonnet-5-5", "--hash", "9c1e", "--test", "ai_quality::test_tone", "--adapter", "scripts/test.sh"]
        out = cli(args).output.strip()
        assert out == (f"No recording for openrouter:anthropic/claude-sonnet-5-5 with prompt hash 9c1e. Record it with: scripts/test.sh --live ai_quality::test_tone. "
                       f"Live calls charge the {b['project']} budget (remaining $0.00 of $0.00).")
        assert cli(["execution", "budget", "set", "--calls", "5", "--usd", "2.5", "--authority", "q"]).exit_code == 0
        assert "remaining $2.50 of $2.50" in cli(args).output
