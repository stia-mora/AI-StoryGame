import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const source = readFileSync(resolve(__dirname, "../api-client.js"), "utf8");
const encoder = new TextEncoder();

beforeEach(() => new Function(source).call(window));
afterEach(() => vi.unstubAllGlobals());

function streamResponse(chunks) {
  let index = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: async () =>
            index < chunks.length
              ? { value: encoder.encode(chunks[index++]), done: false }
              : { done: true },
        }),
      },
    }),
  );
}

it("ignores heartbeat comments and decodes CRLF frames split across network chunks", async () => {
  streamResponse([
    ": keepalive\r\n\r",
    '\nevent: token\r\ndata: {"text":"已到学院"}\r\n\r',
    "\nevent: done\r\ndata: {}\r\n\r\n",
  ]);
  const handlers = {
    onEvent: vi.fn(),
    on_token: vi.fn(),
    on_done: vi.fn(),
    onError: vi.fn(),
    onClose: vi.fn(),
  };
  await window.api.player.execute({}, handlers).done;
  expect(handlers.on_token).toHaveBeenCalledWith({ text: "已到学院" });
  expect(handlers.onEvent).toHaveBeenCalledTimes(2);
  expect(handlers.on_done).toHaveBeenCalledTimes(1);
  expect(handlers.onError).not.toHaveBeenCalled();
  expect(handlers.onClose).toHaveBeenCalledTimes(1);
});

it("reports a clean EOF without done as incomplete rather than successful completion", async () => {
  streamResponse(['event: token\ndata: {"text":"部分正文"}\n\n']);
  const handlers = { on_token: vi.fn(), onError: vi.fn(), onClose: vi.fn() };
  await window.api.game.chat({}, handlers).done;
  expect(handlers.on_token).toHaveBeenCalledWith({ text: "部分正文" });
  expect(handlers.onError.mock.calls[0][0].code).toBe("stream_incomplete");
  expect(handlers.onClose).toHaveBeenCalledTimes(1);
});

it("reports a broken read while retaining the previously streamed text", async () => {
  let reads = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: async () => {
            if (reads++) throw new TypeError("connection reset");
            return {
              value: encoder.encode(
                'event: token\ndata: {"text":"部分正文"}\n\n',
              ),
              done: false,
            };
          },
        }),
      },
    }),
  );
  const handlers = { on_token: vi.fn(), onError: vi.fn() };
  await window.api.player.execute({}, handlers).done;
  expect(handlers.on_token).toHaveBeenCalledWith({ text: "部分正文" });
  expect(handlers.onError.mock.calls[0][0].code).toBe("stream_read");
});
