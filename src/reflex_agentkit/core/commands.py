"""Pure command functions: state transitions that are not AG-UI events (API §11).

Each takes a ``ConversationState`` and returns a new one. They generate IDs (UUID4 by
default, DM R-7) but take ``new_id`` so a sequence of commands can be reproduced.

T-010 brings in the basic ``begin_run`` (user message, run/thread IDs, the turn's run
IDs, status and error). T-015 adds the interrupt bookkeeping and the other commands.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.models import ChatMessage, MessageRole, ReducerConfig, RunStatus

__all__ = ["begin_run"]


def _uuid4() -> str:
    return str(uuid.uuid4())


def begin_run(
    conv: ConversationState,
    *,
    config: ReducerConfig,
    user_text: str | None = None,
    resume: bool = False,
    new_id: Callable[[], str] = _uuid4,
) -> ConversationState:
    """Start a run (REQ-001.1-3, REQ-002.1-2, REQ-010.2).

    With ``user_text`` the human's turn is appended and a new turn of run IDs starts.
    Without it (a resume or a client-tool follow-up) the run joins the current turn, so
    late events of the turn's earlier runs are still recognized.

    Args:
        conv: The current conversation.
        config: The reducer settings for this run, built from the ``AgentState`` ClassVars.
        user_text: The validated text the user sent, if this run starts a new turn.
        resume: Whether this run answers interrupts (bookkeeping completed in T-015).
        new_id: ID factory; UUID4 strings by default.
    """
    thread_id = conv.thread_id or new_id()
    run_id = new_id()
    messages = conv.messages
    if user_text is not None:
        user_message = ChatMessage(id=new_id(), role=MessageRole.USER, content=user_text)
        messages = (*messages, user_message)
        last_run_ids: tuple[str, ...] = (run_id,)
    else:
        last_run_ids = (*conv.last_run_ids, run_id)
    return conv.with_(
        config=config,
        thread_id=thread_id,
        run_id=run_id,
        run_status=RunStatus.RUNNING,
        error="",
        error_code=None,
        messages=messages,
        last_run_ids=last_run_ids,
    )
