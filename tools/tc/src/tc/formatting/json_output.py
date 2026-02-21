"""JSON output helpers for Task Copilot CLI."""

import json
import sys
from typing import Any, Union


def _default_serializer(obj: Any) -> Any:
    """Handle types not natively serializable by json module."""
    # sqlite3.Row objects
    if hasattr(obj, "keys"):
        return dict(obj)
    # Fallback to string
    return str(obj)


def output_json(data: Union[dict, list]) -> None:
    """Print compact JSON to stdout.

    Args:
        data: Dictionary or list to serialize.
    """
    print(json.dumps(data, default=_default_serializer, ensure_ascii=False))


def output_error_json(message: str, code: int) -> None:
    """Print error JSON to stderr.

    Args:
        message: Human-readable error message.
        code: Exit code integer.
    """
    error = {"error": message, "code": code}
    print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
