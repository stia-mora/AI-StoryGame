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

it("restores both the current step and unsent text without creating a save", () => {
  const first = render(<Initialize {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "同龄伙伴" }));
  fireEvent.change(screen.getByLabelText("你的名字"), { target: { value: "未发送的名字" } });
  first.unmount();
  render(<Initialize {...props} />);
  expect(screen.getByLabelText("你的名字").value).toBe("未发送的名字");
  expect(window.api.player.create).not.toHaveBeenCalled();
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
