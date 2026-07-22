import json
import subprocess

from cc.commands.onboard import build_personal_onboard_report


class FakeGitHub:
    def __init__(self, repos=None, errors=None):
        self.repos = dict(repos or {})
        self.errors = set(errors or ())
        self.calls = []

    def __call__(self, args):
        args = tuple(args)
        self.calls.append(args)
        if args[:4] == ("gh", "api", "user", "--jq"):
            return subprocess.CompletedProcess(args, 0, "pablo\n", "")
        if "POST" in args:
            name = args[args.index("-f") + 1].removeprefix("name=")
            self.repos[name] = True
            return subprocess.CompletedProcess(args, 0, "{}", "")
        name = args[2].rsplit("/", 1)[-1]
        if name in self.errors:
            return subprocess.CompletedProcess(args, 1, "", "network unavailable")
        if name not in self.repos:
            return subprocess.CompletedProcess(args, 1, "", "gh: Not Found (HTTP 404)")
        return subprocess.CompletedProcess(args, 0, json.dumps({"private": self.repos[name]}), "")


def test_plan_reuses_private_and_marks_only_404_missing():
    gh = FakeGitHub({"claude-copilot-private": True})
    report = build_personal_onboard_report(components=("claude", "codex"), run=gh)
    assert report["result"] == "changes-required"
    assert [row["state"] for row in report["repositories"]] == ["existing-private", "missing"]
    assert not any("POST" in call for call in gh.calls)


def test_apply_creates_missing_private_repository():
    gh = FakeGitHub()
    report = build_personal_onboard_report(components=("codex",), apply=True, run=gh)
    assert report["result"] == "applied"
    assert report["repositories"][0]["state"] == "created"
    post = next(call for call in gh.calls if "POST" in call)
    assert "private=true" in post
    assert "auto_init=true" in post


def test_unknown_read_blocks_all_creation():
    gh = FakeGitHub(errors={"codex-copilot-private"})
    report = build_personal_onboard_report(components=("claude", "codex"), apply=True, run=gh)
    assert report["result"] == "blocked"
    assert report["repositories"][1]["state"] == "unknown"
    assert not any("POST" in call for call in gh.calls)


def test_public_collision_blocks_all_creation():
    gh = FakeGitHub({"codex-copilot-private": False})
    report = build_personal_onboard_report(components=("claude", "codex"), apply=True, run=gh)
    assert report["result"] == "blocked"
    assert report["repositories"][1]["state"] == "conflict-public"
    assert not any("POST" in call for call in gh.calls)
