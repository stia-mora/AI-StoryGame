import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Comments } from "../player/Comments.jsx";
import { PlayerApp } from "../player/PlayerApp.jsx";
import { __resolveNextOrDefault } from "../components/login/nextTarget.js";

const story = { id: 7, title: "雾海来信", introduction: "一封信", cover: "", identities: [] };
const mine = { id: 3, author: "玩家甲", content: "很喜欢这个故事", created_at: "2026-10-26T10:00:00Z", can_delete: true };
const props = { story, user: { id: 44, name: "玩家甲", admin: false }, navigate: vi.fn(), login: vi.fn() };
beforeEach(() => {
  localStorage.clear(); vi.clearAllMocks();
  window.api = { player: {
    comments: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    postComment: vi.fn().mockResolvedValue(mine), deleteComment: vi.fn().mockResolvedValue({ ok: true }),
  } };
});

it("lets a guest read plain text and offers login without a composer", async () => {
  window.api.player.comments.mockResolvedValue({ items: [{ ...mine, content: "<img src=x onerror=alert(1)>", can_delete: false }], next_cursor: null });
  const { container } = render(<Comments {...props} user={null} />);
  expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeTruthy();
  expect(container.querySelector("img")).toBeNull();
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(screen.queryByRole("button", { name: /删除/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "登录后评论" }));
  expect(props.login).toHaveBeenCalled();
});

it("keeps a failed draft, posts on retry and retains it across reopening", async () => {
  window.api.player.postComment.mockRejectedValueOnce(new Error("连接失败"));
  const first = render(<Comments {...props} />);
  await screen.findByText("还没有评论，来聊聊这个故事吧。");
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "很喜欢这个故事" } });
  fireEvent.click(screen.getByRole("button", { name: "发布评论" }));
  expect(await screen.findByText("连接失败")).toBeTruthy();
  first.unmount();
  render(<Comments {...props} />);
  expect(screen.getByRole("textbox")).toHaveValue("很喜欢这个故事");
  await screen.findByText("还没有评论，来聊聊这个故事吧。");
  fireEvent.click(screen.getByRole("button", { name: "发布评论" }));
  expect(await screen.findByText("评论已发布")).toBeTruthy();
  expect(window.api.player.postComment).toHaveBeenLastCalledWith(7, "很喜欢这个故事");
  expect(screen.getByRole("textbox")).toHaveValue("");
});

it("loads older comments, confirms deletion and retains the row on failure", async () => {
  window.api.player.comments.mockResolvedValueOnce({ items: [mine], next_cursor: 3 })
    .mockResolvedValueOnce({ items: [{ ...mine, id: 2, content: "旧评论", can_delete: false }], next_cursor: null });
  window.api.player.deleteComment.mockRejectedValueOnce(new Error("删除失败"));
  render(<Comments {...props} />);
  await screen.findByText(mine.content);
  fireEvent.click(screen.getByRole("button", { name: "加载更早评论" }));
  expect(await screen.findByText("旧评论")).toBeTruthy();
  expect(window.api.player.comments).toHaveBeenLastCalledWith(7, 3);
  fireEvent.click(screen.getByRole("button", { name: "删除玩家甲的评论" }));
  expect(window.api.player.deleteComment).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await screen.findByText("删除失败");
  expect(screen.getByText(mine.content)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await screen.findByText("评论已删除");
  expect(screen.queryByText(mine.content)).toBeNull();
});

it("retries an initial load without falsely showing an empty discussion", async () => {
  window.api.player.comments.mockRejectedValueOnce(new Error("加载失败"));
  render(<Comments {...props} />);
  await screen.findByText("加载失败");
  expect(screen.queryByText("还没有评论，来聊聊这个故事吧。")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "重试加载" }));
  await screen.findByText("还没有评论，来聊聊这个故事吧。");
});

it("protects IME entry and prevents duplicate submits", async () => {
  let resolvePost;
  window.api.player.postComment.mockImplementation(() => new Promise((resolve) => { resolvePost = resolve; }));
  render(<Comments {...props} />);
  await screen.findByText("还没有评论，来聊聊这个故事吧。");
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "测试" } });
  fireEvent.compositionStart(input);
  fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
  expect(window.api.player.postComment).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "发布评论" }));
  fireEvent.submit(screen.getByRole("form", { name: "发表评论" }));
  expect(window.api.player.postComment).toHaveBeenCalledTimes(1);
  resolvePost(mine);
  await screen.findByText("评论已发布");
});

it("opens the story discussion from the public lobby without private requests", async () => {
  history.replaceState({}, "", "/play"); window.scrollTo = vi.fn();
  Object.assign(window.api.player, {
    session: vi.fn().mockResolvedValue({ authenticated: false }), catalog: vi.fn().mockResolvedValue({ stories: [story] }), bootstrap: vi.fn(),
  });
  render(<PlayerApp />);
  fireEvent.click(await screen.findByRole("button", { name: "查看雾海来信的评论" }));
  expect(await screen.findByRole("heading", { name: "故事评论" })).toBeTruthy();
  await waitFor(() => expect(window.api.player.comments).toHaveBeenCalledWith(7));
  expect(location.pathname).toBe("/play/stories/7/comments");
  expect(window.api.player.bootstrap).not.toHaveBeenCalled();
});

it("returns to the same discussion after login", () => {
  history.replaceState({}, "", "/Login.html?next=%2Fplay%2Fstories%2F7%2Fcomments");
  expect(__resolveNextOrDefault({ account_mode: "player" })).toBe("/play/stories/7/comments");
});

it("does not submit a shortcut while the initial page is still loading", () => {
  window.api.player.comments.mockReturnValue(new Promise(() => {}));
  render(<Comments {...props} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "先等评论加载完成" } });
  fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter", ctrlKey: true });
  expect(window.api.player.postComment).not.toHaveBeenCalled();
});
