from app.api.sse import format_sse


def test_format_sse_encodes_event_and_json_payload() -> None:
    assert format_sse("token", {"text": "hi"}) == 'event: token\ndata: {"text": "hi"}\n\n'


def test_format_sse_keeps_the_payload_on_a_single_data_line() -> None:
    encoded = format_sse("token", {"text": "a\nb"})

    assert encoded.count("data:") == 1
    assert encoded.endswith("\n\n")
    assert "a\\nb" in encoded


def test_format_sse_serializes_non_string_values() -> None:
    encoded = format_sse("tool_result", {"is_error": True, "id": "c1"})

    assert encoded.startswith("event: tool_result\ndata: {")
    assert '"is_error": true' in encoded
