import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Initialize } from "../player/Initialize.jsx";
import { StreamingNarration } from "../player/shared.jsx";

const story = { id: 538, title: "万圣夜", introduction: "和朋友们准备出发。", cover: "", identities: [{ id: "friend", name: "同龄伙伴" }] };
const props = { story, uid: 44, navigate: vi.fn(), refresh: vi.fn().mockResolvedValue() };
const send = (label, value) => {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "发送设定" }));
};
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  window.api = { player: { create: vi.fn().mockResolvedValue({ save: { id: 99 } }) } };
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it("accepts free identity and background in the chat and creates only after confirmation", async () => {
  render(<Initialize {...props} />);
  send("初始化设定", "修理对讲机的学生");
  expect(document.activeElement).toBe(screen.getByLabelText("你的名字"));
  send("你的名字", "小林");
  send("初始化设定", "我住在学校附近，想调查街灯异常。");
  expect(window.api.player.create).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认设定，进入故事" }));
  await waitFor(() => expect(props.navigate).toHaveBeenCalledWith("/play/saves/99"));
  expect(window.api.player.create).toHaveBeenCalledWith({ story_id: 538, name: "小林", identity_id: "", custom_identity: "修理对讲机的学生", background: "我住在学校附近，想调查街灯异常。" });
  expect(localStorage.getItem("player-setup-44-538")).toBeNull();
});

it("uses an original character's name and skips renaming while keeping custom roles available", async () => {
  const cast = { ...story, identities: [{ id: "emperor", name: "赵官家（赵玖）", character_name: "赵玖", description: "从明道宫执掌行在。" }, ...story.identities] };
  render(<Initialize {...props} story={cast} />);
  fireEvent.click(screen.getByRole("button", { name: /赵官家/ }));
  expect(screen.queryByLabelText("你的名字")).toBeNull();
  expect(screen.getByText(/你将扮演赵玖/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "名字", exact: true })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "跳过，使用当前设定" }));
  expect(screen.getByRole("button", { name: "修改名字" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "确认设定，进入故事" }));
  await waitFor(() => expect(window.api.player.create).toHaveBeenCalledWith(expect.objectContaining({ name: "赵玖", identity_id: "emperor" })));
});

it("lets a player switch from an original character to their own named character", () => {
  const cast = { ...story, identities: [{ id: "yue", name: "岳飞", character_name: "岳飞" }, ...story.identities] };
  render(<Initialize {...props} story={cast} />);
  fireEvent.click(screen.getByRole("button", { name: "岳飞" }));
  fireEvent.click(screen.getByRole("button", { name: "身份", exact: true }));
  fireEvent.click(screen.getByRole("button", { name: "同龄伙伴" }));
  expect(screen.getByLabelText("你的名字")).toHaveValue("");
  send("你的名字", "小林");
  expect(screen.getByRole("heading", { name: "还有想带入故事的设定吗？" })).toBeTruthy();
});

it("restores both the current step and unsent text without creating a save", () => {
  const first = render(<Initialize {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "同龄伙伴" }));
  fireEvent.change(screen.getByLabelText("你的名字"), { target: { value: "未发送的名字" } });
  first.unmount();
  render(<Initialize {...props} />);
  expect(screen.getByLabelText("你的名字").value).toBe("未发送的名字");
  expect(window.api.player.create).not.toHaveBeenCalled();
});

it("keeps unsent drafts for each step while navigating and after reopening", () => {
  const first = render(<Initialize {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "同龄伙伴" }));
  fireEvent.change(screen.getByLabelText("你的名字"), { target: { value: "未发送的名字" } });
  fireEvent.click(screen.getByRole("button", { name: "身份", exact: true }));
  fireEvent.change(screen.getByLabelText("初始化设定"), { target: { value: "还在考虑的身份" } });
  fireEvent.click(screen.getByRole("button", { name: "名字", exact: true }));
  expect(screen.getByLabelText("你的名字")).toHaveValue("未发送的名字");
  first.unmount();
  render(<Initialize {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "身份", exact: true }));
  expect(screen.getByLabelText("初始化设定")).toHaveValue("还在考虑的身份");
  expect(window.api.player.create).not.toHaveBeenCalled();
});

