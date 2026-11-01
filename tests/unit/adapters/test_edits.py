"""The edited-arguments notice shared by both adapters (REQ-035, DD-016)."""

from __future__ import annotations

from reflex_agentkit.adapters._edits import EDITED_ARGS_NOTICE, with_edited_args_notice


def test_REQ_035_1_notice_text_is_pinned() -> None:
    """REQ-035: the normative notice; changing it changes what every model reads."""
    assert EDITED_ARGS_NOTICE == (
        "Note: the user edited this tool call's arguments before approving it, so the tool "
        "ran with: {args}. These are the arguments the user wants: do not call the tool "
        "again to restore the earlier ones, and do not report the change as an error."
    )


def test_REQ_035_1_string_results_get_the_notice_after_a_blank_line() -> None:
    text = with_edited_args_notice("Booked 3 nights in Porto.", {"nights": 3, "city": "Porto"})
    assert text == (
        "Booked 3 nights in Porto.\n\nNote: the user edited this tool call's arguments "
        'before approving it, so the tool ran with: {"nights": 3, "city": "Porto"}. '
        "These are the arguments the user wants: do not call the tool again to restore the "
        "earlier ones, and do not report the change as an error."
    )


def test_REQ_035_1_other_results_are_serialized_as_json_first() -> None:
    """Non-string results are serialized the way PydanticAI serializes tool returns."""
    text = with_edited_args_notice({"booked": True, "city": "Porto"}, {"city": "Porto"})
    assert text.startswith('{"booked":true,"city":"Porto"}\n\nNote: ')


def test_REQ_035_1_non_json_values_fall_back_to_str() -> None:
    class Ticket:
        def __str__(self) -> str:
            return "ticket-7"

    text = with_edited_args_notice(Ticket(), {"when": Ticket()})
    assert text.startswith('"ticket-7"\n\nNote: ')
    assert 'the tool ran with: {"when": "ticket-7"}. ' in text


def test_REQ_035_1_unicode_stays_readable() -> None:
    assert '{"city": "Málaga"}' in with_edited_args_notice("ok", {"city": "Málaga"})
