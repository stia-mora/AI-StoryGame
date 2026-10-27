import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PlayerApp } from "../player/PlayerApp.jsx";
import { __resolveNextOrDefault } from "../components/login/nextTarget.js";

const story = { id: 7, title: "雾海来信", introduction: "一封来自远方的信", cover: "", identities: [{ id: "traveler", name: "旅人", description: "从港口出发" }] };
beforeEach(() => {
  history.replaceState({}, "", "/play");
  window.scrollTo = vi.fn();
  window.api = {
    player: {
      session: vi.fn().mockResolvedValue({ authenticated: false }),
      catalog: vi.fn().mockResolvedValue({ stories: [story] }),
      bootstrap: vi.fn(), save: vi.fn(),
    },
    auth: { logout: vi.fn() },
  };
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new Event("close")); };
});

it("lets guests search and read public introductions without requesting private data", async () => {
  render(<PlayerApp />);
  await screen.findByRole("heading", { name: "雾海来信" });
  expect(window.api.player.bootstrap).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: /积分/ })).toBeNull();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "没有" } });
  expect(screen.getByText("没有找到这个故事")).toBeTruthy();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "雾海" } });
  fireEvent.click(screen.getByRole("button", { name: /开始故事/ }));
  expect(await screen.findByRole("button", { name: "登录后创建角色" })).toBeTruthy();
  expect(screen.getByText("旅人")).toBeTruthy();
  expect(screen.queryByLabelText("你的名字")).toBeNull();
});

it("shows a login boundary for direct private save URLs", async () => {
  history.replaceState({}, "", "/play/saves/123");
  render(<PlayerApp />);
  expect(await screen.findByRole("button", { name: "登录后继续" })).toBeTruthy();
  expect(window.api.player.save).not.toHaveBeenCalled();
});

it("opens guidance again and keeps logout failures actionable", async () => {
  window.api.player.session.mockResolvedValue({ authenticated: true });
  window.api.player.bootstrap.mockResolvedValue({ user: { id: 2, name: "测试玩家" }, stories: [], saves: [], wallet: { free_micro: 0, permanent_micro: 0 } });
  window.api.auth.logout.mockRejectedValue(new Error("网络中断"));
  render(<PlayerApp />);
  await screen.findByRole("heading", { name: "故事大厅" });
  fireEvent.click(screen.getByRole("button", { name: "指引" }));
  expect(screen.getByRole("dialog").open).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "关闭" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "指引" }));
  expect(screen.getByRole("dialog").open).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "关闭" }));
  fireEvent.click(screen.getByLabelText("账户菜单"));
  fireEvent.click(screen.getByRole("button", { name: "退出登录 / 切换账号" }));
  await waitFor(() => expect(screen.getByText(/退出失败：网络中断/)).toBeTruthy());
  expect(screen.getByRole("button", { name: "退出登录 / 切换账号" }).disabled).toBe(false);
});

it.each(["/\\evil.example/login", "//evil.example", "\thttps://evil.example", "javascript:alert(1)", "/Login.html", "/%5cevil.example", "/admin"])("rejects unsafe player redirect %s", (target) => {
  history.replaceState({}, "", `/Login.html?next=${encodeURIComponent(target)}`);
  expect(__resolveNextOrDefault({ account_mode: "player", role: "user" })).toBe("/play");
  expect(__resolveNextOrDefault({ account_mode: "creator", role: "admin" })).toBe("/play");
});

it("preserves a validated save deep link and rejects duplicate redirect parameters", () => {
  history.replaceState({}, "", "/Login.html?next=%2Fplay%2Fsaves%2F42");
  expect(__resolveNextOrDefault({ account_mode: "player" })).toBe("/play/saves/42");
  history.replaceState({}, "", "/Login.html?next=/play&next=//evil.example");
  expect(__resolveNextOrDefault({ role: "admin" })).toBe("/play");
});

it.each(["/play/authoring?project=example", "/oauth/authoring/authorize?client_id=test&state=hello"])("returns creators to the authoring flow after login: %s", (target) => {
  history.replaceState({}, "", `/play/login?next=${encodeURIComponent(target)}`);
  expect(__resolveNextOrDefault({ account_mode: "creator" })).toBe(target);
  expect(__resolveNextOrDefault({ account_mode: "player" })).toBe("/play");
});

it.each([{ account_mode: "player" }, { account_mode: "creator" }, { role: "admin" }])("defaults every account to the player lobby", (user) => {
  history.replaceState({}, "", "/play/login");
  expect(__resolveNextOrDefault(user)).toBe("/play");
});

it("returns to the personal archive after login", () => {
  history.replaceState({}, "", "/play/login?next=%2Fplay%2Fsaves");
  expect(__resolveNextOrDefault({ account_mode: "player" })).toBe("/play/saves");
});

it.each(["/settings-models", "/admin-security", "/device?user_code=ABCD", "/me", "/scripts-library"])("preserves the existing creator route %s", (target) => {
  history.replaceState({}, "", `/Login.html?next=${encodeURIComponent(target)}`);
  expect(__resolveNextOrDefault({ account_mode: "creator" })).toBe(target);
});
