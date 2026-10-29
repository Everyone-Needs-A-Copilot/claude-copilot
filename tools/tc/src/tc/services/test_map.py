"""Change-to-test map: which focused/affected command covers which source paths.

The map is a project file (``.copilot/test-map.json``, next to ``tasks.db``).
Nothing here executes a command; selection only reports what the map says.
Unmatched paths select the broad lane, never an empty selection.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path, PurePosixPath

from tc.db.exceptions import ValidationError

LANES = ("focused", "affected", "broad")
LANE_CAPS = {"focused": 60, "affected": 180, "broad": 900}
RELEASE_KEY = "release"
MAP_NAME = "test-map.json"


def map_path(db_path) -> Path:
    return Path(db_path).parent / MAP_NAME


def _command(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{what} must be a non-empty command string")
    return value.strip()


def _validate_entry(glob: str, entry) -> dict:
    allowed = {"focused", "affected", "lane", "cap_seconds"}
    if not isinstance(entry, dict) or set(entry) - allowed or "focused" not in entry:
        raise ValidationError(f"Map entry '{glob}' must be an object with focused (required), affected, lane, cap_seconds")
    clean = {"focused": _command(entry["focused"], f"'{glob}' focused")}
    clean["affected"] = _command(entry["affected"], f"'{glob}' affected") if entry.get("affected") is not None else clean["focused"]
    if entry.get("lane") is not None:
        if entry["lane"] not in LANES:
            raise ValidationError(f"'{glob}' lane must be one of: {', '.join(LANES)}")
        clean["lane"] = entry["lane"]
    cap = entry.get("cap_seconds")
    if cap is not None:
        if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
            raise ValidationError(f"'{glob}' cap_seconds must be an integer > 0")
        clean["cap_seconds"] = cap
    return clean


def _validate_glob(glob: str) -> None:
    if not isinstance(glob, str) or not glob.strip() or glob == RELEASE_KEY or glob.startswith("/") or ".." in PurePosixPath(glob).parts or "\\" in glob:
        raise ValidationError("Glob must be a non-empty project-relative pattern (not 'release')")


def load_map(db_path) -> dict:
    path = map_path(db_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise ValidationError(f"{path} is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"{path} must be a JSON object")
    for glob, entry in data.items():
        if glob == RELEASE_KEY:
            if not isinstance(entry, dict) or set(entry) != {"broad"}:
                raise ValidationError("'release' entry must be {broad: <command>}")
            _command(entry["broad"], "release broad")
        else:
            _validate_glob(glob)
            _validate_entry(glob, entry)
    return data


def _save(db_path, data: dict) -> None:
    path = map_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def set_entry(db_path, glob, focused, affected=None, lane=None, cap_seconds=None) -> dict:
    _validate_glob(glob)
    entry = _validate_entry(glob, {"focused": focused, "affected": affected, "lane": lane, "cap_seconds": cap_seconds})
    data = load_map(db_path)
    data[glob] = entry
    _save(db_path, data)
    return entry


def set_release(db_path, broad) -> dict:
    data = load_map(db_path)
    data[RELEASE_KEY] = {"broad": _command(broad, "release broad")}
    _save(db_path, data)
    return data[RELEASE_KEY]


def remove_entry(db_path, glob) -> None:
    data = load_map(db_path)
    if glob not in data:
        raise ValidationError(f"No map entry for '{glob}'")
    del data[glob]
    _save(db_path, data)


def _regex(glob: str):
    anchored = "/" in glob.rstrip("/")
    pattern, i = "", 0
    glob = glob.lstrip("/")
    while i < len(glob):
        c = glob[i]
        if glob.startswith("**/", i):
            pattern += "(?:.*/)?"
            i += 3
        elif glob.startswith("/**", i) and i + 3 == len(glob):
            pattern += "(?:/.*)?"
            i += 3
        elif glob.startswith("**", i):
            pattern += ".*"
            i += 2
        elif c == "*":
            pattern += "[^/]*"
            i += 1
        elif c == "?":
            pattern += "[^/]"
            i += 1
        else:
            pattern += re.escape(c)
            i += 1
    return re.compile(("" if anchored else "(?:.*/)?") + pattern + "/?")


def _specificity(glob: str) -> tuple:
    first = min([i for i, c in enumerate(glob) if c in "*?"] or [len(glob)])
    return (first, len(re.sub(r"[*?]", "", glob)), -glob.count("*"))


def _best(path: str, globs):
    hits = [g for g in globs if _regex(g).fullmatch(path)]
    return max(hits, key=_specificity) if hits else None


def select(db_path, paths) -> dict:
    paths = [p.strip()[2:] if p.strip().startswith("./") else p.strip() for p in paths if p and p.strip()]
    if not paths:
        raise ValidationError("Give at least one changed path (or --diff)")
    data = load_map(db_path)
    globs = [g for g in data if g != RELEASE_KEY]
    matches, unmatched, entries = [], [], {}
    for path in paths:
        glob = _best(path, globs)
        if glob is None:
            unmatched.append(path)
        else:
            matches.append({"path": path, "glob": glob})
            entries[glob] = data[glob]
    lane_rank = {n: i for i, n in enumerate(LANES)}
    lane = max([e.get("lane", "affected") for e in entries.values()] + (["broad"] if unmatched else []), key=lane_rank.get)
    caps = [e.get("cap_seconds", LANE_CAPS[e.get("lane", "affected")]) for e in entries.values()]
    if unmatched:
        caps.append(LANE_CAPS["broad"])
    focused, affected = [], []
    for e in entries.values():
        if e["focused"] not in focused:
            focused.append(e["focused"])
        if e["affected"] not in affected:
            affected.append(e["affected"])
    result = {
        "paths": paths,
        "matches": matches,
        "unmatched": unmatched,
        "focused": focused,
        "affected": affected,
        "lane": lane,
        "cap_seconds": max(caps),
        "note": None,
    }
    if unmatched:
        result["note"] = "No map entry for: " + ", ".join(unmatched) + "; selecting the broad lane (never an empty selection)"
        broad = data.get(RELEASE_KEY, {}).get("broad")
        if broad:
            result["broad"] = broad
    return result


def changed_paths(root, base=None) -> list[str]:
    def git(*args):
        proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            raise ValidationError("git failed: " + (proc.stderr.strip() or f"exit {proc.returncode}"))
        return [line for line in proc.stdout.splitlines() if line]
    try:
        names = git("diff", "--name-only", base or "HEAD")
    except ValidationError:
        if base:
            raise
        names = git("diff", "--name-only")
    if not base:
        names += git("ls-files", "--others", "--exclude-standard")
    return [n for n in dict.fromkeys(names) if not n.startswith(".copilot/")]  # runtime state, not source


def derive_lane(db_path, sources) -> tuple[dict | None, str | None]:
    """Lane for a contract's sources, or (None, reason) when the map cannot supply one."""
    if not map_path(db_path).exists() or not sources:
        return None, None
    result = select(db_path, sources)
    focused = result["focused"] or ([result["broad"]] if result.get("broad") else [])
    affected = result["affected"] or focused
    if not focused:
        return None, result["note"]
    return {"focused": " && ".join(focused), "affected": " && ".join(affected), "cap_seconds": result["cap_seconds"], "lane": result["lane"]}, result["note"]
