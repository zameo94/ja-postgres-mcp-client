from app.services.llm.sse import ServerSentEvent, SSEDecoder


def _decode(lines: list[str]) -> list[ServerSentEvent]:
    decoder = SSEDecoder()
    events: list[ServerSentEvent] = []
    for line in lines:
        event = decoder.feed(line)
        if event is not None:
            events.append(event)
    return events


def test_single_event_single_data_line() -> None:
    assert _decode(["data: hello", ""]) == [ServerSentEvent(data="hello")]


def test_multiple_data_lines_are_joined_with_newline() -> None:
    events = _decode(["data: line1", "data: line2", ""])

    assert events == [ServerSentEvent(data="line1\nline2")]


def test_json_split_across_data_lines() -> None:
    events = _decode(['data: {"a":', "data: 1}", ""])

    assert events == [ServerSentEvent(data='{"a":\n1}')]


def test_leading_space_after_colon_is_stripped_once() -> None:
    events = _decode(["data:  two spaces", ""])

    assert events == [ServerSentEvent(data=" two spaces")]


def test_event_and_id_fields_are_captured() -> None:
    events = _decode(["event: message", "id: 42", "data: x", ""])

    assert events == [ServerSentEvent(data="x", event="message", id="42")]


def test_comments_and_keep_alives_are_ignored() -> None:
    events = _decode([": keep-alive", "data: x", "", ": ping", ""])

    assert events == [ServerSentEvent(data="x")]


def test_consecutive_events() -> None:
    events = _decode(["data: a", "", "data: b", ""])

    assert events == [ServerSentEvent(data="a"), ServerSentEvent(data="b")]


def test_event_is_not_dispatched_until_terminated() -> None:
    decoder = SSEDecoder()

    assert decoder.feed("data: a") is None
    assert decoder.feed("data: b") is None
    assert decoder.feed("") == ServerSentEvent(data="a\nb")


def test_close_returns_none_on_clean_end() -> None:
    decoder = SSEDecoder()
    decoder.feed("data: a")
    decoder.feed("")

    assert decoder.close() is None


def test_close_returns_pending_event_on_truncated_stream() -> None:
    decoder = SSEDecoder()
    decoder.feed("data: partial")

    assert decoder.close() == ServerSentEvent(data="partial")
