import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PlayerApp } from "../player/PlayerApp.jsx";
import { BookCover } from "../player/shared.jsx";

let media;
beforeEach(() => {
  localStorage.clear();
  history.replaceState({}, "", "/play");
  window.scrollTo = vi.fn();
  media = { matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  vi.stubGlobal("matchMedia", vi.fn(() => media));
  window.api = { player: { bootstrap: vi.fn().mockResolvedValue({
    user: { id: 1 }, wallet: { free_micro: 1000000, permanent_micro: 0 }, stories: [], saves: [],
  }) } };
});
afterEach(() => vi.unstubAllGlobals());

it("follows system changes until a manual theme is selected and preserves it on reload", async () => {
  const first = render(<PlayerApp />);
  await screen.findByRole("heading", { name: "故事大厅" });
  expect(document.documentElement.dataset.reading).toBe("night");
  const change = media.addEventListener.mock.calls[0][1];
  act(() => change({ matches: false }));
  expect(document.documentElement.dataset.reading).toBe("day");
  fireEvent.click(screen.getByRole("button", { name: "切换夜间阅读" }));
  expect(document.documentElement.dataset.reading).toBe("night");
  expect(media.removeEventListener).toHaveBeenCalledWith("change", change);
  expect(JSON.parse(localStorage.getItem("player-reading")).theme).toBe("manual");
  first.unmount();
  media.matches = false;
  render(<PlayerApp />);
  await screen.findByRole("heading", { name: "故事大厅" });
  expect(document.documentElement.dataset.reading).toBe("night");
});

it("honors legacy day preference and font size instead of replacing them with system defaults", async () => {
  localStorage.setItem("player-reading", JSON.stringify({ night: false, font: 22 }));
  const { container } = render(<PlayerApp />);
  await screen.findByRole("heading", { name: "故事大厅" });
  expect(document.documentElement.dataset.reading).toBe("day");
  expect(container.querySelector(".player-app").style.getPropertyValue("--reading-size")).toBe("22px");
  expect(media.addEventListener).not.toHaveBeenCalled();
});

it("refreshes a stored system preference from the current system theme", async () => {
  localStorage.setItem("player-reading", JSON.stringify({ night: false, font: 20, theme: "system" }));
  render(<PlayerApp />);
  await screen.findByRole("heading", { name: "故事大厅" });
  expect(document.documentElement.dataset.reading).toBe("night");
});

it("uses a text cover if a supplied image fails and retries when the cover changes", async () => {
  const { container, rerender } = render(<BookCover story={{ title: "星河旅人", cover: "/cover.jpg" }} />);
  fireEvent.error(container.querySelector("img"));
  expect(screen.getByText("星河旅人")).toBeTruthy();
  expect(container.querySelector("img")).toBeNull();
  rerender(<BookCover story={{ title: "星河旅人", cover: "/new-cover.jpg" }} />);
  await waitFor(() => expect(container.querySelector("img").getAttribute("src")).toBe("/new-cover.jpg"));
});
