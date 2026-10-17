"""Worker ownership propagated through nested graph/tool execution."""
from contextvars import ContextVar

current_job = ContextVar("arena_current_job", default=None)
