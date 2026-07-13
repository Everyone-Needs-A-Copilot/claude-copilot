"""Typed exceptions for tc service layer.

These are raised by tc.services.* functions instead of calling error_exit
or sys.exit.  CLI command handlers catch these and translate to the
appropriate exit codes and stderr messages.

This module has ZERO import-time side effects — no DB opened, no env read.
"""

from __future__ import annotations


class TcError(Exception):
    """Base class for all tc service exceptions."""


class TaskNotFound(TcError):
    """Raised when a task ID does not exist in the database."""


class PrdNotFound(TcError):
    """Raised when a PRD ID does not exist in the database."""


class WorkProductNotFound(TcError):
    """Raised when a work product ID does not exist in the database."""


class SolutionNotFound(TcError):
    """Raised when a solution ID does not exist in the database."""


class ValidationError(TcError):
    """Raised when input data fails validation (bad priority, invalid status, etc.)."""


class ConflictError(TcError):
    """Raised when an operation conflicts with current state (e.g. already claimed,
    duplicate dependency)."""


class DatabaseError(TcError):
    """Raised for unexpected SQLite errors that are not covered by the above."""
