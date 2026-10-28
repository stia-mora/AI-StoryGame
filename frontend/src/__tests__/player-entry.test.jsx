import React from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PlayerApp } from "../player/PlayerApp.jsx";

const story = { id: 538, title: "怪奇物语：万圣夜，别松手", introduction: "1984 年，Hawkins 的万圣节。", cover: "", identities: [{ id: "friend", name: "同龄伙伴" }] };
const account = {
  user: { id: 1, name: "玩家" }, wallet: { free_micro: 1000000, permanent_micro: 0 }, stories: [story],
  saves: [
    { id: 9, story_id: 538, story_title: story.title, name: "Alex", turn: 3 },
    { id: 10, story_id: 538, story_title: story.title, name: "Robin", turn: 0 },
  ],
};

it("distinguishes a generated prologue from a new character and filters all lobby save surfaces", async () => {
  window.api.player.bootstrap.mockResolvedValue({ ...account, saves: [
    { ...account.saves[0], name: "赵玖", turn: 0, has_opening: true },
    { ...account.saves[1], name: "Robin", turn: 0, has_opening: false, story_title: "另一部故事" },
  ] });
  render(<PlayerApp />);
  await screen.findByRole("heading", { name: "故事大厅" });
  expect(screen.getAllByText(/序章已生成/).length).toBeGreaterThan(0);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "另一部" } });
  expect(screen.queryByText(/赵玖/)).toBeNull();
  expect(screen.getAllByText(/Robin/).length).toBeGreaterThan(0);
});
beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
  history.replaceState({}, "", "/play");
  window.scrollTo = vi.fn();
  window.api = { player: {
    session: vi.fn().mockResolvedValue({ authenticated: true }),
    bootstrap: vi.fn().mockResolvedValue(account),
    catalog: vi.fn().mockResolvedValue({ stories: [story] }),
  } };
});

it.each([false, true])("shows the beta notice in the lobby with authentication=%s", async (authenticated) => {
  window.api.player.session.mockResolvedValue({ authenticated });
  render(<PlayerApp />);
  const notice = await screen.findByRole("status", { name: "内测公告" });
  expect(notice).toHaveTextContent("对话不限次数");
  expect(notice).toHaveTextContent("联系群主领取兑换码");
  expect(notice).toHaveTextContent("1132435140");
  expect(screen.getByRole("link", { name: "加入内测群" })).toHaveAttribute("href", "https://qm.qq.com/q/MDjwl91IwE");
  if (!authenticated) expect(window.api.player.bootstrap).not.toHaveBeenCalled();
});

it("copies the QQ group number and confirms success", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  render(<PlayerApp />);
  fireEvent.click(await screen.findByRole("button", { name: "复制QQ群号 1132435140" }));
  await screen.findByText("已复制群号");
  expect(writeText).toHaveBeenCalledWith("1132435140");
});

it("keeps the group number and join link available if clipboard permission is denied", async () => {
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error("Denied")) } });
  render(<PlayerApp />);
  fireEvent.click(await screen.findByRole("button", { name: "复制QQ群号 1132435140" }));
  await screen.findByText("复制失败，请长按群号复制。");
  expect(screen.getByRole("link", { name: "加入内测群" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "复制QQ群号 1132435140" })).toBeTruthy();
});

it("dismisses the notice for this browser session and returns focus to the lobby", async () => {
  const view = render(<PlayerApp />);
  fireEvent.click(await screen.findByRole("button", { name: "关闭内测公告" }));
  expect(screen.queryByRole("status", { name: "内测公告" })).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole("main"));
  view.unmount();
  render(<PlayerApp />);
  await screen.findByRole("heading", { name: "故事大厅" });
  expect(screen.queryByRole("status", { name: "内测公告" })).toBeNull();
});

it("can close the notice when browser storage is unavailable", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("Disabled"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Disabled"); });
  render(<PlayerApp />);
  fireEvent.click(await screen.findByRole("button", { name: "关闭内测公告" }));
  expect(screen.queryByRole("status", { name: "内测公告" })).toBeNull();
});

it("keeps the lobby beta notice out of the personal archive", async () => {
  history.replaceState({}, "", "/play/saves");
  render(<PlayerApp />);
  await screen.findByRole("heading", { name: "我的存档" });
  expect(screen.queryByRole("status", { name: "内测公告" })).toBeNull();
});

it("opens all personal saves and searches by character name without changing the catalog", async () => {
  render(<PlayerApp />);
  await screen.findByRole("heading", { name: "故事大厅" });
  fireEvent.click(screen.getByRole("button", { name: "我的存档", exact: true }));
  expect(location.pathname).toBe("/play/saves");
  expect(screen.getByRole("heading", { name: "我的存档" })).toBeTruthy();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "  aLeX " } });
  expect(screen.getByRole("button", { name: /Alex · 第 3 回合/ })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Robin/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "清除搜索" }));
  expect(screen.getByRole("button", { name: /Robin · 待开场/ })).toBeTruthy();
  await waitFor(() => expect(window.api.player.bootstrap).toHaveBeenCalledTimes(2));
});

