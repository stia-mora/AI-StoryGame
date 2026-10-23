import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useComposerKeys } from "../player/useComposerKeys.js";
import { useReadingScroll } from "../player/useReadingScroll.js";
import { useWorkspaceSplit } from "../player/useWorkspaceSplit.js";

beforeEach(() => { localStorage.clear(); vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

function Composer({ send }) {
  return <textarea aria-label="行动" {...useComposerKeys(send)} />;
}

it("blocks composition, legacy 229 and trailing Enter for 500ms without consuming candidate selection", () => {
  const send = vi.fn();
  render(<Composer send={send} />);
  const input = screen.getByLabelText("行动");
  fireEvent.keyDown(input, { key: "Enter", ctrlKey: true, isComposing: true });
  fireEvent.keyDown(input, { key: "Enter", metaKey: true, keyCode: 229 });
  fireEvent.compositionStart(input);
  expect(fireEvent.keyDown(input, { key: "Enter", ctrlKey: true })).toBe(true);
  fireEvent.compositionEnd(input);
  expect(fireEvent.keyDown(input, { key: "Enter", ctrlKey: true })).toBe(false);
  act(() => vi.advanceTimersByTime(499));
  fireEvent.keyDown(input, { key: "Enter", metaKey: true });
  expect(send).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(1));
  fireEvent.keyDown(input, { key: "Enter", metaKey: true });
  expect(send).toHaveBeenCalledTimes(1);
  fireEvent.keyDown(input, { key: "Enter" });
  expect(send).toHaveBeenCalledTimes(1);
  fireEvent.compositionStart(input);
  fireEvent.compositionEnd(input);
  fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
  expect(send).toHaveBeenCalledTimes(1);
});

function Reading({ text, enabled = true, visible = true }) {
  const { bindScroller, away, jump, scrollEvents } = useReadingScroll(text, enabled, visible ? "story" : "state");
  return <><div aria-label="正文" ref={bindScroller} {...scrollEvents}>{text}<button>选项</button></div>{away && <button onClick={jump}>跳至最新</button>}</>;
}

function geometry(node, height = 1000, top = 760) {
  const dimensions = { height, top };
  Object.defineProperties(node, {
    scrollHeight: { configurable: true, get: () => dimensions.height },
    clientHeight: { configurable: true, get: () => 200 },
    scrollTop: { configurable: true, get: () => dimensions.top, set: (value) => { dimensions.top = Math.max(0, Math.min(value, dimensions.height - 200)); } },
  });
  return dimensions;
}

it("follows only inside 40px and shows the latest button only beyond 120px", () => {
  const { rerender } = render(<Reading text="一" />);
  const node = screen.getByLabelText("正文"), dimensions = geometry(node);
  fireEvent.scroll(node);
  fireEvent.pointerDown(screen.getByRole("button", { name: "选项" }));
  dimensions.height = 1100;
  rerender(<Reading text="一二" />);
  expect(node.scrollTop).toBe(900);
  node.scrollTop = 859; // 41px away, following must stop.
  fireEvent.scroll(node);
  dimensions.height = 1120;
  rerender(<Reading text="一二三" />);
  expect(node.scrollTop).toBe(859);
  node.scrollTop = 800; // Exactly 120px is not away.
  fireEvent.scroll(node);
  expect(screen.queryByRole("button", { name: "跳至最新" })).toBeNull();
  node.scrollTop = 799;
  fireEvent.scroll(node);
  expect(screen.getByRole("button", { name: "跳至最新" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "跳至最新" }));
  expect(node.scrollTop).toBe(920);
  expect(screen.queryByRole("button", { name: "跳至最新" })).toBeNull();
});

it("interrupts on wheel, touch and keyboard before a scroll event and retains the position through final save", () => {
  const { rerender } = render(<Reading text="一" />);
  const node = screen.getByLabelText("正文"), dimensions = geometry(node, 1000, 780);
  fireEvent.scroll(node);
  fireEvent.wheel(node, { deltaY: -1 });
  dimensions.height = 1020;
  rerender(<Reading text="一二" />);
  expect(node.scrollTop).toBe(780);
  fireEvent.scroll(node); // Still within 40px, but deliberate reading stays detached.
  dimensions.height = 1040;
  rerender(<Reading text="一二三" />);
  expect(node.scrollTop).toBe(780);
  node.scrollTop = 840;
  fireEvent.scroll(node); // Deliberately reach the bottom to resume.
  dimensions.height = 1060;
  rerender(<Reading text="一二三四" />);
  expect(node.scrollTop).toBe(860);
  fireEvent.touchMove(node);
  dimensions.height = 1080;
  rerender(<Reading text="一二三四五" />);
  expect(node.scrollTop).toBe(860);
  fireEvent.keyDown(node, { key: "PageUp" });
  dimensions.height = 1200;
  rerender(<Reading text="已保存的完整正文" enabled={false} />);
  expect(node.scrollTop).toBe(860);
  expect(screen.getByRole("button", { name: "跳至最新" })).toBeTruthy();
});

it("does not pull an initially distant reader or a hidden mobile reading area to the bottom", () => {
  const { rerender } = render(<Reading text="已保存" enabled={false} />);
  const node = screen.getByLabelText("正文"), dimensions = geometry(node, 1000, 100);
  rerender(<Reading text="已保存的正文" enabled={false} />);
  rerender(<Reading text="新回合" />);
  expect(node.scrollTop).toBe(100);
  node.checkVisibility = () => false;
  dimensions.height = 1200;
  rerender(<Reading text="在其他视图时生成的内容" />);
  expect(node.scrollTop).toBe(100);
});

it("refreshes the latest affordance on returning to a hidden conversation without moving its scroll position", () => {
  const { rerender } = render(<Reading text="一" />);
  const node = screen.getByLabelText("正文"), dimensions = geometry(node, 1000, 800);
  fireEvent.scroll(node);
  node.checkVisibility = () => false;
  rerender(<Reading text="一" visible={false} />);
  dimensions.height = 1500;
  rerender(<Reading text="一二三" visible={false} />);
  node.checkVisibility = () => true;
  rerender(<Reading text="一二三" visible />);
  expect(node.scrollTop).toBe(800);
  expect(screen.getByRole("button", { name: "跳至最新" })).toBeTruthy();
});

it("does not interpret keyboard activation of an action as scrolling the conversation", () => {
  const { rerender } = render(<Reading text="一" />);
  const node = screen.getByLabelText("正文"), dimensions = geometry(node, 1000, 800);
  fireEvent.scroll(node);
  fireEvent.keyDown(screen.getByRole("button", { name: "选项" }), { key: " " });
  dimensions.height = 1100;
  rerender(<Reading text="一二" />);
  expect(node.scrollTop).toBe(900);
});

it("rechecks distance after a layout resize without moving the reader or rearming following", () => {
  const observers = [];
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback) { this.notify = callback; this.observe = vi.fn(); this.disconnect = vi.fn(); observers.push(this); }
  });
  const { rerender, unmount } = render(<Reading text="一" />);
  const node = screen.getByLabelText("正文"), dimensions = geometry(node, 1000, 800);
  fireEvent.scroll(node);
  dimensions.height = 1500;
  act(() => observers.at(-1).notify());
  expect(screen.getByRole("button", { name: "跳至最新" })).toBeTruthy();
  expect(node.scrollTop).toBe(800);
  dimensions.height = 1600;
  rerender(<Reading text="一二" />);
  expect(node.scrollTop).toBe(800);
  unmount();
  expect(observers.at(-1).disconnect).toHaveBeenCalledOnce();
});

