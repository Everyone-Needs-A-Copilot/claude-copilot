"""Project initialisation: the one writer of thin project state."""

from cc.core.project_init.init import InitError, init_project
from cc.core.project_init.marker import MARKER_FILENAME, RUNTIMES, write_marker
from cc.core.project_init.sections import SECTION, SECTION_BEGIN, SECTION_END

__all__ = [
    "InitError", "init_project", "MARKER_FILENAME", "RUNTIMES", "write_marker",
    "SECTION", "SECTION_BEGIN", "SECTION_END",
]
