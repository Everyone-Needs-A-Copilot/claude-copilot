"""Task Copilot CLI - Agent-agnostic task management."""

__version__ = "1.0.0"

# Default paths
DEFAULT_DB_DIR = ".copilot"
DEFAULT_DB_NAME = "tasks.db"
DEFAULT_DB_PATH = f"{DEFAULT_DB_DIR}/{DEFAULT_DB_NAME}"

# Threshold for hybrid WP storage: content at or below this size is stored
# inline in the DB (fast, no file I/O); content exceeding this is written to an
# external .md file (file_path set, content NULL in DB) to keep the DB lean and
# avoid bloating Claude's context window with large agent outputs.
#
# Rationale: observed WP sizes in this codebase range from ~300 B (one-liners)
# to ~20 KB (large analysis outputs).  8 KB covers the typical short-to-medium
# range inline while offloading the genuinely large outputs that would otherwise
# consume meaningful context budget.  Adjustable via WP_CONTENT_SIZE_THRESHOLD
# override in test fixtures.
WP_CONTENT_SIZE_THRESHOLD = 8 * 1024  # 8 KB
WP_FILE_DIR = ".copilot/wp"
