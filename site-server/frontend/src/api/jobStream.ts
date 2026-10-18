import { accessToken } from "./client";

/**
 * Server-sent events for one job, over `fetch` rather than `EventSource`.
 *
 * `EventSource` cannot send headers, so using it would mean putting the JWT in
 * the query string — where it lands in nginx access logs, browser history and
 * any `Referer` the page sends onward. A token in a log file is a token
 * somebody can use. `fetch` carries it in the header like every other request.
 *
 * The caller gets a `close()` and must call it. Returns `null` when streaming
 * is not available at all — no ReadableStream, or the server refused because
 * its per-process stream budget is full — and the caller falls back to polling.
 */

export type JobStreamHandlers = {
  onProgress: (payload: unknown) => void;
  onDone: (payload: unknown) => void;
  /** The job parked for a human; nothing more will arrive on this stream. */
  onWaiting: (payload: unknown) => void;
  onGone: () => void;
  /** Stream ended for a reason that is not the job finishing. */
  onDrop: () => void;
};

export type JobStream = { close: () => void };

/** Split an SSE buffer into complete `event:`/`data:` frames. */
function parseFrames(buffer: string): { frames: string[]; rest: string } {
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  return { frames: parts, rest };
}

function readFrame(frame: string): { event: string; data: string } | null {
  let event = "message";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) continue; // heartbeat comment
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }
  if (data.length === 0) return null;
  return { event, data: data.join("\n") };
}

export async function openJobStream(
  jobId: number,
  handlers: JobStreamHandlers,
): Promise<JobStream | null> {
  if (typeof window === "undefined" || !("ReadableStream" in window)) return null;

  const controller = new AbortController();
  let response: Response;
  try {
    response = await fetch(`/api/v1/jobs/${jobId}/stream/`, {
      headers: {
        Accept: "text/event-stream",
        ...(accessToken() ? { Authorization: `Bearer ${accessToken()}` } : {}),
      },
      signal: controller.signal,
    });
  } catch {
    return null;
  }

  // 503 is the server saying its stream budget is full. Not an error worth
  // showing anyone — the poller does the same job a little slower.
  if (!response.ok || !response.body) return null;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let closed = false;

  const close = () => {
    closed = true;
    controller.abort();
    reader.cancel().catch(() => {});
  };

  (async () => {
    let buffer = "";
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done || closed) break;
        buffer += decoder.decode(value, { stream: true });
        const { frames, rest } = parseFrames(buffer);
        buffer = rest;

        for (const raw of frames) {
          const frame = readFrame(raw);
          if (!frame) continue;
          let payload: unknown = null;
          try {
            payload = JSON.parse(frame.data);
          } catch {
            continue;
          }
          if (closed) return;
          switch (frame.event) {
            case "progress":
              handlers.onProgress(payload);
              break;
            case "done":
              handlers.onDone(payload);
              close();
              return;
            case "waiting":
              handlers.onWaiting(payload);
              close();
              return;
            case "gone":
              handlers.onGone();
              close();
              return;
            // "reconnect" and "error" both mean this connection is over but the
            // job may not be. Falling back to the poller is simpler than
            // re-opening, and it is what the caller does on a drop.
            default:
              break;
          }
        }
      }
    } catch {
      // An aborted read during close() is the normal path, not a failure.
    }
    if (!closed) handlers.onDrop();
  })();

  return { close };
}
