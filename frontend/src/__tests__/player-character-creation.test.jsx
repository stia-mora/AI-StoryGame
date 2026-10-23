import React from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Start } from "../player/PlayerApp.jsx";

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
  window.api = {
    player: { create: vi.fn().mockResolvedValue({ save: { id: 17 } }) },
  };
});
function start(selectedStory = story) {
  const navigate = vi.fn(),
    refresh = vi.fn().mockResolvedValue();
  render(<Start story={selectedStory} navigate={navigate} refresh={refresh} />);
  fireEvent.change(screen.getByLabelText("你的名字"), {
    target: { value: "沈砚" },
  });
  return navigate;
}
it("chooses a recommended soul before entering the paid opening", async () => {
  const navigate = start();
  fireEvent.click(screen.getByLabelText(/岩纹盾/));
  fireEvent.click(screen.getByRole("button", { name: "带着这个身份出发" }));
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("/play/saves/17"));
  expect(window.api.player.create).toHaveBeenCalledWith(
    expect.objectContaining({
      martial_soul: { mode: "recommended", name: "岩纹盾" },
    }),
  );
});
it("accepts a custom soul name and requires it before form submission", async () => {
  start();
  fireEvent.click(screen.getByLabelText("自己填写"));
  expect(screen.getByLabelText("武魂名称").required).toBe(true);
  fireEvent.change(screen.getByLabelText("武魂名称"), {
    target: { value: "青羽弓" },
  });
  fireEvent.click(screen.getByRole("button", { name: "带着这个身份出发" }));
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
  fireEvent.click(screen.getByLabelText("随机觉醒"));
  expect(screen.getByText(/随机结果只抽一次/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "带着这个身份出发" }));
  await waitFor(() =>
    expect(window.api.player.create).toHaveBeenCalledWith(
      expect.objectContaining({
        martial_soul: { mode: "random", name: "" },
      }),
    ),
  );
});
it("keeps other stories free of martial soul configuration", async () => {
  start({ ...story, martial_soul_creation: null });
  expect(screen.queryByText("你想觉醒什么武魂？")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "带着这个身份出发" }));
  await waitFor(() => expect(window.api.player.create).toHaveBeenCalled());
  expect(window.api.player.create.mock.calls[0][0]).not.toHaveProperty(
    "martial_soul",
  );
});

it("preserves character details after a failed creation and allows retry", async () => {
  window.api.player.create.mockRejectedValueOnce(new Error("连接暂时中断"));
  start({ ...story, martial_soul_creation: null });
  fireEvent.change(screen.getByLabelText("角色背景"), { target: { value: "喜欢修理对讲机" } });
  fireEvent.click(screen.getByRole("button", { name: "带着这个身份出发" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("连接暂时中断");
  expect(screen.getByLabelText("你的名字").value).toBe("沈砚");
  expect(screen.getByLabelText("角色背景").value).toBe("喜欢修理对讲机");
  expect(screen.getByRole("button", { name: "带着这个身份出发" }).disabled).toBe(false);
});