it("edits a single confirmed field and returns directly to review without losing other settings", async () => {
  render(<Initialize {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "同龄伙伴" }));
  send("你的名字", "小林");
  send("初始化设定", "想调查街灯异常。");
  fireEvent.click(screen.getByRole("button", { name: "修改名字" }));
  expect(screen.getByLabelText("你的名字")).toHaveValue("小林");
  send("你的名字", "林晓");
  expect(screen.getByRole("heading", { name: "确认角色设定" })).toBeTruthy();
  expect(window.api.player.create).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认设定，进入故事" }));
  await waitFor(() => expect(window.api.player.create).toHaveBeenCalledWith(expect.objectContaining({ name: "林晓", identity_id: "friend", background: "想调查街灯异常。" })));
});

it("keeps future steps unavailable until their prerequisites are confirmed", () => {
  render(<Initialize {...props} />);
  expect(screen.getByRole("button", { name: "名字", exact: true })).toBeDisabled();
  expect(screen.getByRole("button", { name: "背景", exact: true })).toBeDisabled();
  expect(screen.getByRole("button", { name: "确认", exact: true })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "武魂", exact: true })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "同龄伙伴" }));
  expect(screen.getByRole("button", { name: "名字", exact: true })).toBeEnabled();
  expect(screen.getByRole("button", { name: "背景", exact: true })).toBeDisabled();
  send("你的名字", "小林");
  expect(screen.getByRole("button", { name: "背景", exact: true })).toBeEnabled();
  expect(screen.getByRole("button", { name: "确认", exact: true })).toBeDisabled();
});

it("opens the created save even when refreshing the lobby fails", async () => {
  const refresh = vi.fn().mockRejectedValue(new Error("目录刷新失败"));
  render(<Initialize {...props} refresh={refresh} />);
  fireEvent.click(screen.getByRole("button", { name: "同龄伙伴" }));
  send("你的名字", "小林");
  fireEvent.click(screen.getByRole("button", { name: "跳过，使用当前设定" }));
  fireEvent.click(screen.getByRole("button", { name: "确认设定，进入故事" }));
  await waitFor(() => expect(props.navigate).toHaveBeenCalledWith("/play/saves/99"));
  expect(window.api.player.create).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(localStorage.getItem("player-setup-44-538")).toBeNull();
});

it("restores an existing review and explicitly allows clearing its background", async () => {
  localStorage.setItem("player-setup-44-538", JSON.stringify({ step: "review", identity: "friend", name: "小林", background: "旧背景", draft: "" }));
  render(<Initialize {...props} />);
  expect(screen.getByRole("button", { name: "确认设定，进入故事" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "修改背景" }));
  expect(screen.getByLabelText("初始化设定")).toHaveValue("旧背景");
  fireEvent.click(screen.getByRole("button", { name: "清空背景，返回确认" }));
  fireEvent.click(screen.getByRole("button", { name: "确认设定，进入故事" }));
  await waitFor(() => expect(window.api.player.create).toHaveBeenCalledWith(expect.objectContaining({ background: "" })));
});

it("locks creation while a request is outstanding and restores copy feedback after 2.5 seconds", async () => {
  render(<Initialize {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "同龄伙伴" }));
  send("你的名字", "小林");
  fireEvent.click(screen.getByRole("button", { name: "跳过，使用当前设定" }));
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockResolvedValue() } });
  vi.useFakeTimers();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "复制设定" })));
  expect(screen.getByRole("button", { name: "已复制" })).toBeTruthy();
  act(() => vi.advanceTimersByTime(2500));
  expect(screen.getByRole("button", { name: "复制设定" })).toBeTruthy();
  window.api.player.create.mockImplementation(() => new Promise(() => {}));
  fireEvent.click(screen.getByRole("button", { name: "确认设定，进入故事" }));
  fireEvent.click(screen.getByRole("button", { name: "正在创建角色……" }));
  expect(window.api.player.create).toHaveBeenCalledTimes(1);
});

it("keeps existing streamed glyphs mounted when more text arrives", () => {
  const { container, rerender } = render(<StreamingNarration text="你好" />);
  const first = container.querySelector("span");
  rerender(<StreamingNarration text="你好，朋友" />);
  expect(container.querySelector("span")).toBe(first);
  expect(container.textContent).toBe("你好，朋友");
  rerender(<StreamingNarration text="新回复" />);
  expect(container.textContent).toBe("新回复");
});
