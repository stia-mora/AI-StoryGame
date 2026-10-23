import React from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Wallet } from "../player/Wallet.jsx";

const row = (id, reason) => ({ id, kind: "grant", reason, free_delta: 0, permanent_delta: 1000000, held_delta: 0, created_at: "2026-10-23T00:30:00Z" });
beforeEach(() => {
  window.api = { player: {
    wallet: vi.fn().mockResolvedValue({ free_micro: 10000000, permanent_micro: 20000000, held_micro: 0, rates: { input: 1, output: 2 } }),
    ledger: vi.fn(({ page }) => Promise.resolve({ items: [row(page, `第${page}页记录`)], page, pages: 3, total: 21 })),
    redeem: vi.fn().mockResolvedValue({}),
  } };
});
const show = () => render(<Wallet refresh={vi.fn()} navigate={vi.fn()} />);

it("replaces the current page instead of appending records", async () => {
  show();
  await screen.findByText("第1页记录");
  fireEvent.click(screen.getByRole("button", { name: "第 2 页", exact: true }));
  expect(await screen.findByText("第2页记录")).toBeTruthy();
  expect(screen.queryByText("第1页记录")).toBeNull();
  expect(window.api.player.ledger).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, page_size: 10 }));
});

it("queries all records with server filters and returns to page one", async () => {
  show(); await screen.findByText("第1页记录");
  fireEvent.click(screen.getByRole("button", { name: "下一页明细" }));
  await screen.findByText("第2页记录");
  fireEvent.change(screen.getByLabelText("查询积分明细"), { target: { value: "  霍金斯  " } });
  fireEvent.change(screen.getByLabelText("变动类型"), { target: { value: "settle" } });
  fireEvent.change(screen.getByLabelText("开始日期"), { target: { value: "2026-10-01" } });
  fireEvent.click(screen.getByRole("button", { name: "查询", exact: true }));
  await waitFor(() => expect(window.api.player.ledger).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, q: "霍金斯", kind: "settle", date_from: "2026-10-01" })));
  fireEvent.click(screen.getByRole("button", { name: "重置" }));
  await waitFor(() => expect(window.api.player.ledger).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, q: "", kind: "", date_from: "" })));
});

it("does not let an older request replace newer filtered results", async () => {
  show(); await screen.findByText("第1页记录");
  let finishOld;
  window.api.player.ledger.mockImplementation(({ q }) => q === "旧" ? new Promise((resolve) => { finishOld = resolve; }) : Promise.resolve({ items: [row(99, "最新结果")], page: 1, pages: 1, total: 1 }));
  fireEvent.change(screen.getByLabelText("查询积分明细"), { target: { value: "旧" } });
  fireEvent.click(screen.getByRole("button", { name: "查询", exact: true }));
  fireEvent.change(screen.getByLabelText("查询积分明细"), { target: { value: "新" } });
  fireEvent.click(screen.getByRole("button", { name: "查询", exact: true }));
  await screen.findByText("最新结果");
  await act(async () => finishOld({ items: [row(1, "过时结果")], page: 1, pages: 1, total: 1 }));
  expect(screen.queryByText("过时结果")).toBeNull();
});

it("keeps filters visible after failure and retries the same query", async () => {
  show(); await screen.findByText("第1页记录");
  window.api.player.ledger.mockRejectedValueOnce(new Error("连接失败"));
  fireEvent.click(screen.getByRole("button", { name: "查询", exact: true }));
  expect(await screen.findByRole("alert")).toHaveTextContent("连接失败");
  fireEvent.click(screen.getByRole("button", { name: "重试明细查询" }));
  expect(await screen.findByText("第1页记录")).toBeTruthy();
});
