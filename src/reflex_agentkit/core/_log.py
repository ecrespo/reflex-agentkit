"""Library logging (TD §7.1, REQ-027).

Every logger lives under ``reflex_agentkit``. Run-scoped records go through
:class:`RunLogger`, which puts ``thread_id`` and ``run_id`` both in the message prefix
and as record attributes (REQ-027.1). Message contents, tool args and results are only
ever logged at DEBUG (REQ-027.2).
"""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

__all__ = ["LOGGER_NAME", "RunLogger", "get_logger"]

LOGGER_NAME = "reflex_agentkit"


def get_logger(name: str) -> logging.Logger:
    """The child logger ``reflex_agentkit.<name>``."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


class RunLogger(logging.LoggerAdapter[logging.Logger]):
    """Adds the run context to every record."""

    def __init__(self, logger: logging.Logger, *, thread_id: str, run_id: str) -> None:
        super().__init__(logger, {"thread_id": thread_id, "run_id": run_id})

    def with_run(self, run_id: str) -> RunLogger:
        """The same logger for a follow-up run of the thread."""
        return RunLogger(self.logger, thread_id=self.thread_id, run_id=run_id)

    @property
    def thread_id(self) -> str:
        return str((self.extra or {})["thread_id"])

    @property
    def run_id(self) -> str:
        return str((self.extra or {})["run_id"])

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        kwargs["extra"] = {**(self.extra or {}), **kwargs.get("extra", {})}
        return f"[thread={self.thread_id} run={self.run_id}] {msg}", kwargs
