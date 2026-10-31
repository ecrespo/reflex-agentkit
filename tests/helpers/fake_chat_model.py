"""A scripted LangChain chat model that streams text and tool calls, with no network."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.messages.tool import tool_call_chunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class ScriptedChatModel(BaseChatModel):
    """Answers each call with the next scripted ``AIMessage``.

    Streaming yields the text in two chunks and each tool call as a name chunk and an
    arguments chunk, as providers do, so
    ag-ui-langgraph emits ``TEXT_MESSAGE_*`` and ``TOOL_CALL_*`` events.
    """

    script: list[AIMessage]
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:
        return self

    def _next(self) -> AIMessage:
        message = self.script[self.calls % len(self.script)]
        self.calls += 1
        return message

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        message = self._next()
        text = str(message.content)
        half = len(text) // 2
        for part in (text[:half], text[half:]):
            if part:
                yield ChatGenerationChunk(message=AIMessageChunk(content=part, id=message.id))
        for index, call in enumerate(message.tool_calls):
            head = tool_call_chunk(name=call["name"], args="", id=call["id"], index=index)
            body = tool_call_chunk(name=None, args=json.dumps(call["args"]), id=None, index=index)
            for chunk in (head, body):
                yield ChatGenerationChunk(
                    message=AIMessageChunk(content="", id=message.id, tool_call_chunks=[chunk])
                )
