"""Run the REAL `cc.core.release.publish.publish` pipeline (build, flip, links, Codex marketplace, doctor, history)
for a test release whose content is the current release's content plus declared edits.

Only the two things that need the owner's signing keys are injected: the tag verifier (returns the commit the
current release already records) and the extractor (copies the component tree from the current release instead
of `git archive`).  Everything after that is the production code path.  Runs under the release's own cc venv.

usage: publish_driver.py BASELINE_RELEASE_DIR EDITS_JSON
EDITS_JSON: [{"file": "<component>/<path>", "op": "probe|append|replace", ...}]
"""
import json
import os
import shutil
import stat
import sys
import traceback
from pathlib import Path

from cc.core.release import publish as pub
from cc.core.release.engine import build, layout

baseline = Path(sys.argv[1])
edits = json.loads(Path(sys.argv[2]).read_text())
manifest = json.loads((baseline / "release.json").read_text())
comps = {c["name"]: c for c in manifest["components"]}
PROBE = ('[ -n "${CRACC_OBS:-}" ] && printf "ver=%s runtime=%s hook=%s\\n" "{ver}" "{runtime}" '
         '"$(basename "$0")" >> "$CRACC_OBS" 2>/dev/null\n')


def writable(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        os.chmod(dirpath, 0o755)
        for n in filenames:
            p = os.path.join(dirpath, n)
            if not os.path.islink(p):
                os.chmod(p, os.lstat(p).st_mode | 0o200)


def apply_edit(root: Path, e: dict) -> None:
    p = root / e["file"]
    t = p.read_text()
    if e["op"] == "probe":
        lines = t.splitlines(keepends=True)
        lines.insert(1 if lines and lines[0].startswith("#!") else 0, PROBE.replace("{ver}", e["ver"]).replace("{runtime}", e["runtime"]))
        t = "".join(lines)
    elif e["op"] == "prepend_body":  # first instruction after any YAML front matter
        if t.startswith("---"):
            end = t.index("\n---", 3) + 4
            t = t[:end] + "\n" + e["text"] + t[end:]
        else:
            t = e["text"] + t
    elif e["op"] == "append":
        t += e["text"]
    elif e["op"] == "replace":
        if e["old"] not in t:
            raise SystemExit(f"edit target text not found in {e['file']}")
        t = t.replace(e["old"], e["new"])
    p.write_text(t)


def verifier(src):
    c = comps[src.name]
    return build.VerifiedTag(commit=c["commit"], signer=c.get("signer", ""))


def extractor(src, tag, dest: Path):
    shutil.copytree(baseline / src.name, dest, symlinks=True)
    writable(dest)
    new_id = dest.parent.name
    for dirpath, _, filenames in os.walk(dest):  # venv shebangs / .pth name the release directory
        for n in filenames:
            p = Path(dirpath, n)
            if p.is_symlink() or p.stat().st_size > 1_000_000:
                continue
            try:
                t = p.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            if baseline.name in t:
                p.write_text(t.replace(baseline.name, new_id))
    for e in edits:
        if e["file"].split("/", 1)[0] == src.name:
            apply_edit(dest.parent, e)


sources = [build.ComponentSource(name=c["name"], tier=c["tier"], kind=c["kind"], version=c.get("version", ""),
                                 ref=c.get("ref", ""), source=c.get("source", ""), commit=c.get("commit", ""))
           for c in manifest["components"]]
try:
    report = pub.publish(sources, venv=False, verifier=verifier, extractor=extractor)
    print(json.dumps(report.to_json()))
except pub.PublishError as exc:
    print(json.dumps({"error": str(exc), "step": exc.step, "restored": exc.restored}))
    sys.exit(1)
except Exception:
    print(json.dumps({"error": traceback.format_exc()[-1500:], "step": "driver"}))
    sys.exit(1)
