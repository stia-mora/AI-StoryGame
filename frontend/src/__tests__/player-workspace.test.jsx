import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  act,
} from "@testing-library/react";
import { Reader } from "../player/Reader.jsx";
import { Assistant } from "../player/Assistant.jsx";
import { InformationPanel } from "../player/WorkspacePanels.jsx";

const props = {
  uid: 1,
  saveId: 9,
  navigate: vi.fn(),
  prefs: { font: 18 },
  setPrefs: vi.fn(),
  refreshWallet: vi.fn().mockResolvedValue(undefined),
};
const view = {
  save: { id: 9, turn: 2, story_title: "测试世界" },
  status: { name: "旅人", location: "村口" },
  has_opening: true,
  options: ["向村长问路", "观察脚印", "检查背包", "暂时休息"],
  messages: [
    { id: "1-gm", role: "assistant", turn: 0, text: "你站在旧桥前。" },
    { id: "2-user", role: "user", text: "走到村口" },
    { id: "2-gm", role: "assistant", turn: 2, text: "你抵达了村口。" },
  ],
};

beforeEach(() => {
  localStorage.clear();
  Element.prototype.scrollIntoView = vi.fn();
  window.api = {
    player: {
      save: vi.fn().mockResolvedValue(view),
      guideHistory: vi.fn().mockResolvedValue({ items: [] }),
      quote: vi.fn((body) =>
        Promise.resolve({
          id: `q-${body.message}`,
          affordable: true,
          estimate_micro: 1000000,
          cap_micro: 5000000,
        }),
      ),
      execute: vi.fn(() => ({ done: new Promise(() => {}) })),
      request: vi.fn().mockResolvedValue({ status: "running" }),
    },
  };
});
afterEach(() => vi.restoreAllMocks());

it("receives server stages and unlocks a settled turn while the wallet request is stalled", async () => {
  let handlers, done;
  window.api.player.execute.mockImplementation((_body, callbacks) => {
    handlers = callbacks;
    return { done: new Promise((resolve) => { done = resolve; }) };
  });
  const refreshWallet = vi.fn().mockReturnValue(new Promise(() => {}));
  render(<Reader {...props} refreshWallet={refreshWallet} />);
  const choice = await screen.findByRole("button", { name: "A 向村长问路" });
  await waitFor(() => expect(choice.disabled).toBe(false));
  fireEvent.click(choice);
  expect(screen.getByRole("timer")).toHaveTextContent("已等待");
  act(() => handlers.on_stage({ phase: "retrieving", label: "正在整理故事资料" }));
  expect(screen.getByText("整理资料").getAttribute("aria-current")).toBe("step");
  act(() => handlers.on_token({ text: "村长为你指明了去学院的路。" }));
  expect(screen.getByText("生成剧情").getAttribute("aria-current")).toBe("step");
  act(() => handlers.on_stage({ phase: "saving", label: "正在保存剧情与结算积分" }));
  expect(screen.getByText("保存结算").getAttribute("aria-current")).toBe("step");
  window.api.player.request.mockResolvedValue({ status: "running", progress: { phase: "understanding" } });
  await act(async () => handlers.onClose());
  expect(screen.getByText("保存结算").getAttribute("aria-current")).toBe("step");
  window.api.player.request.mockResolvedValue({ status: "settled", receipt: { saved: true } });
  await act(async () => { done(); });
  await waitFor(() => expect(screen.getByLabelText("你要如何行动？").disabled).toBe(false));
  expect(screen.queryByRole("timer")).toBeNull();
  expect(refreshWallet).toHaveBeenCalled();
});

it("links to the full archive when the reader only has recent saves", async () => {
  const navigate = vi.fn();
  render(<Reader {...props} navigate={navigate} saves={[{ id: 9, name: "旅人", story_title: "测试世界", turn: 2 }]} saveTotal={51} />);
  const archive = await screen.findByText("查看全部 51 个存档");
  fireEvent.click(archive);
  expect(navigate).toHaveBeenCalledWith("/play/saves");
});

it("does not execute a quoted action while the IME is selecting or within 500ms of composition ending", async () => {
  render(<Reader {...props} />);
  const input = await screen.findByLabelText("你要如何行动？");
  fireEvent.change(input, { target: { value: "观察村口" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "行动" }).disabled).toBe(false));
  const now = vi.spyOn(Date, "now").mockReturnValue(1000);
  fireEvent.keyDown(input, { key: "Enter", ctrlKey: true, keyCode: 229 });
  fireEvent.compositionStart(input);
  fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
  fireEvent.compositionEnd(input);
  now.mockReturnValue(1499);
  fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
  expect(window.api.player.execute).not.toHaveBeenCalled();
  now.mockReturnValue(1500);
  fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
  expect(window.api.player.execute).toHaveBeenCalledTimes(1);
  expect(window.api.player.execute.mock.calls[0][0].message).toBe("观察村口");
});

