import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { GenerationProgress } from "../player/GenerationProgress.jsx";

afterEach(() => vi.useRealTimers());

it("uses recent observed durations for a qualified remaining-time range, then reports an overrun", () => {
  vi.useFakeTimers(); vi.setSystemTime(1000000);
  render(<GenerationProgress phase="generating" startedAt={940000} timing={{ samples: 3, low_seconds: 180, high_seconds: 300, median_seconds: 240 }} />);
  expect(screen.getByText(/剩余参考约 2 分钟–4 分钟/)).toBeTruthy();
  expect(screen.getByText(/依据本存档同模型近期 3 次记录/)).toBeTruthy();
  act(() => vi.advanceTimersByTime(241000));
  expect(screen.getByText(/已超过近期参考用时/)).toBeTruthy();
  expect(screen.getByRole("timer")).toHaveTextContent("5:01");
});

it("shows elapsed time and actual stages without an invented percentage or ETA", () => {
  vi.useFakeTimers();
  vi.setSystemTime(1000000);
  const { rerender } = render(<GenerationProgress phase="understanding" startedAt={Date.now()} confirmedAt={Date.now()} />);
  expect(screen.getByText("理解行动").getAttribute("aria-current")).toBe("step");
  act(() => vi.advanceTimersByTime(185000));
  expect(screen.getByRole("timer")).toHaveTextContent("已等待 3:05");
  expect(screen.getByText(/剩余时间暂无法准确估算/)).toBeTruthy();
  rerender(<GenerationProgress phase="saving" startedAt={1000000} confirmedAt={Date.now()} />);
  expect(screen.getByText("保存结算").getAttribute("aria-current")).toBe("step");
  expect(screen.queryByRole("progressbar")).toBeNull();
});

it("resumes the original elapsed time and clears its timer on unmount", () => {
  vi.useFakeTimers();
  vi.setSystemTime(1000000);
  const { unmount } = render(<GenerationProgress phase="retrieving" startedAt={880000} opening />);
  expect(screen.getByRole("timer")).toHaveTextContent("已等待 2:00");
  expect(screen.getByText("准备开场")).toBeTruthy();
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});
