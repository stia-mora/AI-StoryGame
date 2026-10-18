import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { PlayerApp } from "../player/PlayerApp.jsx";
import { Reader } from "../player/Reader.jsx";
import { TurnProgress } from "../player/Progress.jsx";
import { __resolveNextOrDefault } from "../components/login/nextTarget.js";

beforeEach(() => {
  localStorage.clear();
  history.replaceState({}, "", "/play");
  window.scrollTo = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
  window.api = {
    player: {
      bootstrap: vi.fn().mockResolvedValue({
        user: { id: 1, name: "Test", creator: false, admin: false },
        wallet: { free_micro: 100000000, permanent_micro: 0 },
        stories: [],
        saves: [],
      }),
    },
  };
});
describe("player-only entry", () => {
  it("keeps a newer execution when an old connection completes after navigation", async () => {
    const channels = [];
    window.api.player.save = vi.fn().mockResolvedValue({
      save: { story_title: "测试故事", turn: 1 },
      status: { name: "旅人" },
      messages: [],
      options: [],
      has_opening: true,
    });
    window.api.player.quote = vi.fn().mockResolvedValue({
      id: "q",
      affordable: true,
      estimate_micro: 1000000,
      cap_micro: 5000000,
    });
    window.api.player.execute = vi.fn((body, handlers) => {
      let resolve;
      const done = new Promise((r) => {
        resolve = r;
      });
      channels.push({ body, handlers, resolve });
      return { done };
    });
    window.api.player.request = vi.fn((id) =>
      Promise.resolve({
        status: id === channels[0]?.body.request_id ? "settled" : "running",
        receipt: { saved: true },
      }),
    );
    const props = {
      saveId: 9,
      uid: 1,
      navigate: vi.fn(),
      prefs: { font: 18 },
      setPrefs: vi.fn(),
      refreshWallet: vi.fn().mockResolvedValue(undefined),
    };
    const first = render(<Reader {...props} />);
    fireEvent.change(await screen.findByLabelText("你要如何行动？"), {
      target: { value: "第一步" },
    });
    await screen.findByText(/预计/);
    fireEvent.click(screen.getByRole("button", { name: "行动" }));
    first.unmount();
    render(<Reader {...props} />);
    await waitFor(() =>
      expect(screen.getByLabelText("你要如何行动？").disabled).toBe(false),
    );
    fireEvent.change(screen.getByLabelText("你要如何行动？"), {
      target: { value: "第二步" },
    });
    await screen.findByText(/预计/);
    fireEvent.click(screen.getByRole("button", { name: "行动" }));
    expect(channels).toHaveLength(2);
    await act(async () => {
      channels[0].resolve();
    });
    expect(
      JSON.parse(localStorage.getItem("player-request-1-9")).request_id,
    ).toBe(channels[1].body.request_id);
    expect(screen.getByRole("button", { name: "停止生成" })).toBeTruthy();
  });
  it("sends a quoted scene action on one click and prevents a duplicate execution", async () => {
    const options = [
      "查看脚印",
      "**向同行者询问**",
      "检查药剂",
      "留在原地观察",
    ];
    window.api.player.save = vi.fn().mockResolvedValue({
      save: { story_title: "测试故事", turn: 1 },
      status: { name: "旅人", location: "村口" },
      messages: [],
      options,
      has_opening: true,
      journey: [],
    });
    window.api.player.quote = vi.fn((body) =>
      Promise.resolve({
        id: `q-${body.message}`,
        affordable: true,
        cap_micro: 5000000,
        estimate_micro: 1000000,
      }),
    );
    window.api.player.execute = vi.fn(() => ({ done: new Promise(() => {}) }));
    window.api.player.request = vi
      .fn()
      .mockResolvedValue({ status: "running" });
    render(
      <Reader
        saveId={9}
        uid={1}
        navigate={vi.fn()}
        prefs={{ font: 18 }}
        setPrefs={vi.fn()}
        refreshWallet={vi.fn()}
      />,
    );
    await screen.findByRole("heading", { name: "选择行动" });
    expect(screen.getAllByRole("button", { name: /^[ABCD] / })).toHaveLength(4);
    const choice = screen.getByRole("button", { name: "B 向同行者询问" });
    await waitFor(() => expect(choice.disabled).toBe(false));
    fireEvent.click(choice);
    fireEvent.click(choice);
    expect(window.api.player.execute).toHaveBeenCalledTimes(1);
    expect(window.api.player.execute.mock.calls[0][0]).toMatchObject({
      message: "【快进至下一处关键抉择】向同行者询问",
      quote_id: "q-【快进至下一处关键抉择】向同行者询问",
      cap_micro: 5000000,
      kind: "turn",
    });
    expect(screen.getByLabelText("你要如何行动？").value).toBe("向同行者询问");
    expect(screen.getByRole("button", { name: "停止生成" })).toBeTruthy();
  });
  it("never executes a scene option while its quote is pending or unaffordable", async () => {
    let quoteReady;
    const quotation = new Promise((resolve) => {
      quoteReady = resolve;
    });
    window.api.player.save = vi.fn().mockResolvedValue({
      save: { story_title: "测试故事", turn: 1 },
      status: { name: "旅人" },
      messages: [],
      options: ["探索村口", "询问村长", "修炼", "观察"],
      has_opening: true,
    });
    window.api.player.quote = vi.fn().mockReturnValue(quotation);
    window.api.player.execute = vi.fn();
    render(
      <Reader
        saveId={9}
        uid={1}
        navigate={vi.fn()}
        prefs={{ font: 18 }}
        setPrefs={vi.fn()}
        refreshWallet={vi.fn()}
      />,
    );
    const choice = await screen.findByRole("button", { name: "A 探索村口" });
    expect(choice.disabled).toBe(true);
    fireEvent.click(choice);
    await act(async () =>
      quoteReady({
        id: "q",
        affordable: false,
        cap_micro: 5000000,
        estimate_micro: 1000000,
      }),
    );
    expect(choice.disabled).toBe(true);
    fireEvent.click(choice);
    expect(window.api.player.execute).not.toHaveBeenCalled();
    expect(screen.getByText("余额不足，查看积分与兑换码")).toBeTruthy();
  });
  it("distinguishes actual gains from worldline changes", () => {
    render(
      <TurnProgress
        latest
        progress={{
          gains: [{ kind: "物品", text: "铜制徽记" }],
          losses: [],
          changes: [{ kind: "人物关系", before: "警惕", after: "信任" }],
          events: [],
        }}
      />,
    );
    expect(screen.getByText("铜制徽记")).toBeTruthy();
    expect(screen.getByText("警惕")).toBeTruthy();
    expect(screen.getByText("信任")).toBeTruthy();
  });
  it("shows an actionable empty library and hides creator controls", async () => {
    render(<PlayerApp />);
    expect(await screen.findByText("下一段故事正在准备中")).toBeTruthy();
    expect(screen.queryByText("创作工作台")).toBeNull();
    expect(screen.getByText("100.00 积分")).toBeTruthy();
  });
  it("prioritizes the latest save and opens it", async () => {
    window.api.player.bootstrap.mockResolvedValue({
      user: { id: 1 },
      wallet: { free_micro: 100000000, permanent_micro: 0 },
      stories: [],
      saves: [{ id: 9, story_title: "测试故事", name: "旅人", turn: 3 }],
    });
    window.api.player.save = vi.fn().mockResolvedValue({
      save: { story_title: "测试故事", turn: 3 },
      status: { name: "旅人" },
      messages: [],
      options: [],
      has_opening: false,
    });
    window.api.player.quote = vi.fn().mockResolvedValue({
      id: "quote",
      estimate_micro: 2000000,
      cap_micro: 5000000,
      affordable: true,
    });
    render(<PlayerApp />);
    fireEvent.click(await screen.findByText("继续游玩"));
    await waitFor(() => expect(location.pathname).toBe("/play/saves/9"));
  });
  it("disables model execution before an affordable quote and restores draft", async () => {
    localStorage.setItem("player-draft-1-9", "沿着河岸寻找线索");
    window.api.player.save = vi.fn().mockResolvedValue({
      save: { story_title: "测试故事", turn: 1 },
      status: { name: "旅人" },
      messages: [],
      options: [],
      has_opening: true,
    });
    window.api.player.quote = vi.fn().mockResolvedValue({
      id: "q",
      estimate_micro: 2000000,
      cap_micro: 5000000,
      affordable: false,
    });
    render(
      <Reader
        saveId={9}
        uid={1}
        navigate={vi.fn()}
        prefs={{ font: 18 }}
        setPrefs={vi.fn()}
        refreshWallet={vi.fn()}
      />,
    );
    expect((await screen.findByLabelText("你要如何行动？")).value).toBe(
      "沿着河岸寻找线索",
    );
    await screen.findByText(/余额不足/);
    expect(screen.getByRole("button", { name: "行动" }).disabled).toBe(true);
    expect(screen.getByText("查看积分与兑换码")).toBeTruthy();
  });
  it("routes new players to play even when a creator URL is supplied", () => {
    history.replaceState({}, "", "/Login.html?next=/settings");
    expect(
      __resolveNextOrDefault({ account_mode: "player", role: "user" }),
    ).toBe("/play");
    expect(
      __resolveNextOrDefault({ account_mode: "creator", role: "user" }),
    ).toBe("/settings");
  });
});
