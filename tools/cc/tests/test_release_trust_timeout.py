"""F4 deadline and protocol controls; private child fixtures remain as evidence."""
import os
from pathlib import Path
import sys
import tempfile
import time

import pytest

from cc.core.release.codex import trust_gate


@pytest.mark.parametrize("partial", [False, True], ids=["silent", "partial-line"])
def test_app_server_read_deadline_reaps_child(partial, monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="cc-trust-timeout-"))
    stub = root / "codex"
    stub.write_text("#!" + sys.executable + "\nimport sys,time\n" +
                    ("sys.stdout.write('{'); sys.stdout.flush()\n" if partial else "") +
                    "time.sleep(1)\n")
    stub.chmod(0o700)
    children = []
    popen = trust_gate.subprocess.Popen
    def capture(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(trust_gate.subprocess, "Popen", capture)
    started = time.monotonic()
    with pytest.raises(trust_gate.TrustGateError, match="did not answer"):
        trust_gate.app_server_hooks(str(stub), root, root, wait=0, timeout=0.15)
    elapsed = time.monotonic() - started
    assert elapsed < 0.7, f"requested 0.15s deadline took {elapsed:.3f}s"
    assert children[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(children[0].pid, 0)


def test_app_server_responsive_protocol_preserves_hooks():
    root = Path(tempfile.mkdtemp(prefix="cc-trust-responsive-"))
    stub = root / "codex"
    stub.write_text("#!" + sys.executable + "\n" +
        "import json,sys\nfor line in sys.stdin:\n"
        " m=json.loads(line)\n"
        " if m.get('id') == 1: print(json.dumps({'id':1,'result':{}}),flush=True)\n"
        " if m.get('id') == 2: print(json.dumps({'id':2,'result':{'data':[{'hooks':[{'key':'fixture'}]}]}}),flush=True)\n")
    stub.chmod(0o700)
    assert trust_gate.app_server_hooks(str(stub), root, root, wait=0, timeout=2) == [{"key": "fixture"}]
