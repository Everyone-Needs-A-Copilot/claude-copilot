"""Parse a confirmed done block (five labeled lines) into a schemaVersion 4 contract."""
from __future__ import annotations

import re

from tc.db.exceptions import ValidationError

_LABELS = {
    "done means": "done",
    "proven by": "proven",
    "not in scope": "excluded",
    "assumptions": "assumptions",
    "assumptions that would change the answer": "assumptions",
    "assumption": "assumptions",
    "first example": "example",
    "tier": "tier",
}
_LINE = re.compile(
    r"^(?:>\s*)*(?:\*\*)?\s*(" + "|".join(sorted((re.escape(k) for k in _LABELS), key=len, reverse=True)) + r")\s*(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.*)$",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(?:(?<=\s)|^)(?:\(\d+\)|\d+\.)\s+")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("**", "")).strip()


def _items(text: str) -> list[str]:
    """Numbered markers split first, else ';', else ','; numbering stripped, empties dropped."""
    if len(_NUMBER.findall(text)) >= 2:
        parts = _NUMBER.split(text)
    elif ";" in text:
        parts = text.split(";")
    else:
        parts = text.split(",")
    return [p for p in (_NUMBER.sub("", x, count=1).strip().rstrip(";").strip() for x in parts) if p]


def parse_done_block(text: str) -> dict:
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _LINE.match(line)
        if match:
            fields[_LABELS[match.group(1).lower()]] = _clean(match.group(2))
    if not fields.get("done"):
        raise ValidationError("Done block needs a 'Done means:' line")
    parsed = {"done": fields["done"]}
    if fields.get("proven"):
        parsed["provenBy"] = fields["proven"]
    if fields.get("excluded"):
        parsed["excluded"] = _items(fields["excluded"])
    if fields.get("assumptions"):
        parsed["assumptions"] = _items(fields["assumptions"])
    if fields.get("example"):
        parsed["firstExample"] = fields["example"]
    if fields.get("tier"):
        tier = fields["tier"].split()[0].upper().rstrip(".,;:")
        if tier not in ("T1", "T2", "T3"):
            raise ValidationError("Tier must be T1, T2 or T3")
        parsed["tier"] = tier
    return parsed


def build_contract(text: str, *, kind: str, sources, criteria, lane) -> dict:
    parsed = parse_done_block(text)
    parsed.pop("tier", None)  # recorded on the task by tc task contract, not part of the contract identity
    extra = []
    for item in criteria or []:
        cid, sep, expected = item.partition("=")
        if not sep:
            raise ValidationError("--criterion must look like ID=expected behavior")
        extra.append({"id": cid.strip(), "expected": expected.strip()})
    contract = {"schemaVersion": 4, "kind": kind, "criteria": [{"id": "DONE", "expected": parsed.pop("done")}, *extra]}
    if sources:
        contract["sources"] = list(sources)
    if lane:
        contract["lane"] = lane
    contract.update(parsed)
    contract["doneBlock"] = text.strip()
    return contract


def limits_registered(task_id: int, db_path) -> bool:
    import sqlite3
    from tc.db.connection import get_db

    conn = get_db(db_path)
    try:
        return conn.execute("SELECT 1 FROM execution_limits WHERE task_id=?", (task_id,)).fetchone() is not None
    except sqlite3.OperationalError:  # the table is created on first registration
        return False
    finally:
        conn.close()