it("reads one saved round at a time and keeps actions attached to current progress", async () => {
  render(<Reader {...props} />);
  expect(await screen.findByText("你抵达了村口。")).toBeTruthy();
  expect(screen.queryByText("你站在旧桥前。")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "上一回合" }));
  expect(screen.getByText("你站在旧桥前。")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "A 向村长问路" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "回到当前回合" }));
  expect(screen.getByRole("button", { name: "A 向村长问路" })).toBeTruthy();
  expect(window.api.player.execute).not.toHaveBeenCalled();
});

it("binds the same fast-forward instruction to the choice quote and execution", async () => {
  render(<Reader {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "快进" }));
  const action = screen.getByRole("button", { name: "A 向村长问路" });
  await waitFor(() => expect(action.disabled).toBe(false));
  fireEvent.click(action);
  expect(window.api.player.execute).toHaveBeenCalledTimes(1);
  expect(window.api.player.execute.mock.calls[0][0]).toMatchObject({
    message: "【快进至下一处关键抉择】向村长问路",
    quote_id: "q-【快进至下一处关键抉择】向村长问路",
  });
  expect(screen.getByLabelText("你要如何行动？").value).toBe("向村长问路");
});

it("keeps reading position, selected state tab and drafts while switching mobile views", async () => {
  const { container } = render(<Reader {...props} />);
  const input = await screen.findByLabelText("你要如何行动？");
  fireEvent.change(input, { target: { value: "先观察道路" } });
  const reading = container.querySelector(".workspace-reading");
  reading.scrollTop = 120;
  const navigation = screen.getByRole("navigation", { name: "游玩视图" });
  fireEvent.click(navigation.querySelectorAll("button")[1]);
  fireEvent.click(screen.getByRole("tab", { name: "背包" }));
  fireEvent.click(navigation.querySelectorAll("button")[2]);
  fireEvent.click(navigation.querySelectorAll("button")[1]);
  expect(screen.getByRole("tab", { name: "背包" }).getAttribute("aria-selected")).toBe("true");
  fireEvent.click(navigation.querySelectorAll("button")[0]);
  expect(container.querySelector(".workspace-reading")).toBe(reading);
  expect(reading.scrollTop).toBe(120);
  expect(input.value).toBe("先观察道路");
  fireEvent.click(navigation.querySelectorAll("button")[3]);
  fireEvent.change(screen.getByLabelText("向游玩助手提问"), { target: { value: "眼前有何风险？" } });
  fireEvent.click(navigation.querySelectorAll("button")[0]);
  fireEvent.click(navigation.querySelectorAll("button")[3]);
  expect(screen.getByLabelText("向游玩助手提问").value).toBe("眼前有何风险？");
  await waitFor(() => expect(screen.getByRole("button", { name: "A 向村长问路" }).disabled).toBe(false));
  expect(window.api.player.execute).not.toHaveBeenCalled();
});

it("restores the assistant trigger on Escape and leaves focus on a selected navigation item", async () => {
  render(<Reader {...props} />);
  await screen.findByText("你抵达了村口。");
  const buttons = screen.getByRole("navigation", { name: "游玩视图" }).querySelectorAll("button");
  buttons[3].focus();
  fireEvent.click(buttons[3]);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(document.activeElement).toBe(buttons[3]);
  fireEvent.click(buttons[3]);
  buttons[1].focus();
  fireEvent.click(buttons[1]);
  expect(document.activeElement).toBe(buttons[1]);
  await waitFor(() => expect(screen.getByRole("button", { name: "A 向村长问路" }).disabled).toBe(false));
});

it("moves focus into the story after selecting a round from records or worldline", async () => {
  window.api.player.save.mockResolvedValue({
    ...view,
    journey: [{ turn: 0, message_id: "1-gm", summary: "抵达旧桥" }],
  });
  render(<Reader {...props} />);
  await screen.findByText("你抵达了村口。");
  const navigation = screen.getByRole("navigation", { name: "游玩视图" });
  fireEvent.click(navigation.querySelectorAll("button")[2]);
  const record = screen.getByRole("button", { name: /^序章/ });
  record.focus();
  fireEvent.click(record);
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("region", { name: "剧情正文" })));
  expect(screen.getByText("你站在旧桥前。")).toBeTruthy();
  fireEvent.click(navigation.querySelectorAll("button")[1]);
  fireEvent.click(screen.getByRole("tab", { name: "世界线" }));
  const step = screen.getByRole("button", { name: "序章" });
  step.focus();
  fireEvent.click(step);
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("region", { name: "剧情正文" })));
  expect(window.api.player.execute).not.toHaveBeenCalled();
});

