import React from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Authoring, AuthoringAdmin } from "../player/Authoring.jsx";

const revision = {
  id: 9, version: 2, fingerprint: "abcdef012345", rights_note: "", reviewed_at: null,
  report: { valid: true, checks: { playtest: "not_run" } }, playtests: [],
  contract: { play: { identities: [{ id: "keeper", name: "守灯人" }] }, completeness: { unresolved: ["核对结局"] } },
};
const draft = { project: { id: "project-1", title: "灯火", version: 2 }, revisions: [revision], jobs: [], submissions: [] };
beforeEach(() => {
  history.replaceState({}, "", "/play/authoring?project=project-1");
  window.api = { federation: { patList: vi.fn().mockResolvedValue({ items: [] }), patCreate: vi.fn(), patRevoke: vi.fn() } };
  vi.stubGlobal("fetch", vi.fn(async (path, options) => {
    const body = options?.body ? JSON.parse(options.body) : {};
    let value = {};
    if (path === "/api/authoring") value = { wallet: { preview_micro: 10000000000 }, author: "测试作者", projects: [draft.project], ledger: [], scopes: ["authoring:read"], endpoint: "https://example.com/mcp/authoring" };
    if (path.endsWith("/get_draft")) value = draft;
    if (path.endsWith("/preview")) value = { url: "/play/saves/42" };
    if (path === "/api/authoring/admin") value = { config: { preview_profile_id: 1 }, profiles: [{ id: 1, name: "服务模型", enabled: true }], submissions: [{ id: "submission-1", title: "灯火", version: 2, status: "pending_review", report: {} }] };
    if (path.includes("/submissions/")) value = { chapters: [{ chapter_index: 1, title: "灯火初见", content: "原创章节正文" }], offset: 0, contract: {}, playtests: [] };
    return { ok: true, json: async () => value, body };
  }));
});

it("opens the linked private draft and binds free preview creation to its version and identity", async () => {
  const navigate = vi.fn();
  render(<Authoring navigate={navigate} />);
  expect(await screen.findByText("作者：测试作者")).toBeTruthy();
  expect(await screen.findByText("待办：核对结局")).toBeTruthy();
  expect(screen.getByRole("button", { name: "提交上架审批" }).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "免费创建试玩存档" }));
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("/play/saves/42"));
  const call = fetch.mock.calls.find(([path]) => path.endsWith("/preview"));
  expect(JSON.parse(call[1].body)).toMatchObject({ mode: "create", revision_id: 9, identity_id: "keeper" });
});

it("shows a recoverable API error and preserves entered rights notes", async () => {
  render(<Authoring navigate={vi.fn()} />);
  const field = await screen.findByLabelText("来源与授权说明");
  fireEvent.change(field, { target: { value: "本人原创" } });
  fetch.mockImplementationOnce(async () => ({ ok: false, json: async () => ({ detail: "网络中断，请重试" }) }));
  fireEvent.click(screen.getByRole("button", { name: "确认已复核此版本" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("网络中断，请重试");
  expect(field.value).toBe("本人原创");
});

it("gives administrators chapter inspection and purpose-specific redemption codes", async () => {
  render(<AuthoringAdmin navigate={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "审阅内容与试玩记录" }));
  expect(await screen.findByText("原创章节正文")).toBeTruthy();
  expect(screen.getByRole("button", { name: "拒绝" }).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "生成兑换码" }));
  await waitFor(() => expect(fetch.mock.calls.some(([path, options]) => path === "/api/admin/player/codes" && JSON.parse(options.body).purpose === "preview")).toBe(true));
});
