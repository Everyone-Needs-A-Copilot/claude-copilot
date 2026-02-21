"""Utilities package for Task Copilot CLI."""

from .errors import (
    EXIT_SUCCESS,
    EXIT_ERROR,
    EXIT_NOT_FOUND,
    EXIT_CONFLICT,
    EXIT_VALIDATION,
    EXIT_DB_ERROR,
    error_exit,
    require_db,
)

__all__ = [
    "EXIT_SUCCESS",
    "EXIT_ERROR",
    "EXIT_NOT_FOUND",
    "EXIT_CONFLICT",
    "EXIT_VALIDATION",
    "EXIT_DB_ERROR",
    "error_exit",
    "require_db",
]
