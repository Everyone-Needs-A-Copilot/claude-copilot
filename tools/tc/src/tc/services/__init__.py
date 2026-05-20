"""tc.services — domain logic layer for Task Copilot.

Functions here:
  - Accept plain Python args (not Typer Options).
  - Accept an optional ``conn`` parameter so callers can batch many ops in one
    transaction (pass None to open/close an own connection — preserves current
    per-call CLI semantics).
  - Return plain dicts / lists-of-dicts (same shape as --json CLI output).
  - NEVER print, NEVER sys.exit.
  - Raise typed exceptions from tc.db.exceptions instead of error_exit.

CLI command handlers in tc.commands.* are thin wrappers that call these
functions and translate typed exceptions to error_exit / output_json.
"""
