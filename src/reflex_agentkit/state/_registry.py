"""``RunRegistry``: the process-local map of running drivers (TD §5.2, Flow D, DD-004).

``cancel_run`` looks the run up here first. A hit means the driver lives in this worker
and can be cancelled immediately; a miss means it runs in another worker (or has
finished), and the driver will see ``_cancel_requested`` at its next flush instead.
Entries hold only the asyncio task: nothing here is serialized or sent anywhere.
"""

from __future__ import annotations

import asyncio

__all__ = ["REGISTRY", "RunRegistry"]


class RunRegistry:
    """``(client token, run id) -> driver task`` for the runs of this process."""

    def __init__(self) -> None:
        self._tasks: dict[tuple[str, str], asyncio.Task[object]] = {}

    def __len__(self) -> int:
        return len(self._tasks)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(runs={len(self._tasks)})"

    def register(self, token: str, run_id: str, task: asyncio.Task[object]) -> None:
        """Record the driver task of ``run_id`` for the session ``token``."""
        self._tasks[(token, run_id)] = task

    def unregister(self, token: str, run_id: str) -> None:
        """Forget the run. Idempotent."""
        self._tasks.pop((token, run_id), None)

    def cancel(self, token: str, run_id: str) -> bool:
        """Cancel the run's task if it lives here and is still running."""
        task = self._tasks.get((token, run_id))
        if task is None or task.done():
            return False
        task.cancel()
        return True


REGISTRY = RunRegistry()
"""The registry shared by every ``AgentState`` of this process."""
