import { useEffect, useRef, useState } from "react";
import { lsGetJSON, lsSetJSON } from "../lib/storage.js";

export function useWorkspaceSplit(uid) {
  const key = `player-split-${uid}`;
  const [ratio, setRatio] = useState(() => {
    const stored = lsGetJSON(key, null);
    return Number.isFinite(stored) && stored >= 20 && stored <= 95 ? stored : null;
  });
  const [dragging, setDragging] = useState(false);
  const panes = useRef(null), drag = useRef(null), current = useRef(ratio);
  const update = (value) => { current.current = value; setRatio(value); };
  const commit = (value) => { update(value); lsSetJSON(key, value); };
  useEffect(() => {
    if (!dragging) return;
    const end = (cancel) => {
      const original = drag.current?.original;
      if (!drag.current) return;
      drag.current = null;
      const value = cancel ? original : current.current;
      current.current = value;
      setRatio(value);
      lsSetJSON(key, value);
      setDragging(false);
    };
    const move = (event) => {
      if (!drag.current || event.pointerId !== drag.current.pointerId) return;
      const { left, width, offset } = drag.current;
      const value = Math.max(20, Math.min(95, (event.clientX - left - offset) / width * 100));
      current.current = value;
      setRatio(value);
    };
    const up = (event) => { if (event.pointerId === drag.current?.pointerId) end(false); };
    const cancel = (event) => { if (event.type !== "pointercancel" || event.pointerId === drag.current?.pointerId) end(true); };
    const escape = (event) => { if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); end(true); } };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
    window.addEventListener("blur", cancel);
    window.addEventListener("resize", cancel);
    window.addEventListener("keydown", escape, true);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
      window.removeEventListener("blur", cancel);
      window.removeEventListener("resize", cancel);
      window.removeEventListener("keydown", escape, true);
    };
  }, [dragging, key]);
  return {
    panes, ratio, dragging, collapsed: ratio > 82,
    toggle: () => commit(ratio > 82 ? 50 : 95),
    handleProps: {
      role: "separator", tabIndex: 0, "aria-label": "调整剧情和状态栏宽度",
      "aria-orientation": "vertical", "aria-valuemin": 20, "aria-valuemax": 95,
      "aria-valuenow": Math.round(ratio ?? 65),
      "aria-valuetext": ratio > 82 ? "状态栏已收起" : ratio === null ? "状态栏宽度 320 像素" : `剧情 ${Math.round(ratio)}%，状态 ${100 - Math.round(ratio)}%`,
      onPointerDown: (event) => {
        if (event.button !== 0) return;
        const rect = panes.current.getBoundingClientRect();
        if (!rect.width) return;
        event.preventDefault();
        event.currentTarget.focus();
        event.currentTarget.setPointerCapture?.(event.pointerId);
        const centerWidth = panes.current.querySelector(".workspace-center").getBoundingClientRect().width;
        const offset = Math.max(0, Math.min(14, event.clientX - rect.left - centerWidth));
        drag.current = { original: ratio, left: rect.left, width: Math.max(1, rect.width - 14), offset, pointerId: event.pointerId };
        setDragging(true);
      },
      onDoubleClick: () => commit(50),
      onKeyDown: (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End", "Enter"].includes(event.key)) return;
        event.preventDefault();
        const width = panes.current?.getBoundingClientRect().width;
        const measured = width > 14 ? panes.current.querySelector(".workspace-center").getBoundingClientRect().width / (width - 14) * 100 : 65;
        const previous = ratio ?? (Number.isFinite(measured) ? measured : 65);
        const next = { Home: 20, End: 95, Enter: 50 }[event.key]
          ?? Math.max(20, Math.min(95, previous + (event.key === "ArrowRight" ? 2 : -2)));
        commit(next);
      },
    },
  };
}
