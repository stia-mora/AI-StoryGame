import React from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { InformationPanel } from "../player/WorkspacePanels.jsx";
import { stateUpdates } from "../player/stateUpdates.js";

const progress = {
  gains: [{ kind: "物品", text: "学院推荐信" }, { kind: "能力", text: "辨认足迹" }],
  losses: [{ kind: "资源", text: "铜币：2" }],
  changes: [
    { kind: "地点", before: "村口", after: "学院门前" },
    { kind: "生命", before: "10", after: "9" },
    { kind: "人物关系", before: "", after: "村长 · 信任" },
    { kind: "任务", before: "入学 · 进行中", after: "入学 · 已完成" },
    { kind: "关键节点", before: "", after: "取得学院资格" },
  ],
  events: ["工读生登记已经开放"],
};
const view = {
  save: { id: 9, turn: 2 },
  status: { name: "旅人", attributes: [{ name: "生命", value: 9 }], inventory: ["学院推荐信"] },
  messages: [{ id: "32-gm", turn: 2, role: "assistant", progress }],
  latest_progress: progress,
  journey: [{ message_id: "31-gm", turn: 1, gains: [{ kind: "物品", text: "地图" }] }],
};
beforeEach(() => { localStorage.clear(); vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it("groups actual gains, losses and before/after changes by panel and round without duplicate latest entries", () => {
  const updates = stateUpdates(view);
  expect(updates.inventory.map((round) => round.turn)).toEqual([2, 1]);
  expect(updates.inventory[0].entries.map((entry) => entry.after)).toEqual(["学院推荐信", "铜币：2"]);
  expect(updates.character[0].entries).toContainEqual({ label: "生命", before: "10", after: "9" });
  expect(updates.tasks[0].entries).toContainEqual({ label: "任务", before: "入学 · 进行中", after: "入学 · 已完成" });
  expect(updates.overview[0].entries).toContainEqual({ label: "已知事件", after: "工读生登记已经开放" });
});

it("opens a concrete tooltip with hover, keyboard or touch and dismisses it with Escape or an outside press", () => {
  render(<InformationPanel uid={1} view={view} onRead={vi.fn()} />);
  const inventory = screen.getByRole("tab", { name: "背包" });
  fireEvent.mouseEnter(inventory);
  const tooltip = screen.getByRole("tooltip");
  expect(inventory.getAttribute("aria-describedby")).toBe(tooltip.id);
  expect(within(tooltip).getByText("第 2 回合")).toBeTruthy();
  expect(within(tooltip).getByText("第 1 回合")).toBeTruthy();
  expect(within(tooltip).getByText("铜币：2")).toBeTruthy();
  fireEvent.keyDown(inventory, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.click(inventory);
  fireEvent.focus(screen.getByRole("button", { name: /回合有未读变化/ }));
  fireEvent.click(screen.getByRole("button", { name: /回合有未读变化/ }));
  expect(screen.getByRole("tooltip")).toBeTruthy();
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.focus(screen.getByRole("tab", { name: "角色" }));
  expect(within(screen.getByRole("tooltip")).getByText("10").tagName).toBe("DEL");
  expect(within(screen.getByRole("tooltip")).getByText("9")).toBeTruthy();
});

it("keeps long updates unread until their end, then persists read state per account and save", () => {
  const first = render(<InformationPanel uid={1} view={view} onRead={vi.fn()} />);
  const panel = screen.getByRole("tabpanel");
  Object.defineProperties(panel, { scrollHeight: { configurable: true, value: 1000 }, clientHeight: { configurable: true, value: 200 } });
  const inventory = screen.getByRole("tab", { name: "背包" });
  fireEvent.click(inventory);
  const tooltip = screen.getByRole("tooltip");
  Object.defineProperties(tooltip, { scrollHeight: { configurable: true, value: 1000 }, clientHeight: { configurable: true, value: 200 } });
  act(() => vi.advanceTimersByTime(800));
  expect(inventory.querySelector(".workspace-tab-change")).toBeTruthy();
  panel.scrollTop = 700;
  fireEvent.scroll(panel);
  expect(inventory.querySelector(".workspace-tab-change")).toBeTruthy();
  panel.scrollTop = 800;
  fireEvent.scroll(panel);
  expect(inventory.querySelector(".workspace-tab-change")).toBeNull();
  first.unmount();
  const second = render(<InformationPanel uid={1} view={view} onRead={vi.fn()} />);
  expect(screen.getByRole("tab", { name: "背包" }).querySelector(".workspace-tab-change")).toBeNull();
  second.unmount();
  render(<InformationPanel uid={2} view={view} onRead={vi.fn()} />);
  expect(screen.getByRole("tab", { name: "背包" }).querySelector(".workspace-tab-change")).toBeTruthy();
});

it("clears the aggregate dot only after all six panels are read, and a new round raises only its changed panels", () => {
  const onUnreadChange = vi.fn();
  const { rerender } = render(<InformationPanel uid={1} view={view} onRead={vi.fn()} onUnreadChange={onUnreadChange} />);
  expect(onUnreadChange).toHaveBeenLastCalledWith(6);
  for (const title of ["局势", "角色", "背包", "人物", "任务", "世界线"]) {
    fireEvent.click(screen.getByRole("tab", { name: title }));
    act(() => vi.advanceTimersByTime(20));
  }
  expect(onUnreadChange).toHaveBeenLastCalledWith(0);
  const next = { ...view, save: { ...view.save, turn: 3 }, latest_progress: { gains: [{ kind: "物品", text: "宿舍钥匙" }] }, messages: [...view.messages, { id: "33-gm", turn: 3, role: "assistant" }] };
  rerender(<InformationPanel uid={1} view={next} onRead={vi.fn()} onUnreadChange={onUnreadChange} />);
  expect(onUnreadChange).toHaveBeenLastCalledWith(1);
  expect(screen.getByRole("tab", { name: "背包" }).querySelector(".workspace-tab-change")).toBeTruthy();
  expect(screen.getByRole("tab", { name: "角色" }).querySelector(".workspace-tab-change")).toBeNull();
});

it("does not acknowledge a later round through an older open tooltip or a hidden mobile panel", () => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  const { rerender } = render(<InformationPanel uid={1} active={false} view={view} onRead={vi.fn()} />);
  fireEvent.mouseEnter(screen.getByRole("tab", { name: "背包" }));
  act(() => vi.advanceTimersByTime(800));
  expect(localStorage.getItem("player-state-read-1-9")).toBeNull();
  rerender(<InformationPanel uid={1} active view={view} onRead={vi.fn()} />);
  const next = { ...view, save: { ...view.save, turn: 3 }, latest_progress: { gains: [{ kind: "物品", text: "宿舍钥匙" }] }, messages: [...view.messages, { id: "33-gm", turn: 3, role: "assistant" }] };
  rerender(<InformationPanel uid={1} active view={next} onRead={vi.fn()} />);
  act(() => vi.advanceTimersByTime(800));
  expect(JSON.parse(localStorage.getItem("player-state-read-1-9")).inventory).toBe(32);
  expect(screen.getByRole("tab", { name: "背包" }).querySelector(".workspace-tab-change")).toBeTruthy();
});
