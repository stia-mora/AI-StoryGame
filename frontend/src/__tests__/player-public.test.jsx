import { beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PlayerApp } from "../player/PlayerApp.jsx";
import { __resolveNextOrDefault } from "../components/login/nextTarget.js";

const story = { id: 7, title: "雾海来信", introduction: "一封来自远方的信", cover: "", identities: [{ id: "traveler", name: "旅人", description: "从港口出发" }] };
beforeEach(() => {
  localStorage.clear();
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

it("closes the account menu on outside interaction and navigation", async () => {
  window.api.player.session.mockResolvedValue({ authenticated: true });
  window.api.player.bootstrap.mockResolvedValue({ user: { id: 2, name: "测试玩家" }, stories: [], saves: [], wallet: { free_micro: 0, permanent_micro: 0 } });
  render(<PlayerApp />);
  const trigger = await screen.findByLabelText("账户菜单");
  const menu = trigger.closest("details");
  menu.open = true;
  fireEvent.pointerDown(screen.getByRole("heading", { name: "故事大厅" }));
  expect(menu.open).toBe(false);
  menu.open = true;
  fireEvent.focusIn(screen.getByRole("button", { name: "指引" }));
  expect(menu.open).toBe(false);
  menu.open = true;
  fireEvent.click(screen.getByRole("button", { name: "我的存档" }));
  expect(menu.open).toBe(false);
});

it("reads an explicitly published opening as a guest without creating or charging a save", async () => {
  window.api.player.catalog.mockResolvedValue({ stories: [{ ...story, opening_preview: "雨落在港口。旅人拆开了那封信。" }] });
  window.api.player.create = vi.fn();
  window.api.player.quote = vi.fn();
  window.api.player.execute = vi.fn();
  render(<PlayerApp />);
  fireEvent.click(await screen.findByRole("button", { name: /开场试读/ }));
  expect(await screen.findByRole("heading", { name: "开场试读" })).toBeTruthy();
  expect(screen.getByText("雨落在港口。旅人拆开了那封信。")).toBeTruthy();
  expect(window.api.player.bootstrap).not.toHaveBeenCalled();
  expect(window.api.player.create).not.toHaveBeenCalled();
  expect(window.api.player.quote).not.toHaveBeenCalled();
  expect(window.api.player.execute).not.toHaveBeenCalled();
});

it("updates the header from redemption even while the ledger refresh is stalled", async () => {
  window.api.player.session.mockResolvedValue({ authenticated: true });
  window.api.player.bootstrap.mockResolvedValue({ user: { id: 2, name: "测试玩家" }, stories: [], saves: [], wallet: { free_micro: 0, permanent_micro: 1000000 } });
  window.api.player.wallet = vi.fn().mockResolvedValue({ free_micro: 0, permanent_micro: 1000000, held_micro: 0, rates: { input: 1, output: 2 } });
  window.api.player.ledger = vi.fn().mockReturnValue(new Promise(() => {}));
  window.api.player.redeem = vi.fn().mockResolvedValue({ free_micro: 0, permanent_micro: 6000000, held_micro: 0, rates: { input: 1, output: 2 } });
  history.replaceState({}, "", "/play/wallet");
  render(<PlayerApp />);
  await screen.findByText("1.00 积分");
  fireEvent.change(await screen.findByLabelText("兑换码"), { target: { value: "TEST" } });
  fireEvent.click(screen.getByRole("button", { name: "兑换" }));
  await screen.findByText("兑换成功，积分已加入长期余额。");
  expect(screen.getByText("6.00 积分")).toBeTruthy();
});

it("does not overwrite redeemed points with an older turn balance response", async () => {
  let finishOldBalance;
  const initialWallet = { free_micro: 0, permanent_micro: 1000000, held_micro: 0, rates: { input: 1, output: 2 } };
  window.api.player.session.mockResolvedValue({ authenticated: true });
  window.api.player.bootstrap.mockResolvedValue({ user: { id: 2 }, stories: [], saves: [], wallet: initialWallet });
  window.api.player.save.mockResolvedValue({ save: { id: 9, turn: 1, story_title: "测试世界" }, status: { name: "旅人" }, messages: [], options: [], has_opening: true });
  window.api.player.request = vi.fn().mockResolvedValue({ status: "released" });
  window.api.player.wallet = vi.fn().mockResolvedValue(initialWallet).mockImplementationOnce(() => new Promise((resolve) => { finishOldBalance = resolve; }));
  window.api.player.ledger = vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, pages: 1 });
  window.api.player.redeem = vi.fn().mockResolvedValue({ ...initialWallet, permanent_micro: 6000000 });
  localStorage.setItem("player-request-2-9", JSON.stringify({ request_id: "previous-turn" }));
  history.replaceState({}, "", "/play/saves/9");
  render(<PlayerApp />);
  await waitFor(() => expect(window.api.player.wallet).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "1.00 积分" }));
  fireEvent.change(await screen.findByLabelText("兑换码"), { target: { value: "TEST" } });
  fireEvent.click(screen.getByRole("button", { name: "兑换" }));
  await screen.findByText("6.00 积分");
  await act(async () => finishOldBalance(initialWallet));
  expect(screen.getByText("6.00 积分")).toBeTruthy();
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
