"""Opt-in local verification: execution evidence, never task approval.

The repository manifest is executable project code. Plans are checked against it
and current inputs immediately before use; they are not a command trust boundary.
"""

from __future__ import annotations

import fnmatch
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from typing import Callable

SCHEMA_VERSION = 1
ARTIFACT_ROOT = ".copilot/verification"
LOG_LIMIT = 16 * 1024 * 1024
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}\Z")


class VerificationError(ValueError):
    """Invalid, stale, or unsafe verification input."""


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(root: Path, value: str, *, artifact: bool = False) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise VerificationError("Expected a nonempty repository-relative path")
    if ".." in Path(value).parts or ".git" in Path(value).parts:
        raise VerificationError("Path traversal and Git metadata are not allowed")
    path = root / value
    if artifact:
        current = root
        for part in Path(value).parts:
            current /= part
            if current.is_symlink():
                raise VerificationError("Artifact paths must not contain symlinks")
    if not path.resolve().is_relative_to(root.resolve()):
        raise VerificationError("Path escapes its root")
    return path


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise VerificationError(f"Cannot read JSON: {path.name}") from exc
    if not isinstance(value, dict) or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != SCHEMA_VERSION:
        raise VerificationError("Unsupported verification schemaVersion")
    return value


def _strings(value: object, name: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise VerificationError(f"{name} must be a list of nonempty strings")
    if nonempty and not value:
        raise VerificationError(f"{name} must not be empty")
    return value


def load_manifest(root: Path, name: str = "verification.json") -> dict:
    root = root.resolve()
    manifest = _read_json(_relative(root, name))
    if set(manifest) - {"schemaVersion", "inputs", "fallbackLanes", "lanes"}:
        raise VerificationError("Unknown manifest fields")
    _strings(manifest.get("inputs"), "inputs", nonempty=True)
    _strings(manifest.get("fallbackLanes"), "fallbackLanes", nonempty=True)
    lanes = manifest.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        raise VerificationError("lanes must not be empty")
    ids = set()
    for lane in lanes:
        if not isinstance(lane, dict) or set(lane) - {
            "id", "description", "paths", "argv", "cwd", "timeoutSeconds", "inputs", "hermetic", "junit"
        }:
            raise VerificationError("Unknown lane fields")
        lane_id = lane.get("id", "")
        if not isinstance(lane_id, str) or not _ID.fullmatch(lane_id) or lane_id in ids:
            raise VerificationError("Lane IDs must be safe and unique")
        ids.add(lane_id)
        if not isinstance(lane.get("description"), str) or not lane["description"]:
            raise VerificationError("Each lane needs a description")
        _strings(lane.get("paths"), "paths")
        _strings(lane.get("argv"), "argv", nonempty=True)
        _strings(lane.get("inputs", []), "lane inputs")
        if not _relative(root, lane.get("cwd", ".")).is_dir():
            raise VerificationError("Lane cwd must be an existing directory")
        cap = lane.get("timeoutSeconds")
        if isinstance(cap, bool) or not isinstance(cap, (int, float)) or not math.isfinite(cap) or not 0 < cap <= 900:
            raise VerificationError("Lane timeoutSeconds must be greater than 0 and at most 900")
        if not isinstance(lane.get("hermetic", False), bool):
            raise VerificationError("hermetic must be boolean")
        if "junit" in lane:
            _relative(root, lane["junit"], artifact=True)
            if Path(lane["junit"]).name in {"status.json", "plan.json", "stdout.log", "stderr.log"}:
                raise VerificationError("JUnit path collides with runner artifacts")
        for value in lane["argv"]:
            if "\x00" in value:
                raise VerificationError("NUL is not permitted in argv")
    if not set(manifest["fallbackLanes"]).issubset(ids):
        raise VerificationError("Unknown fallback lane")
    for value in manifest["inputs"] + [p for lane in lanes for p in lane.get("inputs", [])]:
        _relative(root, value)
        if value == "." or Path(value).as_posix().startswith(ARTIFACT_ROOT):
            raise VerificationError("Identity inputs must exclude generated verification artifacts")
    return manifest


def changed_paths(root: Path, base: str) -> list[str]:
    """Include committed, dirty, deleted, and untracked (nonignored) inputs."""
    if not base or base.startswith("-"):
        raise VerificationError("Invalid review base")
    paths = set()
    commands = [
        ["git", "diff", "--name-only", "-z", base, "--"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ]
    for argv in commands:
        try:
            output = subprocess.run(argv, cwd=root, capture_output=True, check=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise VerificationError("Cannot determine changed paths; provide --changed or a valid --base") from exc
        paths.update(p for p in output.stdout.decode().split("\0") if p)
    return sorted(p for p in paths if not p.startswith(ARTIFACT_ROOT + "/"))


def _base_revision(root: Path, base: str) -> str:
    if not isinstance(base, str) or not base or base.startswith("-"):
        raise VerificationError("Invalid review base")
    try:
        result = subprocess.run(["git", "rev-parse", "--verify", base + "^{commit}"], cwd=root,
                                capture_output=True, text=True, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise VerificationError("Cannot resolve review base to a commit") from exc
    return result.stdout.strip()


def _inputs_identity(root: Path, inputs: list[str]) -> dict:
    found = {}
    for name in sorted(set(inputs)):
        path = _relative(root, name)
        if path.is_symlink() and path.is_dir():
            raise VerificationError("Directory symlink inputs are ambiguous; list the actual source directory")
        if not path.exists():
            found[name] = "missing"
            continue
        candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
        if path.is_dir():
            found[name + "/"] = "directory"
        for child in candidates:
            rel = child.relative_to(root).as_posix()
            if any(part in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv"} for part in child.relative_to(root).parts):
                continue
            _relative(root, rel)
            if child.is_symlink():
                if child.is_dir():
                    raise VerificationError("Directory symlink inputs are ambiguous; list the actual source directory")
                found[rel + "@"] = os.readlink(child)
            if child.is_file():
                found[rel] = {"hash": _file_hash(child), "mode": child.stat().st_mode & 0o777}
    return found


def _executable(root: Path, lane: dict) -> Path:
    value = lane["argv"][0].replace("{python}", sys.executable)
    if "{artifact_dir}" in value:
        raise VerificationError("The executable cannot come from generated artifacts")
    if "/" in value:
        executable = Path(value) if Path(value).is_absolute() else root / lane.get("cwd", ".") / value
    else:
        located = shutil.which(value)
        if not located:
            raise VerificationError(f"Executable unavailable for lane {lane['id']}")
        executable = Path(located)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise VerificationError(f"Executable unavailable for lane {lane['id']}")
    return executable.absolute()


def build_plan(root: Path, *, manifest_name: str = "verification.json", changed: list[str] | None = None,
               lanes: list[str] | None = None, task: str | None = None, base: str | None = None) -> dict:
    root = root.resolve()
    manifest = load_manifest(root, manifest_name)
    if base is not None and changed is not None:
        raise VerificationError("Use either --base or --changed, not both")
    base_revision = _base_revision(root, base) if base is not None else None
    if base_revision is not None:
        changed = changed_paths(root, base_revision)
    changes = sorted(set(changed or []))
    for path in changes:
        _relative(root, path)
    requested = sorted(set(lanes or []))
    available = {lane["id"]: lane for lane in manifest["lanes"]}
    if any(lane not in available for lane in requested):
        raise VerificationError("Unknown requested lane")
    reasons: dict[str, list[str]] = {}
    if requested:
        reasons = {lane: ["explicit lane selection; not an assertion of complete change coverage"] for lane in requested}
    else:
        unknown = []
        for path in changes:
            matches = [lane["id"] for lane in manifest["lanes"] if any(fnmatch.fnmatchcase(path, pattern) for pattern in lane["paths"])]
            if not matches:
                unknown.append(path)
            for lane in matches:
                reasons.setdefault(lane, []).append(f"changed: {path}")
        if not changes or unknown:
            reason = "unknown impact: " + (", ".join(unknown) if unknown else "no changed paths provided")
            for lane in manifest["fallbackLanes"]:
                reasons.setdefault(lane, []).append(reason)
    selected = [dict(available[lane], reasons=reasons[lane]) for lane in sorted(reasons)]
    inputs = manifest["inputs"] + changes + [p for lane in selected for p in lane.get("inputs", [])]
    runtime = {
        "python": sys.version, "platform": platform.platform(),
        "runner": _file_hash(Path(__file__)),
        "packages": sorted((d.metadata.get("Name", ""), d.version) for d in importlib.metadata.distributions()),
        "executables": {lane["id"]: {"path": str(_executable(root, lane)), "hash": _file_hash(_executable(root, lane))} for lane in selected},
    }
    identity = {
        "manifest": _digest(manifest), "inputs": _digest(_inputs_identity(root, inputs)),
        "runtime": _digest(runtime), "environment": _digest(dict(os.environ)),
    }
    result = {
        "schemaVersion": SCHEMA_VERSION, "kind": "verification-plan", "root": str(root),
        "manifest": manifest_name, "task": task,
        "selection": {"changed": changes, "lanes": requested, "base": base, "baseRevision": base_revision,
                      "scope": "git-base-discovery" if base is not None else "declared-paths" if changed is not None else "unknown-impact"},
        "lanes": selected, "excludedLanes": sorted(set(available) - set(reasons)),
        "timeoutSeconds": sum(lane["timeoutSeconds"] for lane in selected), "identity": identity,
        "approval": "none; tc alone grants task approval",
    }
    # Task association is deliberately not execution identity or task approval.
    result["fingerprint"] = _digest({k: v for k, v in result.items() if k != "task"})
    return result


def validate_plan(root: Path, plan: dict) -> dict:
    try:
        if plan.get("schemaVersion") != SCHEMA_VERSION or plan.get("kind") != "verification-plan":
            raise VerificationError("Unsupported plan schema")
        selection = plan["selection"]
        base = selection["base"]
        changed = None if base is not None or selection["scope"] == "unknown-impact" else selection["changed"]
        current = build_plan(root, manifest_name=plan["manifest"], changed=changed,
                             lanes=selection["lanes"], task=plan["task"], base=base)
        if current != plan:
            raise VerificationError("Plan is stale or differs from the current repository manifest; create a new plan")
        return current
    except (KeyError, TypeError) as exc:
        raise VerificationError("Malformed verification plan") from exc


def _atomic_json(path: Path, value: dict) -> None:
    if path.is_symlink():
        raise VerificationError("Refusing symlink artifact")
    descriptor, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _run_dir(root: Path, run_id: str, *, create: bool = False) -> Path:
    if not isinstance(run_id, str) or not _ID.fullmatch(run_id):
        raise VerificationError("Invalid run ID")
    path = _relative(root, f"{ARTIFACT_ROOT}/{run_id}", artifact=True)
    if create:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.mkdir(mode=0o700)
    return path


def _validate_status(directory: Path, status: dict) -> None:
    required = {"task", "fingerprint", "identity", "lanes", "startedAt", "approval"}
    if (not required.issubset(status) or status.get("kind") != "verification-result" or status.get("runId") != directory.name
        or status.get("status") not in {"running", "passed", "failed", "incomplete"}
        or status.get("artifactPath") != str(directory) or not isinstance(status["lanes"], list)
        or not isinstance(status["identity"], dict)
        or set(status["identity"]) != {"manifest", "inputs", "runtime", "environment"}
        or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
               for v in [status["fingerprint"], *status["identity"].values()])
        or status["approval"] != "none; tc alone grants task approval"):
        raise VerificationError("Malformed verification status")
    if status["status"] == "running":
        return  # Atomic progress snapshots are nonterminal and never return CLI success.
    if (not {"finishedAt", "artifactHashes", "resultHash"}.issubset(status)
        or not isinstance(status["artifactHashes"], dict)
        or status["resultHash"] != _digest({k: v for k, v in status.items() if k != "resultHash"})):
        raise VerificationError("Terminal verification status is incomplete or has invalid integrity")
    if any(type(status[key]) not in (int, float) or not math.isfinite(status[key]) for key in ("startedAt", "finishedAt")):
        raise VerificationError("Malformed terminal timestamps")
    if status["finishedAt"] < status["startedAt"]:
        raise VerificationError("Malformed terminal timestamp order")
    saved_plan = _read_json(_relative(directory, "plan.json", artifact=True))
    if (saved_plan.get("kind") != "verification-plan" or saved_plan.get("identity") != status["identity"]
        or saved_plan.get("task") != status["task"] or saved_plan.get("fingerprint") != status["fingerprint"]
        or saved_plan["fingerprint"] != _digest({k: v for k, v in saved_plan.items() if k not in {"task", "fingerprint"}})
        or not isinstance(saved_plan.get("lanes"), list)):
        raise VerificationError("Terminal status does not match its saved plan")
    lanes = status["lanes"]
    if any(not isinstance(lane, dict) or not {"id", "status", "exitCode", "elapsedSeconds", "pid", "logBytes", "timeoutSeconds"}.issubset(lane)
           or lane["status"] not in {"passed", "failed", "incomplete"} for lane in lanes):
        raise VerificationError("Malformed terminal lane result")
    planned_ids = [lane.get("id") for lane in saved_plan["lanes"] if isinstance(lane, dict)]
    if [lane["id"] for lane in lanes] != planned_ids[:len(lanes)]:
        raise VerificationError("Terminal lanes differ from the saved plan")
    if status["status"] == "passed" and (not lanes or len(lanes) != len(planned_ids)
        or any(lane["status"] != "passed" or lane["exitCode"] != 0 for lane in lanes)):
        raise VerificationError("Passing status lacks successful execution of every selected lane")
    if status["status"] == "failed" and not any(lane["status"] == "failed" for lane in lanes):
        raise VerificationError("Failed status lacks a failed lane")
    if (status["artifactHashes"] and status["artifactHashes"] != _artifact_hashes(directory)) or (status["status"] == "passed" and not status["artifactHashes"]):
        raise VerificationError("Terminal execution artifacts are missing or changed")


def read_status(root: Path, run_id: str) -> dict:
    root = root.resolve()
    directory = _run_dir(root, run_id)
    status = _read_json(_relative(directory, "status.json", artifact=True))
    _validate_status(directory, status)
    if status.get("reusedFrom"):
        previous_dir = _run_dir(root, status["reusedFrom"])
        previous = _read_json(_relative(previous_dir, "status.json", artifact=True))
        _validate_status(previous_dir, previous)
        if (previous.get("reusedFrom") or previous["status"] != "passed"
            or previous["fingerprint"] != status["fingerprint"] or previous["lanes"] != status["lanes"]):
            raise VerificationError("Invalid reused execution reference")
    return status


def _stop_group(process: subprocess.Popen) -> None:
    """Signal only a group created by this runner, including surviving descendants."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=0.4)
    except subprocess.TimeoutExpired:
        pass
    # The leader may already have exited while a descendant ignores SIGTERM.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=2)


class _Cancelled(BaseException):
    pass


def _junit(path: Path) -> dict:
    try:
        if path.stat().st_size > LOG_LIMIT:
            raise VerificationError("JUnit artifact exceeds the 16 MiB input limit")
        tree = ET.parse(path)
    except (OSError, ET.ParseError) as exc:
        raise VerificationError("Required JUnit artifact is missing or invalid") from exc
    root = tree.getroot()
    if root.tag not in {"testsuite", "testsuites"}:
        raise VerificationError("JUnit root must be testsuite or testsuites")
    cases = []
    case_states = {}
    parents = {child: parent for parent in root.iter() for child in parent}
    for case in tree.iter("testcase"):
        if parents[case].tag != "testsuite":
            raise VerificationError("JUnit test cases must be direct children of a testsuite")
        # A failure must not be hidden by a preceding skipped marker.
        finding = next((child for tag in ("error", "failure", "skipped") for child in case if child.tag == tag), None)
        case_states[case] = finding.tag if finding is not None else "passed"
        cases.append({"id": f"{case.get('classname', '')}::{case.get('name', '')}",
                      "status": case_states[case],
                      "reason": (finding.get("message") or finding.text or "")[:2000] if finding is not None else ""})
    covered_cases = set()
    for suite in root.iter():
        if suite.tag not in {"testsuite", "testsuites"}:
            continue
        allowed = {"testsuite", "properties", "system-out", "system-err"}
        if suite.tag == "testsuite":
            allowed.add("testcase")
        if any(child.tag not in allowed for child in suite):
            raise VerificationError("JUnit suite contains unsupported or misplaced result elements")
        descendants = list(suite.iter("testcase"))
        covered_cases.update(descendants)
        counts = {"tests": len(descendants), "failures": sum(case_states[case] == "failure" for case in descendants),
                  "errors": sum(case_states[case] == "error" for case in descendants),
                  "skipped": sum(case_states[case] == "skipped" for case in descendants)}
        # Validate each subtree's summary, never add nested aggregate summaries.
        for name, count in counts.items():
            declared = suite.get(name)
            if declared is not None and (not re.fullmatch(r"[0-9]+", declared) or int(declared) != count):
                raise VerificationError(f"JUnit aggregate {name} disagrees with detailed test cases")
    if covered_cases != set(case_states):
        raise VerificationError("JUnit test cases must belong to suites")
    return {"cases": cases, "counts": {state: sum(c["status"] == state for c in cases) for state in ("passed", "failure", "error", "skipped")}}


def _execute(root: Path, lane: dict, directory: Path, notify: Callable[[dict], None], heartbeat: float) -> dict:
    argv = [v.replace("{python}", sys.executable).replace("{artifact_dir}", str(directory)) for v in lane["argv"]]
    argv[0] = str(_executable(root, lane))
    result = {"id": lane["id"], "status": "running", "exitCode": None, "pid": None,
              "elapsedSeconds": 0, "logBytes": 0, "timeoutSeconds": lane["timeoutSeconds"]}
    started = time.monotonic()
    next_heartbeat = started
    process = None
    with selectors.DefaultSelector() as selector:
        streams = {}
        try:
            for name in ("stdout", "stderr"):
                descriptor = os.open(directory / f"{name}.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                streams[name] = os.fdopen(descriptor, "wb", buffering=0)
            process = subprocess.Popen(argv, cwd=_relative(root, lane.get("cwd", ".")), stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True)
            result["pid"] = process.pid
            for name in streams:
                pipe = getattr(process, name)
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, streams[name])
            cleaned = False
            while selector.get_map() or process.poll() is None:
                now = time.monotonic()
                result["elapsedSeconds"] = round(now - started, 3)
                if now >= next_heartbeat:
                    notify(result.copy())
                    next_heartbeat = now + heartbeat
                if now - started >= lane["timeoutSeconds"]:
                    result.update(status="incomplete", reason="timeout")
                    break
                for key, _ in selector.select(timeout=min(0.1, heartbeat)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    remaining = LOG_LIMIT - result["logBytes"]
                    key.data.write(chunk[:max(0, remaining)])
                    result["logBytes"] += min(len(chunk), max(0, remaining))
                    if len(chunk) > remaining:
                        result.update(status="incomplete", reason="output-limit")
                        break
                if result["status"] == "incomplete":
                    break
                if process.poll() is not None and not cleaned:
                    # A test must not leave background children holding its pipes open.
                    _stop_group(process)
                    cleaned = True
            if result["status"] == "running":
                remaining_time = max(0.01, lane["timeoutSeconds"] - (time.monotonic() - started))
                try:
                    process.wait(timeout=remaining_time)
                    result["status"] = "passed" if process.returncode == 0 else "failed"
                except subprocess.TimeoutExpired:
                    result.update(status="incomplete", reason="timeout")
        except (KeyboardInterrupt, _Cancelled):
            result.update(status="incomplete", reason="cancelled")
        except OSError as exc:
            result.update(status="incomplete", reason=f"execution-error: {exc.__class__.__name__}")
        finally:
            if process is not None:
                _stop_group(process)
                result["exitCode"] = process.returncode
                for pipe in (process.stdout, process.stderr):
                    pipe.close()
            for stream in streams.values():
                stream.close()
    result["elapsedSeconds"] = round(time.monotonic() - started, 3)
    if "junit" in lane:
        try:
            result["tests"] = _junit(_relative(directory, lane["junit"], artifact=True))
            if result["status"] == "passed" and (result["tests"]["counts"]["failure"] or result["tests"]["counts"]["error"]):
                result.update(status="failed", reason="JUnit reports failures despite zero exit code")
            if result["status"] == "passed" and not result["tests"]["counts"]["passed"]:
                result.update(status="incomplete", reason="JUnit contains no executed passing test cases (empty or all skipped)")
        except VerificationError as exc:
            if result["status"] == "passed":
                result.update(status="incomplete", reason=str(exc))
    notify(result.copy())
    return result


def _artifact_hashes(directory: Path) -> dict:
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise VerificationError("Symlink artifact cannot be reused")
        if path.is_file() and path.name != "status.json":
            result[path.relative_to(directory).as_posix()] = _file_hash(path)
    return result


def run_plan(root: Path, plan: dict, *, reuse: bool = False, heartbeat: float = 30,
             progress: Callable[[dict], None] | None = None) -> dict:
    if os.name != "posix":
        raise VerificationError("Owned-process-group execution currently requires POSIX (macOS/Linux)")
    if not 0 < heartbeat <= 30:
        raise VerificationError("Heartbeat must be greater than 0 and at most 30 seconds")
    root = root.resolve()
    plan = validate_plan(root, plan)
    previous = None
    if reuse and all(lane.get("hermetic", False) for lane in plan["lanes"]):
        artifact_root = _relative(root, ARTIFACT_ROOT, artifact=True)
        for path in sorted(artifact_root.glob("*/status.json"), reverse=True):
            try:
                candidate = read_status(root, path.parent.name)
                if (not candidate.get("reusedFrom") and candidate.get("status") == "passed" and candidate.get("fingerprint") == plan["fingerprint"]
                    and candidate.get("artifactHashes") == _artifact_hashes(path.parent)
                    and candidate.get("artifactHashes")):
                    saved_plan = _read_json(path.parent / "plan.json")
                    validate_plan(root, saved_plan)
                    if (saved_plan["fingerprint"] == plan["fingerprint"]
                        and candidate.get("resultHash") == _digest({k: v for k, v in candidate.items() if k != "resultHash"})):
                        previous = candidate
                        break
            except (VerificationError, OSError, KeyError):
                continue
    run_id = uuid.uuid4().hex
    directory = _run_dir(root, run_id, create=True)
    _atomic_json(directory / "plan.json", plan)
    report = {"schemaVersion": SCHEMA_VERSION, "kind": "verification-result", "runId": run_id,
              "task": plan["task"], "fingerprint": plan["fingerprint"], "identity": plan["identity"],
              "status": "running", "lanes": [], "startedAt": time.time(), "artifactPath": str(directory),
              "approval": "none; tc alone grants task approval"}

    def notify(current: dict) -> None:
        report["current"] = current
        report["heartbeatAt"] = time.time()
        _atomic_json(directory / "status.json", report)
        if progress:
            progress(dict(current, runId=run_id, artifactPath=str(directory)))

    _atomic_json(directory / "status.json", report)
    if previous:
        # Reference immutable execution artifacts, not another task's approval.
        report.update(status="passed", reusedFrom=previous["runId"], lanes=previous["lanes"])
    else:
        old_handler = signal.getsignal(signal.SIGTERM)

        def cancelled(_signum, _frame):
            raise _Cancelled()

        signal.signal(signal.SIGTERM, cancelled)
        try:
            for lane in plan["lanes"]:
                lane_dir = directory / lane["id"]
                lane_dir.mkdir(mode=0o700)
                current = _execute(root, lane, lane_dir, notify, heartbeat)
                report["lanes"].append(current)
                if current.get("reason") == "cancelled":
                    break
        except (KeyboardInterrupt, _Cancelled):
            report.update(status="incomplete", reason="cancelled")
        finally:
            signal.signal(signal.SIGTERM, old_handler)
        if report["status"] == "running":
            states = [lane["status"] for lane in report["lanes"]]
            report["status"] = "incomplete" if "incomplete" in states or len(states) != len(plan["lanes"]) else "failed" if "failed" in states else "passed"
        try:
            validate_plan(root, plan)
        except VerificationError:
            report.update(status="incomplete", reason="inputs changed during verification; create a new plan")
    report.pop("current", None)
    report["finishedAt"] = time.time()
    try:
        report["artifactHashes"] = _artifact_hashes(directory)
    except (VerificationError, OSError):
        report.update(status="incomplete", reason="unsafe or unreadable generated artifact", artifactHashes={})
    report["resultHash"] = _digest(report)
    _atomic_json(directory / "status.json", report)
    return report
