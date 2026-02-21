"""Task Copilot CLI - Agent-agnostic task management."""

__version__ = "1.0.0"

# Default paths
DEFAULT_DB_DIR = ".copilot"
DEFAULT_DB_NAME = "tasks.db"
DEFAULT_DB_PATH = f"{DEFAULT_DB_DIR}/{DEFAULT_DB_NAME}"

# Large content threshold for hybrid storage
WP_CONTENT_SIZE_THRESHOLD = 100 * 1024  # 100KB
WP_FILE_DIR = ".copilot/wp"
