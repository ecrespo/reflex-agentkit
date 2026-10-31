"""Incremental SSE parser (T-020, API §8.2, REQ-021.2)."""

from __future__ import annotations

import pytest

from reflex_agentkit.core.clients.sse import SSEParser


def _parse(*chunks: bytes | str) -> list[str]:
    parser = SSEParser()
    out: list[str] = []
    for chunk in chunks:
        out.extend(parser.feed(chunk))
    out.extend(parser.finish())
    return out


def test_REQ_021_2_single_frame() -> None:
    assert _parse(b'data: {"a": 1}\n\n') == ['{"a": 1}']


def test_REQ_021_2_several_frames_in_one_chunk() -> None:
    assert _parse(b"data: 1\n\ndata: 2\n\n") == ["1", "2"]


def test_REQ_021_2_multi_line_data_is_joined_with_newlines() -> None:
    assert _parse(b"data: {\ndata: }\n\n") == ["{\n}"]


def test_REQ_021_2_event_id_retry_and_unknown_fields_are_ignored() -> None:
    assert _parse(b"event: msg\nid: 7\nretry: 10\nfoo: bar\ndata: x\n\n") == ["x"]


def test_REQ_021_2_comments_are_ignored() -> None:
    assert _parse(b": keep-alive\n\n: another\ndata: x\n\n") == ["x"]


@pytest.mark.parametrize("newline", [b"\r\n", b"\r", b"\n"], ids=["crlf", "cr", "lf"])
def test_REQ_021_2_all_line_endings(newline: bytes) -> None:
    assert _parse(b"data: a" + newline + b"data: b" + newline + newline) == ["a\nb"]


def test_REQ_021_2_frame_split_across_chunks() -> None:
    assert _parse(b"da", b"ta: hel", b"lo\n", b"\n") == ["hello"]


def test_REQ_021_2_crlf_split_across_chunks_is_one_line_ending() -> None:
    assert _parse(b"data: a\r", b"\n\r", b"\n") == ["a"]


def test_REQ_021_2_multibyte_utf8_split_across_chunks() -> None:
    encoded = "data: ñandú\n\n".encode()
    assert _parse(encoded[:8], encoded[8:]) == ["ñandú"]


def test_REQ_021_2_str_chunks_are_accepted() -> None:
    assert _parse("data: x\n", "\n") == ["x"]


def test_REQ_021_2_only_one_leading_space_is_stripped() -> None:
    assert _parse(b"data:  x\ndata:y\n\n") == [" x\ny"]


def test_REQ_021_2_field_without_colon_and_empty_data() -> None:
    assert _parse(b"data\n\n") == [""]
    assert _parse(b"event: x\n\n") == []


def test_REQ_021_2_trailing_frame_without_blank_line_is_discarded() -> None:
    assert _parse(b"data: 1\n\ndata: 2\n") == ["1"]
    assert _parse(b"data: 1\n\ndata: 2") == ["1"]


def test_REQ_021_2_leading_bom_is_ignored() -> None:
    assert _parse("﻿data: x\n\n".encode()) == ["x"]


def test_REQ_021_2_parser_is_reusable_after_finish() -> None:
    parser = SSEParser()
    parser.feed(b"data: partial")
    assert parser.finish() == []
    assert parser.feed(b"data: new\n\n") == ["new"]