it("retains an interrupted execution through offline status checks and restores its saved reply", async () => {
  let resolve, handlers;
  window.api.player.execute.mockImplementation((body, callbacks) => {
    handlers = callbacks;
    return {
      done: new Promise((r) => {
        resolve = r;
      }),
    };
  });
  window.api.player.request.mockRejectedValue(new TypeError("offline"));
  render(<Reader {...props} />);
  const choice = await screen.findByRole("button", { name: "A 向村长问路" });
  await waitFor(() => expect(choice.disabled).toBe(false));
  fireEvent.click(choice);
  const request = window.api.player.execute.mock.calls[0][0];
  await act(async () => {
    handlers.onError(new TypeError("offline"));
    resolve();
  });
  expect(
    JSON.parse(localStorage.getItem("player-request-1-9")).request_id,
  ).toBe(request.request_id);
  expect(screen.getByRole("button", { name: "停止生成" })).toBeTruthy();
  expect(window.api.player.execute).toHaveBeenCalledTimes(1);
  window.api.player.request.mockResolvedValue({
    status: "settled",
    receipt: { saved: true },
  });
  window.api.player.save.mockResolvedValue({
    ...view,
    messages: [
      ...view.messages,
      {
        id: "3-gm",
        role: "assistant",
        turn: 3,
        text: "服务器已经保存了这一步。",
      },
    ],
  });
  await act(async () => {
    await handlers.onClose();
  });
  expect(await screen.findByText("服务器已经保存了这一步。")).toBeTruthy();
  expect(localStorage.getItem("player-request-1-9")).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("supports keyboard tab navigation and never invents empty character stats", () => {
  render(<InformationPanel view={view} onRead={vi.fn()} />);
  fireEvent.keyDown(screen.getByRole("tab", { name: "局势" }), {
    key: "ArrowRight",
  });
  expect(
    screen.getByRole("tab", { name: "角色" }).getAttribute("aria-selected"),
  ).toBe("true");
  expect(screen.getByText("属性尚未在故事中确认")).toBeTruthy();
  expect(screen.queryByText("生命：0")).toBeNull();
});

it("shows only recorded tasks and completed milestones in separate panels", () => {
  const changed = {
    ...view,
    status: {
      ...view.status,
      tasks: [
        {
          name: "办理入学",
          status: "completed",
          description: "取得学院资格",
          progress: "登记与住宿已完成",
        },
      ],
      milestones: [{ name: "独自入学", description: "选择工读路线" }],
    },
    latest_progress: { panels: ["任务", "世界线"] },
    journey: [{ turn: 1, message_id: "2-gm", events: ["工读生资格已经确认"] }],
  };
  render(<InformationPanel view={changed} onRead={vi.fn()} />);
  fireEvent.click(screen.getByRole("tab", { name: /任务/ }));
  expect(screen.getByText("办理入学")).toBeTruthy();
  expect(screen.getByText("已完成")).toBeTruthy();
  expect(screen.getByText("登记与住宿已完成")).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: /世界线/ }));
  expect(screen.getByText("独自入学 · 选择工读路线")).toBeTruthy();
  expect(screen.getByText("工读生资格已经确认")).toBeTruthy();
});