it("subscribes to layout changes when an initially empty reader mounts after loading", () => {
  const observed = [];
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback) { this.notify = callback; }
    observe(node) { observed.push(node); }
    disconnect() {}
  });
  function LoadingReader({ ready }) {
    const { bindScroller } = useReadingScroll("", false);
    return ready ? <div ref={bindScroller} aria-label="空正文" /> : <p>加载中</p>;
  }
  const { rerender } = render(<LoadingReader ready={false} />);
  expect(observed).toHaveLength(0);
  rerender(<LoadingReader ready />);
  expect(observed).toEqual([screen.getByLabelText("空正文")]);
});

function Split() {
  const split = useWorkspaceSplit(1);
  return <div ref={split.panes} data-testid="panes" data-ratio={split.ratio ?? "default"} data-collapsed={split.collapsed}>
    <section className="workspace-center" />
    <div {...split.handleProps} />
    <aside>{split.dragging && <div data-testid="shield" />}</aside>
    <button onClick={split.toggle}>切换状态</button>
  </div>;
}

function pointerSupport() {
  vi.stubGlobal("PointerEvent", class extends MouseEvent {
    constructor(type, init = {}) { super(type, init); Object.defineProperty(this, "pointerId", { value: init.pointerId ?? 1 }); }
  });
}

