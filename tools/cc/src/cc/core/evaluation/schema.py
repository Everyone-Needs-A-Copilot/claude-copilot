"""Draft 2020-12 validation and canonical fixture identities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from typing import Any, Mapping

from jsonschema import Draft202012Validator


@dataclass(frozen=True)
class SchemaIssue:
    location: str
    rule: str


class SchemaViolation(ValueError):
    def __init__(self, schema_name: str, issues: tuple[SchemaIssue, ...]) -> None:
        self.schema_name = schema_name
        self.issues = issues
        summary = ", ".join(f"{item.location}:{item.rule}" for item in issues[:8])
        super().__init__(f"{schema_name} schema validation failed ({summary})")


def load_schema(schema_name: str) -> Mapping[str, Any]:
    if schema_name != "fixture":
        raise ValueError("Unknown evaluation schema.")
    schema_file = resources.files("cc.core.evaluation").joinpath(
        "schemas", f"{schema_name}.schema.json"
    )
    value = json.loads(schema_file.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def validate_document(value: object, *, schema_name: str = "fixture") -> None:
    validator = Draft202012Validator(load_schema(schema_name))
    errors = sorted(
        validator.iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if not errors:
        return
    issues = tuple(
        SchemaIssue(
            location="/" + "/".join(str(item) for item in error.absolute_path),
            rule=error.validator or "schema",
        )
        for error in errors
    )
    raise SchemaViolation(schema_name, issues)


def canonical_json_bytes(value: object) -> bytes:
    _validate_canonical_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _validate_canonical_value(value: object) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        raise TypeError("Floating-point values are not canonical evaluation inputs.")
    if isinstance(value, list):
        for item in value:
            _validate_canonical_value(item)
        return
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Canonical evaluation object keys must be strings.")
        for item in value.values():
            _validate_canonical_value(item)
        return
    raise TypeError("Unsupported canonical evaluation value.")