it("keeps the committed goal visible while a long-running task retains its prior record", () => {
  render(
    <InformationPanel
      view={{
        ...view,
        status: {
          ...view.status,
          objective: "携带推荐信前往学院",
          tasks: [
            { name: "求学", status: "active", progress: "待领取推荐信" },
            {
              name: "当前目标",
              status: "active",
              description: "携带推荐信前往学院",
            },
          ],
        },
      }}
      onRead={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("tab", { name: "任务" }));
  expect(screen.getByText("当前推进")).toBeTruthy();
  expect(screen.getAllByText("携带推荐信前往学院")).toHaveLength(1);
  expect(screen.getByText("求学")).toBeTruthy();
  expect(screen.getByText("最近记录")).toBeTruthy();
});

it("keeps the round being read when streaming finishes and a new round is saved", async () => {
  let resolve;
  window.api.player.execute.mockImplementation(() => ({
    done: new Promise((r) => {
      resolve = r;
    }),
  }));
  render(<Reader {...props} />);
  const choice = await screen.findByRole("button", { name: "A 向村长问路" });
  await waitFor(() => expect(choice.disabled).toBe(false));
  fireEvent.click(choice);
  fireEvent.click(screen.getByRole("button", { name: "上一回合" }));
  expect(screen.getByText("你站在旧桥前。")).toBeTruthy();
  await act(async () =>
    window.api.player.execute.mock.calls[0][1].on_token({
      text: "你认识了村长。",
    }),
  );
  window.api.player.save.mockResolvedValue({
    ...view,
    messages: [
      ...view.messages,
      { id: "3-gm", role: "assistant", turn: 3, text: "你认识了村长。" },
    ],
  });
  window.api.player.request.mockResolvedValue({
    status: "settled",
    receipt: { saved: true },
  });
  await act(async () => resolve());
  expect(screen.getByText("你站在旧桥前。")).toBeTruthy();
  expect(screen.queryByText("你认识了村长。")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "回到当前回合" }));
  expect(screen.getByText("你认识了村长。")).toBeTruthy();
});

it("quotes a read-only consultation, preserves the response and fills suggestions without sending", async () => {
  let resolve;
  window.api.player.execute.mockImplementation(() => ({
    done: new Promise((r) => {
      resolve = r;
    }),
  }));
  const onUse = vi.fn(),
    onBusy = vi.fn(),
    refreshWallet = vi.fn().mockResolvedValue(undefined);
  render(
    <Assistant
      uid={1}
      saveId={9}
      name="旅人"
      gameBusy={false}
      onBusy={onBusy}
      onUse={onUse}
      refreshWallet={refreshWallet}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "打开游玩助手" }));
  fireEvent.change(screen.getByLabelText("向游玩助手提问"), {
    target: { value: "下一步呢？" },
  });
  await screen.findByText(/预计 1.00/);
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  const request = window.api.player.execute.mock.calls[0][0];
  expect(request.kind).toBe("guide");
  expect(request.reveal_future).toBe(false);
  expect(onBusy).toHaveBeenCalledWith(true);
  const receipt = {
    request_id: request.request_id,
    text: "先确认道路情况。",
    question: "下一步呢？",
    options: ["向村长问路"],
    charged_micro: 300000,
    input_tokens: 100,
    output_tokens: 50,
    rate_version: 1,
  };
  window.api.player.request.mockResolvedValue({ status: "settled", receipt });
  window.api.player.guideHistory.mockResolvedValue({ items: [receipt] });
  await act(async () => resolve());
  expect(await screen.findByText("先确认道路情况。")).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "填入行动框 · 向村长问路" }),
  );
  expect(onUse).toHaveBeenCalledWith("向村长问路");
  expect(window.api.player.execute).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem("player-guide-request-1-9")).toBeNull();
});

it("requotes future disclosure and resets permission after sending even when released", async () => {
  let resolve;
  window.api.player.execute.mockImplementation(() => ({
    done: new Promise((r) => { resolve = r; }),
  }));
  render(
    <Assistant uid={1} saveId={9} name="旅人" gameBusy={false}
      onBusy={vi.fn()} onUse={vi.fn()} refreshWallet={vi.fn().mockResolvedValue(undefined)} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "打开游玩助手" }));
  const permission = screen.getByRole("checkbox", { name: "本次揭示未来" });
  expect(permission.checked).toBe(false);
  fireEvent.change(screen.getByLabelText("向游玩助手提问"), { target: { value: "尧山之后如何？" } });
  await screen.findByText(/预计 1.00/);
  expect(window.api.player.quote).toHaveBeenLastCalledWith({
    save_id: 9, kind: "guide", message: "尧山之后如何？", reveal_future: false,
  });
  fireEvent.click(permission);
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(window.api.player.execute).not.toHaveBeenCalled();
  await screen.findByText(/预计 1.00/);
  expect(window.api.player.quote).toHaveBeenLastCalledWith({
    save_id: 9, kind: "guide", message: "尧山之后如何？", reveal_future: true,
  });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(window.api.player.execute.mock.calls[0][0].reveal_future).toBe(true);
  expect(permission.checked).toBe(false);
  expect(permission.disabled).toBe(true);
  expect(JSON.parse(localStorage.getItem("player-guide-request-1-9")).reveal_future).toBe(true);
  window.api.player.request.mockResolvedValue({ status: "released" });
  await act(async () => resolve());
  expect(await screen.findByText(/咨询未完成/)).toBeTruthy();
  await screen.findByText(/预计 1.00/);
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(window.api.player.execute.mock.calls[1][0].reveal_future).toBe(false);
});
