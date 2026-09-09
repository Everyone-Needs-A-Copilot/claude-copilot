"""Read-only Codex runtime discovery; presence never implies enforcement."""
import json
from pathlib import Path
import select
import shutil
import subprocess
import time


def codex_status(project: Path, binary: str = "codex") -> dict:
    executable = shutil.which(binary)
    if not executable:
        return {"status": "unavailable", "runtime_enforcement": "unverified", "reason": "Codex executable missing"}
    version = subprocess.check_output([executable, "--version"], text=True, timeout=5).strip()
    process = subprocess.Popen([executable, "app-server", "--stdio"], cwd=project,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True)

    def call(rid, method, params):
        process.stdin.write(json.dumps({"id": rid, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if not select.select([process.stdout], [], [], 1)[0]:
                continue
            line = process.stdout.readline()
            if not line:
                raise RuntimeError("Codex app-server closed")
            row = json.loads(line)
            if row.get("id") == rid:
                if "error" in row:
                    raise RuntimeError("Codex runtime introspection rejected")
                return row["result"]
        raise TimeoutError("Codex runtime introspection timed out")

    try:
        call(1, "initialize", {"clientInfo": {"name": "cc-enforcement-status", "version": "1"},
                               "capabilities": {"experimentalApi": True}})
        config = call(2, "config/read", {"cwd": str(project.resolve()), "includeLayers": True})
        discovered = call(3, "hooks/list", {"cwds": [str(project.resolve())]})
        hooks = [h for row in discovered["data"] for h in row["hooks"]]
        layers = [{"source": layer.get("name"), "reason": layer["disabledReason"]}
                  for layer in config.get("layers", []) if layer.get("disabledReason")]
        return {"schema_version": 1, "project": str(project.resolve()), "binary": executable,
                "version": version, "status": "discovered" if hooks else "not-discovered",
                "runtime_enforcement": "unverified", "disabled_layers": layers,
                "hooks": [{k: h.get(k) for k in ("key", "eventName", "enabled", "trustStatus", "sourcePath", "currentHash")}
                          for h in hooks],
                "warnings": [w for row in discovered["data"] for w in row.get("warnings", [])],
                "errors": [e for row in discovered["data"] for e in row.get("errors", [])]}
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
