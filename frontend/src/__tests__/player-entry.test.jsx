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
beforeEach(() => {
  history.replaceState({}, "", "/play");
  window.scrollTo = vi.fn();
  window.api = { player: {
    session: vi.fn().mockResolvedValue({ authenticated: true }),
    bootstrap: vi.fn().mockResolvedValue(account),
    catalog: vi.fn().mockResolvedValue({ stories: [story] }),
  } };
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