it("refreshes the catalog and saves when returning to the lobby", async () => {
  history.replaceState({}, "", "/play/saves");
  render(<PlayerApp />);
  await screen.findByRole("heading", { name: "我的存档" });
  const published = { ...story, id: 999, title: "新上架故事" };
  window.api.player.bootstrap.mockResolvedValue({ ...account, stories: [published], saves: [] });
  fireEvent.click(screen.getByLabelText("故事大厅"));
  expect(await screen.findByRole("heading", { name: "新上架故事" })).toBeTruthy();
  expect(screen.queryByText("Alex")).toBeNull();
  expect(window.api.player.bootstrap).toHaveBeenCalledTimes(2);
});

it("does not let an older navigation refresh overwrite a newer catalog", async () => {
  render(<PlayerApp />);
  await screen.findByRole("heading", { name: "故事大厅" });
  let resolveOld;
  const oldResponse = new Promise(resolve => { resolveOld = resolve; });
  const published = { ...story, id: 999, title: "新上架故事" };
  window.api.player.bootstrap.mockReturnValueOnce(oldResponse).mockResolvedValueOnce({ ...account, stories: [published] });
  fireEvent.click(screen.getByRole("button", { name: "我的存档", exact: true }));
  await waitFor(() => expect(window.api.player.bootstrap).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByLabelText("故事大厅"));
  expect(await screen.findByRole("heading", { name: "新上架故事" })).toBeTruthy();
  await act(async () => { resolveOld(account); await oldResponse; });
  expect(screen.getByRole("heading", { name: "新上架故事" })).toBeTruthy();
});

it("pages and searches older saves", async () => {
  history.replaceState({}, "", "/play/saves");
  const first = Array.from({ length: 50 }, (_, index) => ({
    id: index + 1, story_id: story.id, story_title: story.title, name: `角色${index}`, title: "存档", turn: 0,
  }));
  const older = { id: 51, story_id: story.id, story_title: story.title, name: "旧角色", title: "存档", turn: 3 };
  window.api.player.bootstrap.mockResolvedValue({ ...account, saves: first, save_total: 51 });
  window.api.player.savesPage = vi.fn().mockImplementation((page, query) => Promise.resolve(
    query ? { items: [older], total: 1, page: 1, pages: 1 }
      : { items: page === 1 ? first : [older], total: 51, page, pages: 2 },
  ));
  render(<PlayerApp />);
  expect(await screen.findByRole("button", { name: "下一页" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "下一页" }));
  expect(await screen.findByRole("button", { name: /旧角色 · 第 3 回合/ })).toBeTruthy();
  fireEvent.change(screen.getByRole("searchbox", { name: "搜索存档" }), { target: { value: "旧角色" } });
  await waitFor(() => expect(window.api.player.savesPage).toHaveBeenLastCalledWith(1, "旧角色"));
  expect(await screen.findByRole("button", { name: /旧角色 · 第 3 回合/ })).toBeTruthy();
});

it("allows retrying a failed save page without hiding the error", async () => {
  history.replaceState({}, "", "/play/saves");
  window.api.player.bootstrap.mockResolvedValue({ ...account, save_total: 51 });
  window.api.player.savesPage = vi.fn().mockRejectedValueOnce(new Error("连接失败"))
    .mockResolvedValueOnce({ items: account.saves, total: 51, page: 1, pages: 2 });
  render(<PlayerApp />);
  expect(await screen.findByRole("alert")).toHaveTextContent("连接失败");
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  expect(await screen.findByRole("button", { name: /Alex · 第 3 回合/ })).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("keeps the archive private when a guest opens its URL", async () => {
  history.replaceState({}, "", "/play/saves");
  window.api.player.session.mockResolvedValue({ authenticated: false });
  render(<PlayerApp />);
  expect(await screen.findByRole("button", { name: "登录后继续" })).toBeTruthy();
  expect(window.api.player.bootstrap).not.toHaveBeenCalled();
  expect(screen.queryByText("Alex")).toBeNull();
});

it("keeps story and archive searches separate when returning through the brand", async () => {
  render(<PlayerApp />);
  await screen.findByRole("heading", { name: "故事大厅" });
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Hawkins" } });
  fireEvent.click(screen.getByRole("button", { name: "我的存档", exact: true }));
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Alex" } });
  fireEvent.click(screen.getByLabelText("故事大厅"));
  expect(screen.getByRole("searchbox").value).toBe("Hawkins");
  expect(screen.getByRole("button", { name: "开始故事" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "全部 2" }));
  expect(screen.getByRole("searchbox").value).toBe("");
  expect(screen.getByRole("button", { name: /Robin · 待开场/ })).toBeTruthy();
});

it("searches visible story introductions with case-insensitive keywords and clears a miss", async () => {
  window.api.player.session.mockResolvedValue({ authenticated: false });
  render(<PlayerApp />);
  await screen.findByRole("heading", { name: story.title });
  expect(screen.getByText(story.introduction)).toBeTruthy();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "  HAWKINS  " } });
  expect(screen.getByRole("button", { name: "开始故事" })).toBeTruthy();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "没有这个故事" } });
  expect(screen.getByText("没有找到这个故事")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "清除关键词" }));
  expect(screen.getByRole("button", { name: "开始故事" })).toBeTruthy();
});

it("shows a recoverable loading failure and retries discovery", async () => {
  window.api.player.session.mockRejectedValueOnce(new Error("网络连接失败"));
  render(<PlayerApp />);
  expect(await screen.findByRole("alert")).toHaveTextContent("网络连接失败");
  fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
  expect(await screen.findByRole("heading", { name: "故事大厅" })).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
});
