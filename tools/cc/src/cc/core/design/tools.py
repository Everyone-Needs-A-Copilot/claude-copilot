"""Explicit, hash-pinned local detector execution. No models or implicit installs."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import selectors
import signal
import subprocess
import time
import urllib.request
from importlib.resources import files
from pathlib import Path

from cc.core.config_paths import machine_config_path
from cc.core.entry_store import _atomic_write
from cc.core.locking import copilot_lock
from .contracts import create_file, local_path, now, read_bytes, read_json, source_records, text

MAX_TOOL_BYTES = 100 * 1024 * 1024
EXTENSIONS = {".html", ".htm", ".css", ".scss", ".sass", ".less", ".jsx", ".tsx", ".js", ".ts", ".vue", ".svelte", ".astro"}


def registry_path() -> Path:
    # Machine-owned registry, never an executable path selected by project JSON.
    return machine_config_path().parent / "design-tools.json"


def run_bounded(argv: list[str], root: Path, *, timeout: int = 20, max_output: int = 1024 * 1024) -> dict:
    if os.name != "posix":
        raise ValueError("Bounded design tool execution currently requires a POSIX host")
    if not 1 <= timeout <= 60:
        raise ValueError("Tool timeout must be 1–60 seconds")
    started = time.monotonic()
    proc = subprocess.Popen(argv, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)
    output = {"stdout": bytearray(), "stderr": bytearray()}
    reason = None
    try:
        with selectors.DefaultSelector() as selector:
            for name in output:
                stream = getattr(proc, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                if time.monotonic() - started > timeout:
                    reason = "timeout"
                    break
                for key, _ in selector.select(0.05):
                    chunk = os.read(key.fileobj.fileno(), 16384)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output[key.data].extend(chunk)
                if sum(map(len, output.values())) > max_output:
                    reason = "output limit"
                    break
            if not reason:
                try:
                    proc.wait(timeout=max(0.1, timeout - (time.monotonic() - started)))
                except subprocess.TimeoutExpired:
                    reason = "timeout"
            if reason:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
    except BaseException:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        raise
    finally:
        for name in output:
            getattr(proc, name).close()
    return {"exit_code": proc.returncode, "failure": reason,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            **{name: bytes(value[:max_output]).decode("utf-8", errors="replace") for name, value in output.items()}}


def tool_status() -> dict:
    path = registry_path()
    if not path.exists():
        return {"available": False, "reason": "No machine-pinned detector; run cc design tool install or register"}
    record = read_json(path)
    binary = Path(text(record.get("binary"), "binary"))
    expected = record.get("sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Invalid detector digest in machine registry")
    if not binary.is_absolute() or binary.is_symlink() or not os.access(binary, os.X_OK):
        raise ValueError("Pinned detector is unavailable or is a symlink")
    actual = hashlib.sha256(read_bytes(binary, MAX_TOOL_BYTES)).hexdigest()
    if actual != expected:
        raise ValueError("Detector content changed; explicit verified re-registration required")
    return {"available": True, **record}


def register_tool(binary: Path, sha256: str, version: str, source: str, *, replace: bool = False) -> dict:
    if binary.is_symlink():
        raise ValueError("Register the real binary, not a symlink or downloading launcher")
    binary = binary.absolute()
    if not re.fullmatch(r"[0-9a-f]{64}", sha256) or hashlib.sha256(read_bytes(binary, MAX_TOOL_BYTES)).hexdigest() != sha256:
        raise ValueError("Detector SHA256 does not match the verified input")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Exact engine version required")
    text(source, "source provenance")
    if not os.access(binary, os.X_OK):
        raise ValueError("Detector is not executable")
    probe = run_bounded([str(binary), "engine-probe"], binary.parent, timeout=3, max_output=4096)
    if probe["exit_code"] != 0 or probe["stdout"].strip() != f"impeccable-engine {version}":
        raise ValueError("Executable did not identify as the selected Impeccable engine")
    if hashlib.sha256(read_bytes(binary, MAX_TOOL_BYTES)).hexdigest() != sha256:
        raise ValueError("Detector changed during registration")
    target = registry_path()
    record = {"schema_version": "1.0", "binary": str(binary), "sha256": sha256, "version": version, "source": source}
    with copilot_lock(path=target.with_suffix(".lock")):
        if target.exists():
            before = read_json(target)
            if before == record:
                return {"changed": False, **record}
            if not replace:
                raise ValueError("A different detector is registered; inspect it before using --replace")
            backup = target.with_name(f"design-tools.{hashlib.sha256(read_bytes(target)).hexdigest()[:16]}.backup.json")
            if not backup.exists():
                create_file(target.parent, backup.name, json.dumps(before, indent=2) + "\n")
        _atomic_write(target, json.dumps(record, indent=2) + "\n")
    return {"changed": True, **record}


def install_tool(*, replace: bool = False) -> dict:
    manifest = json.loads(files("cc.core.design").joinpath("references", "impeccable.json").read_text())
    machine = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(platform.machine().lower())
    key = f"{platform.system().lower()}-{machine}"
    asset = manifest["assets"].get(key)
    if asset is None:
        raise ValueError(f"No reviewed detector asset for {key}; register a verified local engine explicitly")
    folder = registry_path().parent / "tools" / "impeccable" / manifest["version"]
    destination = folder / asset["name"]
    if not destination.exists():
        url = asset["url"]
        if not url.startswith("https://github.com/pbakaus/impeccable/releases/download/"):
            raise ValueError("Unrecognized packaged release origin")
        with urllib.request.urlopen(url, timeout=30) as response:
            body = response.read(MAX_TOOL_BYTES + 1)
        if len(body) > MAX_TOOL_BYTES or hashlib.sha256(body).hexdigest() != asset["sha256"]:
            raise ValueError("Downloaded detector differs from the packaged release digest")
        from cc.core.write_guard import assert_write_is_isolated
        assert_write_is_isolated(destination)
        folder.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents replacement of an existing executable.
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o700)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(body)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    return register_tool(destination, asset["sha256"], manifest["version"], asset["url"], replace=replace)


def audit(root: Path, targets: list[str], *, timeout: int = 20, review_sha256: str | None = None) -> dict:
    if not targets or len(targets) > 40 or len(set(targets)) != len(targets):
        raise ValueError("Select 1–40 distinct local source files")
    paths = [local_path(root, name) for name in targets]
    before = source_records(root, targets)
    tool = tool_status()
    base = {"schema_version": "1.0", "kind": "design-audit", "created_at": now(), "project": str(root.resolve()),
            "sources": before, "review_sha256": review_sha256, "tool": tool,
            "policy": "Raw local static scan including linked local stylesheets; remote CSS, JavaScript execution, project/inline suppressions and DESIGN.md loading disabled. Every finding requires contextual review; this process is not an OS sandbox.",
            "qa_approved": False}
    try:
        source_records(root, targets, strict_links=True)
    except (ValueError, OSError) as exc:
        return {**base, "status": "unavailable", "reason": f"Linked stylesheet coverage unavailable: {exc}", "findings": []}
    if any(path.suffix.lower() not in EXTENSIONS for path in paths):
        return {**base, "status": "unavailable", "reason": "Target language is not supported by this web detector; record native inspection as scan_alternative", "findings": []}
    if not tool["available"]:
        return {**base, "status": "unavailable", "findings": []}
    argv = [tool["binary"], "detect", "--json", "--no-config", *map(str, paths)]
    result = run_bounded(argv, root, timeout=timeout)
    after = source_records(root, targets)
    stable = before == after and tool_status()["sha256"] == tool["sha256"]
    base.update({"command": argv, "run": result, "identity_stable": stable})
    if result["failure"] or result["exit_code"] not in (0, 2) or not stable:
        return {**base, "status": "failed", "findings": []}
    try:
        raw = json.loads(result["stdout"])
        if not isinstance(raw, list) or len(raw) > 5000 or any(not isinstance(f, dict) for f in raw):
            raise ValueError("Invalid detector finding list")
        findings = []
        for item in raw:
            encoded = json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False)
            findings.append({"id": hashlib.sha256(encoded.encode()).hexdigest(),
                             **{key: str(item.get(key, "")) for key in ("antipattern", "name", "description", "severity", "category", "file", "line", "snippet")}})
    except (ValueError, TypeError):
        return {**base, "status": "invalid-output", "findings": []}
    status = "incomplete" if "could not read linked stylesheet" in result["stderr"] else "completed"
    return {**base, "status": status, "findings": findings}
