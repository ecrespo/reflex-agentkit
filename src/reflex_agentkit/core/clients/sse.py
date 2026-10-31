"""Incremental Server-Sent Events parser (API §8.2, REQ-021.2).

Only the ``data`` field matters: each dispatched frame's data lines are joined with
``\\n`` and returned. ``event``, ``id``, ``retry``, unknown fields and comments are
ignored. CRLF, LF and CR line endings are accepted, including a CRLF split across chunks,
and bytes are decoded incrementally so a UTF-8 character may span chunks. A frame without
its terminating blank line at EOF is discarded, as the SSE specification requires (a
lone CR at EOF counts as a complete line ending).
"""

from __future__ import annotations

import codecs

__all__ = ["SSEParser"]


class SSEParser:
    """Feed byte or str chunks; get back the ``data`` payload of each complete frame."""

    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buffer = ""
        self._data: list[str] = []
        self._started = False

    def feed(self, chunk: bytes | str) -> list[str]:
        """Consume ``chunk``; return the payloads of the frames it completes."""
        text = self._decoder.decode(chunk) if isinstance(chunk, bytes) else chunk
        if not self._started and text:
            self._started = True
            text = text.removeprefix("﻿")
        self._buffer += text
        frames: list[str] = []
        while True:
            line, ending = self._next_line()
            if ending is None:
                return frames
            if line == "":
                if self._data:
                    frames.append("\n".join(self._data))
                    self._data = []
                continue
            self._field(line)

    def finish(self) -> list[str]:
        """End of stream: return a frame a final lone CR completes, drop the rest, reset."""
        frames = self.feed("\n") if self._buffer.endswith("\r") else []
        self._reset()
        return frames

    def _next_line(self) -> tuple[str, str | None]:
        """Pop one terminated line from the buffer; ``(…, None)`` if none is complete."""
        buffer = self._buffer
        for index, char in enumerate(buffer):
            if char == "\n":
                self._buffer = buffer[index + 1 :]
                return buffer[:index], "\n"
            if char == "\r":
                if index + 1 == len(buffer):
                    return "", None  # may be the first half of CRLF; wait for more
                skip = 2 if buffer[index + 1] == "\n" else 1
                self._buffer = buffer[index + skip :]
                return buffer[:index], "\r"
        return "", None

    def _field(self, line: str) -> None:
        if line.startswith(":"):
            return
        name, _, value = line.partition(":")
        if name == "data":
            self._data.append(value.removeprefix(" "))
