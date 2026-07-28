"""
Per-request project attribution for logs and alerts.

The hub is shared by several trading projects (ARES, Aeolus, gamma-blaster,
Kronos, stock-screener). When something fails we need to know which caller
triggered it, so every request carries a project name that is stored in a
context variable and injected into every log record emitted while handling
that request.
"""
import logging
import os
from contextvars import ContextVar

# Header clients use to identify themselves to the hub.
PROJECT_HEADER = "X-Project-Name"

# Used when no caller identified itself, e.g. the hub's own background tasks.
DEFAULT_PROJECT = "hub-internal"

_project_ctx: ContextVar[str] = ContextVar("project_name", default=DEFAULT_PROJECT)


def set_project(name: str | None) -> None:
    """Sets the project attributed to the current context (request/task)."""
    _project_ctx.set(name.strip() if name and name.strip() else DEFAULT_PROJECT)


def get_project() -> str:
    """Returns the project attributed to the current context."""
    return _project_ctx.get()


def default_client_project() -> str:
    """
    Project name a client library reports when the caller did not pass one.
    Reads PROJECT_NAME from the environment so deployments can set it once.
    """
    return os.getenv("PROJECT_NAME", "unknown-project")


class ProjectLogFilter(logging.Filter):
    """Injects the current project into every log record as `%(project)s`."""

    def filter(self, record: logging.LogRecord) -> bool:
        # getattr guard: records built before the contextvar was set (or by
        # third-party libraries) must still format cleanly.
        if not hasattr(record, "project"):
            record.project = get_project()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """
    Configures root logging with the project field in the format string and
    attaches the project filter to every handler.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] [project=%(project)s] %(name)s: %(message)s",
    )
    project_filter = ProjectLogFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(project_filter)
