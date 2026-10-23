import React from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Initialize } from "../player/Initialize.jsx";

const story = {
  id: 4,
  title: "觉醒之旅",
  introduction: "从首次觉醒开始成长。",
  identities: [{ id: "native", name: "村中少年", role: "少年" }],
  martial_soul_creation: {
    choices: [
      { name: "铁剑", description: "器武魂" },
      { name: "岩纹盾", description: "防护" },
    ],
    allow_custom: true,
    allow_random: true,
  },
};
beforeEach(() => {
  localStorage.clear();
  window.api = {
    player: { create: vi.fn().mockResolvedValue({ save: { id: 17 } }) },
  };
});
function start(selectedStory = story) {
  const navigate = vi.fn(),
    refresh = vi.fn().mockResolvedValue();
  render(<Initialize story={selectedStory} uid={1} navigate={navigate} refresh={refresh} />);
  fireEvent.click(screen.getByRole("button", { name: /村中少年/ }));
  fireEvent.change(screen.getByLabelText("你的名字"), {
    target: { value: "沈砚" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送设定" }));
  return navigate;
}
it("chooses a recommended soul before entering the paid opening", async () => {
  const navigate = start();
  fireEvent.click(screen.getByRole("button", { name: /岩纹盾/ }));
  fireEvent.click(screen.getByRole("button", { name: "跳过，使用当前设定" }));
  fireEvent.click(screen.getByRole("button", { name: "确认设定，进入故事" }));
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("/play/saves/17"));
  expect(window.api.player.create).toHaveBeenCalledWith(
    expect.objectContaining({
      martial_soul: { mode: "recommended", name: "岩纹盾" },
    }),
  );
});
it("accepts a custom soul name and requires it before form submission", async () => {
  start();
  fireEvent.change(screen.getByLabelText("初始化设定"), { target: { value: "青羽弓" } });
  fireEvent.click(screen.getByRole("button", { name: "发送设定" }));
  fireEvent.click(screen.getByRole("button", { name: "跳过，使用当前设定" }));
  fireEvent.click(screen.getByRole("button", { name: "确认设定，进入故事" }));
  await waitFor(() =>
    expect(window.api.player.create).toHaveBeenCalledWith(
      expect.objectContaining({
        martial_soul: { mode: "custom", name: "青羽弓" },
      }),
    ),
  );
});
it("sends a random choice without granting or selecting power on the client", async () => {
  start();
  fireEvent.click(screen.getByRole("button", { name: /随机觉醒/ }));
  fireEvent.click(screen.getByRole("button", { name: "跳过，使用当前设定" }));
  fireEvent.click(screen.getByRole("button", { name: "确认设定，进入故事" }));
  await waitFor(() =>
    expect(window.api.player.create).toHaveBeenCalledWith(
      expect.objectContaining({
        martial_soul: { mode: "random", name: "" },
      }),
    ),
  );
});
it("rejects custom input when a story only allows the provided souls", () => {
  start({ ...story, martial_soul_creation: { ...story.martial_soul_creation, allow_custom: false, allow_random: false } });
  const input = screen.getByLabelText("初始化设定");
  expect(input).toBeDisabled();
  expect(screen.getByRole("button", { name: "发送设定" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: /随机觉醒/ })).toBeNull();
  fireEvent.change(input, { target: { value: "不允许的武魂" } });
  fireEvent.submit(input.closest("form"));
  expect(screen.getByRole("heading", { name: "选择你的武魂" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "背景", exact: true })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: /铁剑/ }));
  expect(screen.getByRole("heading", { name: "还有想带入故事的设定吗？" })).toBeTruthy();
  expect(window.api.player.create).not.toHaveBeenCalled();
});
it("keeps other stories free of martial soul configuration", async () => {
  start({ ...story, martial_soul_creation: null });
  expect(screen.queryByLabelText("武魂选项")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "跳过，使用当前设定" }));
  fireEvent.click(screen.getByRole("button", { name: "确认设定，进入故事" }));
  await waitFor(() => expect(window.api.player.create).toHaveBeenCalled());
  expect(window.api.player.create.mock.calls[0][0]).not.toHaveProperty(
    "martial_soul",
  );
});

it("preserves character details after a failed creation and allows retry", async () => {
  window.api.player.create.mockRejectedValueOnce(new Error("连接暂时中断"));
  start({ ...story, martial_soul_creation: null });
  fireEvent.change(screen.getByLabelText("初始化设定"), { target: { value: "喜欢修理对讲机" } });
  fireEvent.click(screen.getByRole("button", { name: "发送设定" }));
  fireEvent.click(screen.getByRole("button", { name: "确认设定，进入故事" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("连接暂时中断");
  expect(window.api.player.create).toHaveBeenCalledWith(expect.objectContaining({ name: "沈砚", background: "喜欢修理对讲机" }));
  expect(screen.getByRole("button", { name: "确认设定，进入故事" }).disabled).toBe(false);

});
