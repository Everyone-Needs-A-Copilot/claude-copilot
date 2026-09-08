"""Real-process and adversarial checks for the opt-in verification boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest
from typer.testing import CliRunner

from cc.core.verification import VerificationError, build_plan, changed_paths, read_status, run_plan
from cc.main import app


@pytest.fixture
def project(tmp_path):
    (tmp_path / "source.py").write_text("value = 7\n")
    (tmp_path / "check.py").write_text("print('observable check', flush=True)\n")
    manifest = {
        "schemaVersion": 1, "inputs": ["source.py", "check.py"], "fallbackLanes": ["broad"],
        "lanes": [
            {"id": "focused", "description": "Focused behavior", "paths": ["source.py"],
             "argv": ["{python}", "check.py"], "cwd": ".", "timeoutSeconds": 3, "hermetic": True},
            {"id": "broad", "description": "Unknown-impact fallback", "paths": [],
             "argv": ["{python}", "check.py"], "cwd": ".", "timeoutSeconds": 3},
        ],
    }
    (tmp_path / "verification.json").write_text(json.dumps(manifest))
    return tmp_path


def modify_manifest(root, callback):
    path = root / "verification.json"
    value = json.loads(path.read_text())
    callback(value)
    path.write_text(json.dumps(value))


def focused(root, **kwargs):
    return build_plan(root, changed=["source.py"], **kwargs)


def test_plan_is_dry_and_mixed_unknown_paths_broaden(project):
    (project / "check.py").write_text("raise SystemExit('must not execute during plan')")
    assert [lane["id"] for lane in focused(project)["lanes"]] == ["focused"]
    mixed = build_plan(project, changed=["source.py", "unmapped.py"])
    assert {lane["id"] for lane in mixed["lanes"]} == {"focused", "broad"}
    assert "unknown impact" in mixed["lanes"][0]["reasons"][0]
    assert [lane["id"] for lane in build_plan(project)["lanes"]] == ["broad"]
    assert not (project / ".copilot").exists()


def test_explicit_lane_has_narrow_scope_warning(project):
    plan = build_plan(project, lanes=["focused"], changed=["unmapped.py"])
    assert "not an assertion" in plan["lanes"][0]["reasons"][0]
    with pytest.raises(VerificationError, match="Unknown requested"):
        build_plan(project, lanes=["nonexistent"])


def test_real_success_failure_and_status_keep_partial_output(project):
    progress = []
    report = run_plan(project, focused(project), progress=progress.append, heartbeat=0.05)
    assert report["status"] == "passed"
    assert progress[0]["status"] == "running"
    assert progress[0]["runId"] == report["runId"]
    assert progress[0]["artifactPath"] == report["artifactPath"]
    assert read_status(project, report["runId"]) == report
    log = Path(report["artifactPath"]) / "focused/stdout.log"
    assert log.read_text() == "observable check\n"
    assert report["artifactHashes"]["focused/stdout.log"]
    (project / "check.py").write_text("import sys\nprint('before failure', flush=True)\nsys.exit(7)\n")
    failed = run_plan(project, focused(project))
    assert failed["status"] == "failed"
    assert failed["lanes"][0]["exitCode"] == 7
    assert "before failure" in (Path(failed["artifactPath"]) / "focused/stdout.log").read_text()


@pytest.mark.parametrize("change", ["command", "source", "dependency", "config", "data", "environment", "runtime"])
def test_changed_inputs_invalidate_saved_plan_and_reuse(project, monkeypatch, change):
    for name in ("lock.txt", "config.json", "seed.json"):
        (project / name).write_text("original")
    modify_manifest(project, lambda manifest: manifest["inputs"].extend(["lock.txt", "config.json", "seed.json"]))
    plan = focused(project)
    first = run_plan(project, plan)
    if change == "command":
        modify_manifest(project, lambda manifest: manifest["lanes"][0]["argv"].append("new-argument"))
    elif change == "environment":
        monkeypatch.setenv("VERIFY_TEST_CONFIG", "changed")
    elif change == "runtime":
        monkeypatch.setattr("cc.core.verification.platform.platform", lambda: "different-runtime")
    else:
        names = {"source": "source.py", "dependency": "lock.txt", "config": "config.json", "data": "seed.json"}
        (project / names[change]).write_text("changed")
    with pytest.raises(VerificationError, match="stale"):
        run_plan(project, plan, reuse=True)
    fresh = run_plan(project, focused(project), reuse=True)
    assert "reusedFrom" not in fresh
    assert fresh["fingerprint"] != first["fingerprint"]


def test_reuse_is_opt_in_integrity_checked_and_not_task_approval(project):
    first = run_plan(project, focused(project, task="TASK-1"))
    second = run_plan(project, focused(project, task="TASK-2"), reuse=True)
    assert second["reusedFrom"] == first["runId"]
    assert second["task"] == "TASK-2"
    assert second["approval"] == "none; tc alone grants task approval"
    third = run_plan(project, focused(project, task="TASK-3"), reuse=True)
    assert third["reusedFrom"] == first["runId"]  # No unvalidated reference chains.
    rerun = run_plan(project, focused(project))
    assert "reusedFrom" not in rerun
    for report in (first, rerun):
        (Path(report["artifactPath"]) / "focused/stdout.log").write_text("tampered")
    assert "reusedFrom" not in run_plan(project, focused(project), reuse=True)


def test_nonhermetic_and_incomplete_results_are_never_reused(project):
    broad = build_plan(project)
    run_plan(project, broad)
    assert "reusedFrom" not in run_plan(project, broad, reuse=True)
    (project / "check.py").write_text("import time\nprint('partial', flush=True)\ntime.sleep(2)\n")
    modify_manifest(project, lambda manifest: manifest["lanes"][0].update(timeoutSeconds=0.15))
    plan = focused(project)
    first = run_plan(project, plan)
    assert first["status"] == "incomplete"
    assert first["lanes"][0]["reason"] == "timeout"
    assert "partial" in (Path(first["artifactPath"]) / "focused/stdout.log").read_text()
    assert "reusedFrom" not in run_plan(project, plan, reuse=True)


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(schemaVersion=90),
    lambda p: p["lanes"][0]["argv"].append("injected"),
    lambda p: p["lanes"][0].update(cwd="../"),
    lambda p: p.update(fingerprint="fake"),
    lambda p: p.update(selection={}),
])
def test_modified_or_unknown_plan_is_rejected_before_execution(project, mutation):
    plan = focused(project)
    mutation(plan)
    with pytest.raises(VerificationError):
        run_plan(project, plan)
    assert not (project / ".copilot").exists()


@pytest.mark.parametrize("mutation", [
    lambda m: m.update(schemaVersion=90),
    lambda m: m.update(unknown="ignored?"),
    lambda m: m["lanes"][0].update(cwd="../"),
    lambda m: m["lanes"][0].update(junit="../escape.xml"),
    lambda m: m["lanes"][0].update(junit="status.json"),
    lambda m: m["lanes"][0].update(timeoutSeconds=float("inf")),
    lambda m: m["lanes"][0].update(timeoutSeconds=0),
    lambda m: m["lanes"][0].update(timeoutSeconds=901),
    lambda m: m.update(inputs=["../escape"]),
    lambda m: m.update(inputs=["."]),
])
def test_manifest_rejects_unsafe_or_unknown_contract(project, mutation):
    modify_manifest(project, mutation)
    with pytest.raises(VerificationError):
        focused(project)


def test_source_and_artifact_symlink_escape_rejected(project, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "source.py").write_text("secret")
    (project / "source.py").unlink()
    (project / "source.py").symlink_to(outside / "source.py")
    with pytest.raises(VerificationError, match="escapes"):
        focused(project)
    (project / "source.py").unlink()
    (project / "source.py").write_text("safe")
    (project / ".copilot").symlink_to(outside, target_is_directory=True)
    with pytest.raises(VerificationError):
        run_plan(project, focused(project))
    assert list(outside.iterdir()) == [outside / "source.py"]
    with pytest.raises(VerificationError):
        read_status(project, "../outside")


def test_in_root_directory_symlink_and_changed_file_mode_invalidate(project):
    (project / "data").mkdir()
    (project / "data/seed").write_text("seven")
    (project / "alias").symlink_to(project / "data", target_is_directory=True)
    modify_manifest(project, lambda m: m["inputs"].append("alias"))
    with pytest.raises(VerificationError, match="Directory symlink"):
        focused(project)
    modify_manifest(project, lambda m: m["inputs"].remove("alias"))
    plan = focused(project)
    (project / "check.py").chmod(0o700)
    with pytest.raises(VerificationError, match="stale"):
        run_plan(project, plan)


def test_status_symlink_and_tampered_status_cannot_be_reused(project):
    report = run_plan(project, focused(project))
    path = Path(report["artifactPath"]) / "status.json"
    changed = json.loads(path.read_text())
    changed["lanes"][0]["exitCode"] = 77
    path.write_text(json.dumps(changed))
    second = run_plan(project, focused(project), reuse=True)
    assert "reusedFrom" not in second
    path.unlink()
    path.symlink_to(Path(second["artifactPath"]) / "status.json")
    with pytest.raises(VerificationError, match="symlink"):
        read_status(project, report["runId"])


def test_generated_symlink_artifact_is_incomplete_not_reusable(project):
    (project / "check.py").write_text("import pathlib,sys\npathlib.Path(sys.argv[1]).symlink_to(pathlib.Path('source.py').resolve())\n")
    modify_manifest(project, lambda m: m["lanes"][0].update(argv=["{python}", "check.py", "{artifact_dir}/escape"]))
    report = run_plan(project, focused(project))
    assert report["status"] == "incomplete"
    assert report["reason"] == "unsafe or unreadable generated artifact"
    assert read_status(project, report["runId"])["status"] == "incomplete"


def test_required_junit_retains_case_ids_skips_and_failures(project):
    xml = '<testsuite><testcase classname="checks" name="pass"/><testcase classname="checks" name="skip"><skipped message="platform unavailable"/></testcase></testsuite>'
    (project / "check.py").write_text("import pathlib,sys\npathlib.Path(sys.argv[1]).write_text(" + repr(xml) + ")\n")
    modify_manifest(project, lambda m: m["lanes"][0].update(argv=["{python}", "check.py", "{artifact_dir}/result.xml"], junit="result.xml"))
    report = run_plan(project, focused(project))
    assert report["status"] == "passed"
    tests = report["lanes"][0]["tests"]
    assert tests["counts"] == {"passed": 1, "skipped": 1, "failure": 0, "error": 0}
    assert tests["cases"][1] == {"id": "checks::skip", "status": "skipped", "reason": "platform unavailable"}
    (project / "check.py").write_text("import pathlib,sys\npathlib.Path(sys.argv[1]).write_text('<testsuite><testcase name=\"broken\"><failure message=\"wrong value\"/></testcase></testsuite>')\n")
    assert run_plan(project, focused(project))["status"] == "failed"
    (project / "check.py").write_text("print('no report')\n")
    assert run_plan(project, focused(project))["status"] == "incomplete"
    (project / "check.py").write_text("import pathlib,sys\npathlib.Path(sys.argv[1]).write_text('<testsuite><testcase name=\"skipped\"><skipped message=\"unsupported\"/></testcase></testsuite>')\n")
    skipped = run_plan(project, focused(project))
    assert skipped["status"] == "incomplete"
    assert skipped["lanes"][0]["tests"]["counts"]["skipped"] == 1


def test_shell_adapter_failure_exit_and_cli_status_nonzero(project):
    (project / "check.sh").write_text("printf 'shell failure evidence\\n'\nexit 9\n")
    modify_manifest(project, lambda m: m["lanes"][0].update(argv=["sh", "check.sh"], inputs=["check.sh"]))
    runner = CliRunner()
    plan_file = project / "plan.json"
    plan_file.write_text(json.dumps(focused(project)))
    result = runner.invoke(app, ["verify", "run", "--root", str(project), "--plan", str(plan_file), "--json"])
    assert result.exit_code == 1, result.output
    report = json.loads(result.stdout)
    assert report["lanes"][0]["exitCode"] == 9
    status = runner.invoke(app, ["verify", "status", "--root", str(project), "--run", report["runId"], "--json"])
    assert status.exit_code == 1
    assert json.loads(status.stdout)["status"] == "failed"


def test_real_pytest_adapter_and_cli_json_stdout(project):
    (project / "test_example.py").write_text("import pytest\ndef test_pass():\n    assert 1 + 1 == 2\n@pytest.mark.skip(reason='explicit unsupported platform')\ndef test_skip():\n    assert False\n")
    modify_manifest(project, lambda m: m["lanes"][0].update(
        argv=["{python}", "-m", "pytest", "test_example.py", "-q", "-p", "no:cacheprovider", "--junitxml={artifact_dir}/results.xml"],
        inputs=["test_example.py"], junit="results.xml", timeoutSeconds=10))
    runner = CliRunner()
    result = runner.invoke(app, ["verify", "plan", "--root", str(project), "--changed", "source.py", "--json"])
    assert result.exit_code == 0, result.output
    plan_file = project / "saved-plan.json"
    plan_file.write_text(result.stdout)
    result = runner.invoke(app, ["verify", "run", "--root", str(project), "--plan", str(plan_file), "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert "elapsed=" in result.stderr
    first_line = result.stderr.splitlines()[0]
    assert f"run={report['runId']}" in first_line
    assert f"artifacts={report['artifactPath']}" in first_line
    assert result.stderr.index(first_line) < result.stderr.index("elapsed=")
    assert report["lanes"][0]["tests"]["counts"]["skipped"] == 1
    status = runner.invoke(app, ["verify", "status", "--root", str(project), "--run", report["runId"], "--json"])
    assert status.exit_code == 0
    assert json.loads(status.stdout) == report


def test_heartbeat_continues_when_child_closes_output(project):
    (project / "check.py").write_text("import os,time\nos.close(1)\nos.close(2)\ntime.sleep(.25)\n")
    progress = []
    assert run_plan(project, focused(project), heartbeat=0.05, progress=progress.append)["status"] == "passed"
    assert len([p for p in progress if p["status"] == "running"]) >= 3


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A reaped/adopted zombie cannot execute; POSIX process cleanup is complete.
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


@pytest.mark.parametrize("mode", ["timeout", "cancel"])
def test_owned_descendants_stop_and_unrelated_process_survives(project, mode):
    script = "import subprocess,sys,time,os\nchild=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'])\nprint(child.pid, flush=True)\ntime.sleep(60)\n"
    (project / "check.py").write_text(script)
    modify_manifest(project, lambda m: m["lanes"][0].update(timeoutSeconds=0.5 if mode == "timeout" else 10))
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    executor = None
    try:
        if mode == "timeout":
            report = run_plan(project, focused(project))
        else:
            # Build/run in the same child so runtime/env identity stays exact.
            source = "from pathlib import Path; import json; from cc.core.verification import build_plan,run_plan; root=Path(" + repr(str(project)) + "); print(json.dumps(run_plan(root,build_plan(root,changed=['source.py']))),flush=True)"
            executor = subprocess.Popen([sys.executable, "-c", source], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            deadline = time.monotonic() + 5
            log = None
            while time.monotonic() < deadline:
                logs = list(project.glob(".copilot/verification/*/focused/stdout.log"))
                if logs and logs[0].read_text().strip():
                    log = logs[0]
                    break
                time.sleep(0.02)
            assert log is not None, "Runner never started its child"
            executor.send_signal(signal.SIGTERM)
            stdout, stderr = executor.communicate(timeout=5)
            assert executor.returncode == 0, stderr
            report = json.loads(stdout)
        assert report["status"] == "incomplete"
        assert report["lanes"][0]["reason"] == ("timeout" if mode == "timeout" else "cancelled")
        descendant = int((Path(report["artifactPath"]) / "focused/stdout.log").read_text().strip())
        deadline = time.monotonic() + 2
        while _alive(descendant) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _alive(descendant)
        assert unrelated.poll() is None
    finally:
        if executor is not None and executor.poll() is None:
            executor.kill()
            executor.wait()
        unrelated.terminate()
        unrelated.wait(timeout=3)


def test_changes_during_execution_never_pass(project):
    (project / "check.py").write_text("from pathlib import Path\nPath('source.py').write_text('changed')\n")
    report = run_plan(project, focused(project))
    assert report["status"] == "incomplete"
    assert "inputs changed" in report["reason"]


@pytest.mark.parametrize("change", ["content", "created", "deleted"])
def test_unmapped_changed_paths_bind_content_and_missing_membership(project, change):
    path = project / "extra.txt"
    if change != "created":
        path.write_text("original")
    plan = build_plan(project, changed=["extra.txt"])
    assert [lane["id"] for lane in plan["lanes"]] == ["broad"]
    assert "extra.txt" not in json.loads((project / "verification.json").read_text())["inputs"]
    if change == "deleted":
        path.unlink()
    else:
        path.write_text("changed")
    assert build_plan(project, changed=["extra.txt"])["identity"]["inputs"] != plan["identity"]["inputs"]
    with pytest.raises(VerificationError, match="stale"):
        run_plan(project, plan)
    assert not (project / ".copilot").exists()


def test_git_review_base_includes_dirty_deleted_and_untracked(project):
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"], cwd=project, check=True)
    (project / "source.py").unlink()
    (project / "check.py").write_text("changed")
    (project / "new.py").write_text("new")
    assert changed_paths(project, "HEAD") == ["check.py", "new.py", "source.py"]
    with pytest.raises(VerificationError):
        changed_paths(project, "--output=unsafe")


def _initialize_git(root):
    for args in (["init", "-q"], ["add", "."],
                 ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, timeout=3)


def test_base_provenance_rechecks_new_unknown_changes_before_execution(project):
    _initialize_git(project)
    (project / "source.py").write_text("value = 8\n")
    output = CliRunner().invoke(app, ["verify", "plan", "--root", str(project), "--base", "HEAD", "--json"])
    assert output.exit_code == 0, output.output
    plan = json.loads(output.stdout)
    assert plan["selection"]["scope"] == "git-base-discovery"
    assert plan["selection"]["base"] == "HEAD"
    assert len(plan["selection"]["baseRevision"]) == 40
    assert [lane["id"] for lane in plan["lanes"]] == ["focused"]
    (project / "unknown-broken.py").write_text("broken")
    with pytest.raises(VerificationError, match="stale"):
        run_plan(project, plan)
    assert not (project / ".copilot").exists()
    assert {lane["id"] for lane in build_plan(project, base="HEAD")["lanes"]} == {"focused", "broad"}


def test_base_discovery_rechecks_changes_after_execution(project):
    (project / "check.py").write_text("from pathlib import Path\nPath('new-unmapped.py').write_text('new behavior')\n")
    _initialize_git(project)
    (project / "source.py").write_text("value = 8\n")
    report = run_plan(project, build_plan(project, base="HEAD"))
    assert report["status"] == "incomplete"
    assert "inputs changed" in report["reason"]
    assert read_status(project, report["runId"])["status"] == "incomplete"


def test_base_discovery_does_not_invalidate_itself_with_runner_artifacts(project):
    _initialize_git(project)
    (project / "source.py").write_text("value = 8\n")
    report = run_plan(project, build_plan(project, base="HEAD"))
    assert report["status"] == "passed"
    assert changed_paths(project, "HEAD") == ["source.py"]
    assert focused(project)["selection"]["scope"] == "declared-paths"
    declared = CliRunner().invoke(app, ["verify", "plan", "--root", str(project), "--changed", "source.py"])
    assert "not automatic whole-change discovery" in declared.stdout


def test_terminal_status_needs_full_integrity_and_running_snapshots_remain_readable(project):
    snapshots = []

    def read_progress(_current):
        run_id = next(project.glob(".copilot/verification/*/status.json")).parent.name
        snapshots.append(read_status(project, run_id))

    report = run_plan(project, focused(project), progress=read_progress)
    assert snapshots and all(snapshot["status"] == "running" for snapshot in snapshots)
    path = Path(report["artifactPath"]) / "status.json"
    malformed = {key: report[key] for key in ("schemaVersion", "kind", "runId", "status", "artifactPath")}
    for value in (malformed, {k: v for k, v in report.items() if k != "resultHash"},
                  {k: v for k, v in report.items() if k != "identity"}, dict(report, lanes=[])):
        path.write_text(json.dumps(value))
        output = CliRunner().invoke(app, ["verify", "status", "--root", str(project), "--run", report["runId"], "--json"])
        assert output.exit_code == 2
        assert "error" in json.loads(output.stdout)
    path.write_text(json.dumps(report))
    assert read_status(project, report["runId"]) == report


@pytest.mark.parametrize("xml", [
    '<testsuite tests="2" failures="1"><testcase name="pass"/></testsuite>',
    '<testsuite tests="1" errors="1"><testcase name="pass"/></testsuite>',
    '<unrelated><testcase name="pass"/></unrelated>',
    '<testsuite tests="invalid"><testcase name="pass"/></testsuite>',
    '<testsuite><properties><testcase name="pass"/></properties></testsuite>',
])
def test_junit_malformed_or_inconsistent_aggregates_never_pass(project, xml):
    (project / "check.py").write_text("import pathlib,sys\npathlib.Path(sys.argv[1]).write_text(" + repr(xml) + ")\n")
    modify_manifest(project, lambda m: m["lanes"][0].update(argv=["{python}", "check.py", "{artifact_dir}/results.xml"], junit="results.xml"))
    report = run_plan(project, focused(project))
    assert report["status"] == "incomplete"
    assert report["lanes"][0]["exitCode"] == 0  # A zero process exit must not conceal bad evidence.
    assert "JUnit" in report["lanes"][0]["reason"]


def test_junit_nested_summaries_count_cases_once_and_errors_outrank_skips(project):
    xml = '<testsuites tests="2" failures="0" errors="1"><testsuite tests="2" failures="0" errors="1"><testsuite tests="1" errors="1"><testcase name="bad"><skipped/><error message="real failure"/></testcase></testsuite><testcase name="pass"/></testsuite></testsuites>'
    (project / "check.py").write_text("import pathlib,sys\npathlib.Path(sys.argv[1]).write_text(" + repr(xml) + ")\n")
    modify_manifest(project, lambda m: m["lanes"][0].update(argv=["{python}", "check.py", "{artifact_dir}/results.xml"], junit="results.xml"))
    report = run_plan(project, focused(project))
    assert report["status"] == "failed"
    assert report["lanes"][0]["tests"]["counts"] == {"passed": 1, "failure": 0, "error": 1, "skipped": 0}
