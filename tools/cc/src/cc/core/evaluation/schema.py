"""Draft 2020-12 validation and canonical fixture identities."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from importlib import resources
from typing import Any, Mapping

_SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"
_CASE_ID = re.compile(r"^eval-[0-9]{2}$")
_NAMESPACE = re.compile(r"^SYNTHETIC-[A-Z0-9][A-Z0-9_-]{2,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_MEDIA_TYPE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,63}/[a-z0-9][a-z0-9.+-]{0,63}$")
_FIXTURE_FIELDS = frozenset(
    {
        "schema_version",
        "case_id",
        "revision",
        "fixture_namespace",
        "problem_statement",
        "evidence_files",
        "layer_variants",
        "runtimes",
        "required_criteria",
        "hard_rejection_rules",
        "journey_requirements",
        "private_oracle",
    }
)
_EVIDENCE_FIELDS = frozenset(
    {"path", "sha256", "media_type", "synthetic_fixture", "fixture_namespace"}
)
_ORACLE_FIELDS = frozenset({"path", "sha256"})
_LAYER_VARIANTS = frozenset({"F", "F+O", "F+O+D", "F+O+D+P"})
_RUNTIMES = frozenset({"claude", "codex"})


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
    if not isinstance(value, dict) or value.get("$schema") != _SCHEMA_URI:
        raise ValueError("Evaluation schema is not Draft 2020-12.")
    return value


def validate_document(value: object, *, schema_name: str = "fixture") -> None:
    # Load the packaged Draft 2020-12 contract before applying its deliberately
    # small, stdlib-only compiled validator. This keeps production installs
    # self-contained without weakening the public schema artifact.
    load_schema(schema_name)
    issues = _fixture_issues(value)
    if not issues:
        return
    raise SchemaViolation(schema_name, tuple(issues))


def _fixture_issues(value: object) -> list[SchemaIssue]:
    issues: list[SchemaIssue] = []
    if not isinstance(value, dict):
        return [SchemaIssue("/", "type")]
    _closed_object(value, _FIXTURE_FIELDS, "/", issues)
    if set(value) != _FIXTURE_FIELDS:
        return issues

    _string(value["schema_version"], "/schema_version", issues, const="1.0")
    _string(value["case_id"], "/case_id", issues, pattern=_CASE_ID)
    revision = value["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int):
        issues.append(SchemaIssue("/revision", "type"))
    elif revision < 1:
        issues.append(SchemaIssue("/revision", "minimum"))
    _string(
        value["fixture_namespace"],
        "/fixture_namespace",
        issues,
        pattern=_NAMESPACE,
    )
    _string(
        value["problem_statement"],
        "/problem_statement",
        issues,
        minimum=1,
        maximum=8192,
    )
    _enum_list(value["layer_variants"], "/layer_variants", issues, _LAYER_VARIANTS)
    _enum_list(value["runtimes"], "/runtimes", issues, _RUNTIMES)
    for field in (
        "required_criteria",
        "hard_rejection_rules",
        "journey_requirements",
    ):
        _identifier_list(value[field], f"/{field}", issues)
    _evidence_list(value["evidence_files"], issues)
    _oracle(value["private_oracle"], issues)
    return issues


def _closed_object(
    value: dict[object, object],
    expected: frozenset[str],
    location: str,
    issues: list[SchemaIssue],
) -> None:
    keys = set(value)
    if any(not isinstance(item, str) for item in keys):
        issues.append(SchemaIssue(location, "propertyNames"))
    if keys - expected:
        issues.append(SchemaIssue(location, "additionalProperties"))
    if expected - keys:
        issues.append(SchemaIssue(location, "required"))


def _string(
    value: object,
    location: str,
    issues: list[SchemaIssue],
    *,
    const: str | None = None,
    pattern: re.Pattern[str] | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> None:
    if not isinstance(value, str):
        issues.append(SchemaIssue(location, "type"))
        return
    if const is not None and value != const:
        issues.append(SchemaIssue(location, "const"))
    if pattern is not None and not pattern.fullmatch(value):
        issues.append(SchemaIssue(location, "pattern"))
    if minimum is not None and len(value) < minimum:
        issues.append(SchemaIssue(location, "minLength"))
    if maximum is not None and len(value) > maximum:
        issues.append(SchemaIssue(location, "maxLength"))


def _array(
    value: object, location: str, issues: list[SchemaIssue]
) -> list[object] | None:
    if not isinstance(value, list):
        issues.append(SchemaIssue(location, "type"))
        return None
    if not value:
        issues.append(SchemaIssue(location, "minItems"))
    markers: list[str] = []
    for index, item in enumerate(value):
        try:
            marker = f"{type(item).__name__}:{json.dumps(item, sort_keys=True, allow_nan=False)}"
        except (TypeError, ValueError):
            marker = f"unsupported:{index}"
        markers.append(marker)
    if len(markers) != len(set(markers)):
        issues.append(SchemaIssue(location, "uniqueItems"))
    return value


def _enum_list(
    value: object,
    location: str,
    issues: list[SchemaIssue],
    choices: frozenset[str],
) -> None:
    items = _array(value, location, issues)
    if items is None:
        return
    for index, item in enumerate(items):
        if not isinstance(item, str) or item not in choices:
            issues.append(SchemaIssue(f"{location}/{index}", "enum"))


def _identifier_list(value: object, location: str, issues: list[SchemaIssue]) -> None:
    items = _array(value, location, issues)
    if items is None:
        return
    for index, item in enumerate(items):
        _string(item, f"{location}/{index}", issues, pattern=_IDENTIFIER)


def _evidence_list(value: object, issues: list[SchemaIssue]) -> None:
    items = _array(value, "/evidence_files", issues)
    if items is None:
        return
    if len(items) > 64:
        issues.append(SchemaIssue("/evidence_files", "maxItems"))
    for index, item in enumerate(items):
        location = f"/evidence_files/{index}"
        if not isinstance(item, dict):
            issues.append(SchemaIssue(location, "type"))
            continue
        _closed_object(item, _EVIDENCE_FIELDS, location, issues)
        if set(item) != _EVIDENCE_FIELDS:
            continue
        _path(item["path"], f"{location}/path", issues)
        _string(item["sha256"], f"{location}/sha256", issues, pattern=_SHA256)
        _string(
            item["media_type"], f"{location}/media_type", issues, pattern=_MEDIA_TYPE
        )
        if item["synthetic_fixture"] is not True:
            issues.append(SchemaIssue(f"{location}/synthetic_fixture", "const"))
        _string(
            item["fixture_namespace"],
            f"{location}/fixture_namespace",
            issues,
            pattern=_NAMESPACE,
        )


def _oracle(value: object, issues: list[SchemaIssue]) -> None:
    location = "/private_oracle"
    if not isinstance(value, dict):
        issues.append(SchemaIssue(location, "type"))
        return
    _closed_object(value, _ORACLE_FIELDS, location, issues)
    if set(value) != _ORACLE_FIELDS:
        return
    _path(value["path"], f"{location}/path", issues)
    _string(value["sha256"], f"{location}/sha256", issues, pattern=_SHA256)


def _path(value: object, location: str, issues: list[SchemaIssue]) -> None:
    if not isinstance(value, str):
        issues.append(SchemaIssue(location, "type"))
        return
    if not 1 <= len(value) <= 512:
        issues.append(SchemaIssue(location, "length"))
    if (
        value.startswith("/")
        or "\\" in value
        or "//" in value
        or any(part in {".", "..", ""} for part in value.split("/"))
        or any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)
    ):
        issues.append(SchemaIssue(location, "pattern"))


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
