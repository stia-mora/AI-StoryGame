import { useCallback, useLayoutEffect, useRef, useState } from "react";

export function useReadingScroll(content, followingEnabled, view = "story") {
  const scroller = useRef(null), following = useRef(true), manual = useRef(false);
  const [node, setNode] = useState(null);
  const bindScroller = useCallback((element) => { scroller.current = element; setNode(element); }, []);
  const programmedTop = useRef(null), wasEnabled = useRef(false);
  const stoppedAt = useRef(null);
  const wasVisible = useRef(true);
  const [away, setAway] = useState(false);
  const distance = (node) => Math.max(0, node.scrollHeight - node.clientHeight - node.scrollTop);
  const jump = useCallback(() => {
    following.current = true;
    manual.current = false;
    const node = scroller.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
      programmedTop.current = node.scrollTop;
    }
    setAway(false);
  }, []);
  const stop = () => { following.current = false; manual.current = true; stoppedAt.current = scroller.current?.scrollTop; programmedTop.current = null; };
  const onScroll = (event) => {
    const node = event.currentTarget, gap = distance(node);
    setAway(gap > 120);
    if (programmedTop.current !== null && Math.abs(node.scrollTop - programmedTop.current) < 1) {
      programmedTop.current = null;
      return;
    }
    programmedTop.current = null;
    // A deliberate scroll interrupts following, even inside the 40px band.
    // Reaching the bottom or pressing Jump opts back in.
    if (manual.current && (gap > 1 || node.scrollTop === stoppedAt.current)) return;
    manual.current = false;
    following.current = gap <= 40;
  };
  const reset = useCallback(() => {
    following.current = false;
    manual.current = true;
    programmedTop.current = null;
    if (scroller.current) scroller.current.scrollTop = 0;
    setAway(false);
  }, []);
  useLayoutEffect(() => {
    if (node) {
      const visible = node.checkVisibility?.() ?? (view === "story" || (window.matchMedia?.("(min-width: 1200px)").matches ?? true));
      if (!visible || !wasVisible.current) {
        // Hidden mobile views retain their position, even if output continues.
        following.current = false;
        manual.current = true;
        programmedTop.current = null;
        wasEnabled.current = followingEnabled;
        wasVisible.current = visible;
        if (visible) setAway(distance(node) > 120);
        return;
      }
      if ((followingEnabled || wasEnabled.current) && following.current) jump();
      else {
        const gap = distance(node);
        setAway(gap > 120);
        if (!followingEnabled && !wasEnabled.current) following.current = !manual.current && gap <= 40;
      }
    }
    wasEnabled.current = followingEnabled;
  }, [content, followingEnabled, jump, view, node]);
  useLayoutEffect(() => {
    if (!node) return;
    const measure = () => {
      if (node.checkVisibility && !node.checkVisibility()) return;
      const gap = distance(node);
      setAway(gap > 120);
      following.current = !manual.current && gap <= 40;
    };
    // Font size, column width and viewport changes can move the bottom
    // without a scroll event or a new token. Measuring never moves the reader.
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(node);
    if (node.firstElementChild) observer?.observe(node.firstElementChild);
    window.addEventListener("resize", measure);
    return () => { observer?.disconnect(); window.removeEventListener("resize", measure); };
  }, [node, view]);
  return {
    scroller, bindScroller, away, jump, reset,
    scrollEvents: {
      onScroll, onWheel: stop, onTouchMove: stop,
      onPointerDown: (event) => {
        const node = event.currentTarget;
        if (event.target === node && event.clientX >= node.getBoundingClientRect().left + node.clientWidth) stop();
      },
      onKeyDown: (event) => {
        if (event.defaultPrevented || event.target.closest?.("input, textarea, select, [contenteditable=true]")) return;
        if (event.key === " " && event.target.closest?.("button, summary, [role=button]")) return;
        if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(event.key)) stop();
      },
    },
  };
}
