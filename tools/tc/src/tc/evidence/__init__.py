"""tc.evidence — pure QA evidence packet parsing, schema and validation.

This package owns exactly what a SINGLE evidence packet must contain to be
well-formed. It knows nothing about tasks, work products, the database, or
which work product is "current" for a task -- that DB traversal, staleness
policy and legacy-evidence migration live in ``tc.services.qa``, which is
the actual completion authority. See wp-a-evidence.md section 5 for the
module boundary this split implements.

Re-exported here: ``EVIDENCE_SCHEMA_VERSION``, ``parse_packet``,
``validate_packet``.
"""

from __future__ import annotations

from .artifact_types import ARTIFACT_TYPES, is_sufficient_alone, is_valid_artifact_type
from .parse import is_legacy_shaped, parse_packet
from .schema import (
    EVIDENCE_SCHEMA_VERSION,
    KNOWN_FIELDS,
    REQUIRED_FIELDS,
    VALID_VERDICTS,
    render_packet,
    to_json_envelope,
)
from .validate import validate_packet

__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "KNOWN_FIELDS",
    "REQUIRED_FIELDS",
    "VALID_VERDICTS",
    "ARTIFACT_TYPES",
    "is_valid_artifact_type",
    "is_sufficient_alone",
    "parse_packet",
    "is_legacy_shaped",
    "validate_packet",
    "render_packet",
    "to_json_envelope",
]