it("shields the preview during drag, collapses beyond 82% and Escape restores the original ratio", () => {
  pointerSupport();
  render(<Split />);
  const panes = screen.getByTestId("panes"), handle = screen.getByRole("separator");
  panes.getBoundingClientRect = () => ({ left: 100, width: 1014 });
  fireEvent.doubleClick(handle);
  fireEvent.pointerDown(handle, { button: 0, pointerId: 1 });
  expect(screen.getByTestId("shield")).toBeTruthy();
  fireEvent.pointerMove(window, { pointerId: 2, clientX: 1050 });
  expect(panes.dataset.ratio).toBe("50");
  fireEvent.pointerMove(window, { pointerId: 1, clientX: 930 });
  expect(panes.dataset.collapsed).toBe("true");
  fireEvent.keyDown(window, { key: "Escape" });
  expect(panes.dataset.ratio).toBe("50");
  expect(panes.dataset.collapsed).toBe("false");
  expect(screen.queryByTestId("shield")).toBeNull();
  fireEvent.pointerUp(window, { pointerId: 1 });
  expect(JSON.parse(localStorage.getItem("player-split-1"))).toBe(50);
});

it("commits and restores proportions, supports keyboard resizing and cancels lost pointer gestures", () => {
  pointerSupport();
  const first = render(<Split />);
  const panes = screen.getByTestId("panes"), handle = screen.getByRole("separator");
  panes.getBoundingClientRect = () => ({ left: 0, width: 1014 });
  fireEvent.pointerDown(handle, { button: 0, pointerId: 1 });
  fireEvent.pointerMove(window, { pointerId: 1, clientX: 700 });
  fireEvent.pointerUp(window, { pointerId: 1 });
  expect(panes.dataset.ratio).toBe("70");
  first.unmount();
  render(<Split />);
  expect(screen.getByTestId("panes").dataset.ratio).toBe("70");
  const next = screen.getByRole("separator");
  fireEvent.keyDown(next, { key: "ArrowRight" });
  expect(next.getAttribute("aria-valuenow")).toBe("72");
  fireEvent.keyDown(next, { key: "End" });
  expect(screen.getByTestId("panes").dataset.collapsed).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "切换状态" }));
  expect(next.getAttribute("aria-valuenow")).toBe("50");
  screen.getByTestId("panes").getBoundingClientRect = () => ({ left: 0, width: 1014 });
  fireEvent.pointerDown(next, { button: 0, pointerId: 1 });
  fireEvent.pointerMove(window, { pointerId: 1, clientX: 800 });
  fireEvent.pointerCancel(window, { pointerId: 1 });
  expect(next.getAttribute("aria-valuenow")).toBe("50");
  expect(screen.queryByTestId("shield")).toBeNull();
});

it("keeps the divider stationary on the first pointer event and cancels a resize when the viewport changes", () => {
  pointerSupport();
  render(<Split />);
  const panes = screen.getByTestId("panes"), handle = screen.getByRole("separator");
  panes.getBoundingClientRect = () => ({ left: 100, width: 1014 });
  panes.querySelector(".workspace-center").getBoundingClientRect = () => ({ width: 500 });
  fireEvent.doubleClick(handle);
  fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 607 });
  fireEvent.pointerMove(window, { pointerId: 1, clientX: 607 });
  expect(panes.dataset.ratio).toBe("50");
  fireEvent.pointerMove(window, { pointerId: 1, clientX: 707 });
  expect(panes.dataset.ratio).toBe("60");
  fireEvent(window, new Event("resize"));
  expect(panes.dataset.ratio).toBe("50");
  expect(screen.queryByTestId("shield")).toBeNull();
});
