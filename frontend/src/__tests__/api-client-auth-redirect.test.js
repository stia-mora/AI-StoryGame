import { afterEach, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const source = readFileSync(resolve(__dirname, "../api-client.js"), "utf8");
afterEach(() => vi.unstubAllGlobals());

function expiredClient(pathname) {
  const destination = {
    protocol: "http:", hostname: "localhost", port: "5173",
    pathname, search: "?sort=recent", hash: "#latest", replace: vi.fn(),
  };
  new Function("location", source)(destination);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: false, status: 401, statusText: "Unauthorized",
    headers: new Headers({ "Content-Type": "application/json" }),
    json: async () => ({ error: "登录已失效" }),
    text: async () => JSON.stringify({ error: "登录已失效" }),
  }));
  return destination;
}

it.each(["/play/login", "/play/register/", "/Login.html"])("keeps authentication errors on %s without a redirect loop", async (path) => {
  const destination = expiredClient(path);
  await expect(window.api.auth.me()).rejects.toThrow("登录已失效");
  await expect(window.api.auth.login({})).rejects.toThrow("登录已失效");
  expect(destination.replace).not.toHaveBeenCalled();
});

it.each(["/play/saves/42", "/play/saves", "/Player.html", "/"])("sends expired player sessions from %s to the new login once", async (path) => {
  const destination = expiredClient(path);
  await expect(window.api.auth.me()).rejects.toThrow();
  await expect(window.api.auth.me()).rejects.toThrow();
  expect(destination.replace).toHaveBeenCalledExactlyOnceWith(`/play/login?next=${encodeURIComponent(path + "?sort=recent#latest")}`);
});

it("keeps explicit creator authentication destinations usable", async () => {
  const destination = expiredClient("/settings");
  await expect(window.api.auth.me()).rejects.toThrow();
  expect(destination.replace).toHaveBeenCalledExactlyOnceWith(`/Login.html?next=${encodeURIComponent("/settings?sort=recent#latest")}`);
});
