import { useRef } from "react";

// Some IMEs emit compositionend before their final Enter keydown.
export function useComposerKeys(send) {
  const composing = useRef(false), endedAt = useRef(-Infinity);
  return {
    onCompositionStart: () => { composing.current = true; },
    onCompositionEnd: () => { composing.current = false; endedAt.current = Date.now(); },
    onKeyDown: (event) => {
      const native = event.nativeEvent || event;
      const selecting = composing.current || event.isComposing || native.isComposing || native.keyCode === 229;
      if (event.key !== "Enter") return;
      if (selecting || Date.now() - endedAt.current < 500) {
        // Leave candidate selection to the IME; suppress the trailing Enter.
        if (!selecting) event.preventDefault();
        return;
      }
      if (event.ctrlKey || event.metaKey) send(event);
    },
  };
}
