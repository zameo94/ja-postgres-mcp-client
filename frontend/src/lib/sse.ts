export interface ParsedSseEvent {
  event: string;
  data: string;
}

/**
 * Parse a buffer of Server-Sent Events, returning the events completed so far
 * and the trailing incomplete part to prepend to the next chunk.
 *
 * Follows the event-stream framing: events are separated by a blank line and
 * multiple `data:` lines of the same event are joined with a newline. Comment
 * lines (`:`) are ignored. `LF`, `CRLF` and lone `CR` are all accepted.
 */
export function parseSseChunk(buffer: string): { events: ParsedSseEvent[]; rest: string } {
  const blocks = buffer.split(/\r\n\r\n|\n\n|\r\r/);
  const rest = blocks.pop() ?? "";
  const events: ParsedSseEvent[] = [];

  for (const block of blocks) {
    let event = "message";
    const dataLines: string[] = [];

    for (const line of block.split(/\r\n|\n|\r/)) {
      if (line.startsWith(":")) continue;
      const separator = line.indexOf(":");
      const field = separator === -1 ? line : line.slice(0, separator);
      let value = separator === -1 ? "" : line.slice(separator + 1);
      if (value.startsWith(" ")) value = value.slice(1);

      if (field === "event") event = value;
      else if (field === "data") dataLines.push(value);
    }

    if (dataLines.length > 0) {
      events.push({ event, data: dataLines.join("\n") });
    }
  }

  return { events, rest };
}
