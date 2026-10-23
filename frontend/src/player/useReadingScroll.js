import { useCallback, useLayoutEffect, useRef, useState } from "react";

export function useReadingScroll(content, followingEnabled) {
  const scroller = useRef(null), following = useRef(true), manual = useRef(false);
  const programmedTop = useRef(null), wasEnabled = useRef(false);
  const stoppedAt = useRef(null);
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
    const node = scroller.current;
    if (node) {
      if (node.checkVisibility && !node.checkVisibility()) return;
      if ((followingEnabled || wasEnabled.current) && following.current) jump();
      else {
        const gap = distance(node);
        setAway(gap > 120);
        if (!followingEnabled && !wasEnabled.current) following.current = !manual.current && gap <= 40;
      }
    }
    wasEnabled.current = followingEnabled;
  }, [content, followingEnabled, jump]);
  return {
    scroller, away, jump, reset,
    scrollEvents: {
      onScroll, onWheel: stop, onTouchMove: stop,
      onPointerDown: (event) => {
        const node = event.currentTarget;
        if (event.target === node && event.clientX >= node.getBoundingClientRect().left + node.clientWidth) stop();
      },
      onKeyDown: (event) => { if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(event.key)) stop(); },
    },
  };
}
