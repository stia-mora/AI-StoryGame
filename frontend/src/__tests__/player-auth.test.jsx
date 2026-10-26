import React from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PlayerApp } from "../player/PlayerApp.jsx";

const schema = {
  login: [
    { key: "username", label: "用户名", required: true },
    { key: "password", label: "密码", type: "password", required: true, min_length: 8 },
  ],
  register: [
    { key: "username", label: "用户名", required: true },
    { key: "email", label: "邮箱", type: "email", required: true },
    { key: "password", label: "密码", type: "password", required: true, min_length: 8 },
    { key: "age_confirmed", label: "我已年满18岁", type: "boolean", required: true },
  ],
  notes: {},
};

beforeEach(() => {
  history.replaceState({}, "", "/play/login");
  window.scrollTo = vi.fn();
  window.api = {
    auth: {
      me: vi.fn().mockResolvedValue({ user: null }),
      login: vi.fn().mockRejectedValue(new Error("密码不正确")),
      loginCodeRequest: vi.fn().mockResolvedValue({ ok: true, email_mask: "r***@example.com" }),
    },
    player: {
      session: vi.fn().mockResolvedValue({ authenticated: false }),
      catalog: vi.fn().mockResolvedValue({ stories: [] }),
    },
  };
  window.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => schema });
});

it("opens login inside the player shell without depending on the story service", async () => {
  render(<PlayerApp />);
  expect(await screen.findByLabelText(/用户名/)).toBeTruthy();
  expect(screen.getByRole("heading", { name: "登录故事之间" })).toBeTruthy();
  expect(window.api.player.session).not.toHaveBeenCalled();
  expect(screen.queryByRole("link", { name: "创作工作台" })).toBeNull();
  fireEvent.change(screen.getByLabelText(/用户名/), { target: { value: "reader" } });
  fireEvent.change(screen.getByLabelText(/^密码/), { target: { value: "wrong-password" } });
  fireEvent.click(screen.getByRole("button", { name: "登录", exact: true }));
  expect(await screen.findByRole("alert")).toHaveTextContent("密码不正确");
  expect(window.api.auth.login).toHaveBeenCalledWith({ username: "reader", password: "wrong-password" });
  expect(location.pathname).toBe("/play/login");
});

it("opens registration with the existing consent validation and email verification", async () => {
  history.replaceState({}, "", "/play/register");
  render(<PlayerApp />);
  const age = await screen.findByLabelText(/我已年满18岁/);
  fireEvent.change(screen.getByLabelText(/用户名/), { target: { value: "reader" } });
  fireEvent.change(screen.getByLabelText(/邮箱/), { target: { value: "reader@example.com" } });
  fireEvent.change(screen.getByLabelText(/^密码/), { target: { value: "new-password" } });
  fireEvent.click(screen.getByRole("button", { name: "创建账号" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("18");
  expect(window.fetch).toHaveBeenCalledTimes(1);
  fireEvent.click(age);
  window.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true, email_mask: "r***@example.com" }) });
  fireEvent.click(screen.getByRole("button", { name: "创建账号" }));
  expect(await screen.findByRole("textbox", { name: /验证码/ })).toBeTruthy();
  expect(window.fetch).toHaveBeenLastCalledWith(expect.stringContaining("/auth/register"), expect.objectContaining({
    body: JSON.stringify({ username: "reader", email: "reader@example.com", password: "new-password", age_confirmed: true }),
  }));
});

it("keeps registration policy when opening the registration URL directly", async () => {
  history.replaceState({}, "", "/play/register");
  window.fetch.mockResolvedValue({ ok: true, json: async () => ({ ...schema, notes: { registration_closed: true } }) });
  render(<PlayerApp />);
  await screen.findByLabelText(/用户名/);
  expect(screen.getByRole("tab", { name: "注册" })).toBeDisabled();
  expect(screen.getByRole("tab", { name: "登录", exact: true })).toHaveAttribute("aria-selected", "true");
  expect(screen.queryByLabelText("邮箱")).toBeNull();
});

it("uses the existing code login flow in the player layout", async () => {
  render(<PlayerApp />);
  fireEvent.click(await screen.findByRole("tab", { name: /验证码/ }));
  fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "reader@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: /发送验证码/ }));
  expect(await screen.findByRole("textbox", { name: /验证码/ })).toBeTruthy();
  expect(window.api.auth.loginCodeRequest).toHaveBeenCalledWith({ email: "reader@example.com" });
});

it("opens password recovery without submitting the filled login form", async () => {
  render(<PlayerApp />);
  fireEvent.change(await screen.findByLabelText(/用户名/), { target: { value: "reader" } });
  fireEvent.change(screen.getByLabelText(/^密码/), { target: { value: "old-password" } });
  const forgot = screen.getByRole("button", { name: "忘记密码" });
  expect(forgot).toHaveAttribute("type", "button");
  fireEvent.click(forgot);
  expect(await screen.findByLabelText("注册邮箱")).toBeTruthy();
  expect(window.api.auth.login).not.toHaveBeenCalled();
});

it("keeps reset tokens in legacy email links and bypasses the existing-session redirect", async () => {
  history.replaceState({}, "", "/Login.html#reset?token=test-token");
  render(<PlayerApp />);
  expect(await screen.findByLabelText("新密码")).toBeTruthy();
  expect(window.api.auth.me).not.toHaveBeenCalled();
  expect(location.hash).toBe("#reset?token=test-token");
});

it("keeps legacy invitation links in the player layout", async () => {
  history.replaceState({}, "", "/Login.html?invite=test-invite");
  render(<PlayerApp />);
  expect(await screen.findByLabelText("用户名")).toHaveAttribute("id", "inv-username");
  expect(screen.getByRole("button", { name: /加入/ })).toBeTruthy();
});

it("preserves the private destination when opening player login and returning to the lobby", async () => {
  history.replaceState({}, "", "/play/saves?sort=recent#latest");
  render(<PlayerApp />);
  fireEvent.click(await screen.findByRole("button", { name: "登录后继续" }));
  await screen.findByLabelText(/用户名/);
  expect(location.pathname).toBe("/play/login");
  expect(new URLSearchParams(location.search).get("next")).toBe("/play/saves?sort=recent#latest");
  fireEvent.click(screen.getByLabelText("故事大厅"));
  await waitFor(() => expect(location.pathname).toBe("/play"));
  expect(await screen.findByRole("heading", { name: "故事大厅" })).toBeTruthy();
});
