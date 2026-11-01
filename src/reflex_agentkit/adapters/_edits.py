"""The edited-arguments notice both adapters give the model (REQ-035, DD-013).

When the user approves a tool call with edited arguments, the model only sees a result
that does not match what it asked for, and may "correct" the user by calling the tool
again. The notice tells it the edit was deliberate.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pydantic_core

__all__ = ["EDITED_ARGS_NOTICE", "with_edited_args_notice"]

EDITED_ARGS_NOTICE = (
    "Note: the user edited this tool call's arguments before approving it, so the tool "
    "ran with: {args}. These are the arguments the user wants: do not call the tool "
    "again to restore the earlier ones, and do not report the change as an error."
)
"""Normative text (REQ-035); tests pin it, so a change here is a spec change."""


def with_edited_args_notice(result: Any, args: Mapping[str, Any]) -> str:
    """``result`` followed by a blank line and the notice naming ``args``.

    A non-string result is serialized to JSON first, as PydanticAI does for tool returns.
    """
    text = (
        result if isinstance(result, str) else pydantic_core.to_json(result, fallback=str).decode()
    )
    shown = json.dumps(dict(args), ensure_ascii=False, default=str)
    return f"{text}\n\n{EDITED_ARGS_NOTICE.format(args=shown)}"
