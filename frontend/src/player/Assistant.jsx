import React, { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, ChatCircleText, Stop, X } from "@phosphor-icons/react";
import {
  lsGetJSON,
  lsSetJSON,
  lsRemove,
  lsGet,
  lsSet,
} from "../lib/storage.js";
import { safeUUID as uuid } from "../lib/crypto-safe.js";
import { Button, Narration, Notice, Receipt, points } from "./shared.jsx";

export function Assistant({
  uid,
  saveId,
  name,
  gameBusy,
  onBusy,
  onUse,
  refreshWallet,
}) {
  const [open, setOpen] = useState(false),
    [items, setItems] = useState([]),
    [busy, setBusy] = useState(false);
  const key = `player-guide-request-${uid}-${saveId}`,
    draftKey = `player-guide-draft-${uid}-${saveId}`;
  const [draft, setDraft] = useState(() => lsGet(draftKey, "")),
    [quote, setQuote] = useState(null),
    [error, setError] = useState("");
  const pending = useRef(null),
    mounted = useRef(true),
    panel = useRef(null),
    trigger = useRef(null),
    usingSuggestion = useRef(false);
  const reload = useCallback(async () => {
    const result = await window.api.player.guideHistory(saveId);
    if (mounted.current) setItems(result.items);
  }, [saveId]);
  const finish = useCallback(
    async (id) => {
      try {
        const result = await window.api.player.request(id);
        if (
          !["settled", "released"].includes(result.status) ||
          pending.current?.request_id !== id
        )
          return false;
        const followNewer = () => {
          const newer = lsGetJSON(key, null);
          if (!newer?.request_id || newer.request_id === id) return false;
          pending.current = newer;
          if (mounted.current) {
            setBusy(true);
            onBusy(true);
          }
          return true;
        };
        if (followNewer()) return false;
        await reload();
        await refreshWallet();
        if (pending.current?.request_id !== id || followNewer()) return false;
        lsRemove(key);
        pending.current = null;
        if (mounted.current) {
          setBusy(false);
          onBusy(false);
          setQuote(null);
          if (result.status === "settled") {
            setDraft("");
            setError("");
          }
          else setError("咨询未完成，预留已释放，未扣积分。");
        }
        return true;
      } catch (e) {
        if (e.status === 404 && pending.current?.request_id === id) {
          lsRemove(key);
          pending.current = null;
          if (mounted.current) {
            setBusy(false);
            onBusy(false);
            setError("上次咨询未发送，请重新尝试。");
          }
        }
        return false;
      }
    },
    [key, reload, refreshWallet, onBusy],
  );
  useEffect(() => {
    mounted.current = true;
    reload().catch(() => {});
    const request = lsGetJSON(key, null);
    if (request) {
      pending.current = request;
      setBusy(true);
      onBusy(true);
      finish(request.request_id);
    }
    return () => {
      mounted.current = false;
    };
  }, [reload, key, finish, onBusy]);
  useEffect(() => {
    lsSet(draftKey, draft);
  }, [draftKey, draft]);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(
      () => pending.current && finish(pending.current.request_id),
      3000,
    );
    return () => clearInterval(timer);
  }, [busy, finish]);
  useEffect(() => {
    setQuote(null);
    if (!draft.trim() || busy || gameBusy || !open) return;
    let live = true;
    const timer = setTimeout(
      () =>
        window.api.player
          .quote({ save_id: saveId, kind: "guide", message: draft })
          .then((q) => live && setQuote(q))
          .catch((e) => live && setError(e.message)),
      450,
    );
    const expiry = setInterval(
      () =>
        window.api.player
          .quote({ save_id: saveId, kind: "guide", message: draft })
          .then((q) => live && setQuote(q))
          .catch((e) => live && setError(e.message)),
      60000,
    );
    return () => {
      live = false;
      clearTimeout(timer);
      clearInterval(expiry);
    };
  }, [draft, busy, gameBusy, open, saveId]);
  useEffect(() => {
    if (!open) return;
    usingSuggestion.current = false;
    const previous = document.activeElement;
    panel.current?.querySelector("textarea")?.focus();
    const escape = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("keydown", escape);
      if (!usingSuggestion.current) previous?.focus();
    };
  }, [open]);
  const send = async (e) => {
    e?.preventDefault();
    if (gameBusy || busy || pending.current || !quote?.affordable) return;
    const request = {
      save_id: saveId,
      kind: "guide",
      message: draft,
      quote_id: quote.id,
      action_id: uuid(),
      request_id: uuid(),
    };
    pending.current = request;
    lsSetJSON(key, request);
    setBusy(true);
    onBusy(true);
    setError("");
    const channel = window.api.player.execute(request, {
      on_error: (data) => mounted.current && setError(data.message),
      onError: () =>
        mounted.current && setError("连接中断，正在查询咨询结果。"),
      onClose: () => finish(request.request_id),
    });
    await channel.done;
    await finish(request.request_id);
  };
  return (
    <>
      <button
        ref={trigger}
        className="workspace-assistant-trigger"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-label="打开游玩助手"
      >
        <ChatCircleText size={20} />
        <span>游玩助手</span>
        {busy && <small>思考中</small>}
      </button>
      {open && (
        <section
          className="workspace-assistant"
          ref={panel}
          role="region"
          aria-label="游玩助手"
        >
          <header>
            <div>
              <ChatCircleText size={22} />
              <strong>游玩助手</strong>
            </div>
            <button
              className="icon-button"
              aria-label="关闭游玩助手"
              onClick={() => setOpen(false)}
            >
              <X size={19} />
            </button>
          </header>
          <p className="workspace-assistant-binding">
            已绑定 {name}的世界线 · 咨询不会推进回合
          </p>
          <div className="workspace-assistant-history">
            {!items.length && (
              <div className="workspace-assistant-empty">
                <h3>一起想清楚下一步。</h3>
                <p>分析眼前局势、整理人物关系，或拟定一条更具体的行动。</p>
                {[
                  "目前有什么值得注意的风险？",
                  "根据当前目标，建议我怎样推进？",
                ].map((s) => (
                  <button key={s} onClick={() => setDraft(s)}>
                    {s}
                  </button>
                ))}
              </div>
            )}
            {items.map((item) => (
              <article key={item.request_id}>
                <p className="workspace-assistant-question">{item.question}</p>
                <Narration text={item.text} />
                {item.options?.map((option) => (
                  <button
                    className="workspace-assistant-suggestion"
                    key={option}
                    disabled={gameBusy || busy}
                    onClick={() => {
                      usingSuggestion.current = true;
                      onUse(option);
                      setOpen(false);
                    }}
                  >
                    填入行动框 · {option}
                  </button>
                ))}
                <Receipt receipt={item} />
              </article>
            ))}
            {busy && (
              <p role="status" className="muted">
                正在结合当前存档分析……可以关闭面板，结果会保留。
              </p>
            )}
            {error && <Notice error>{error}</Notice>}
          </div>
          <form onSubmit={send}>
            <label className="sr-only" htmlFor="player-guide">
              向游玩助手提问
            </label>
            <textarea
              id="player-guide"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={2}
              maxLength={6000}
              placeholder="询问局势或请助手帮你拟定行动……"
              disabled={busy || gameBusy}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  (e.ctrlKey || e.metaKey) &&
                  !e.nativeEvent.isComposing
                )
                  send(e);
              }}
            />
            <div className="workspace-assistant-footer">
              <small>
                {gameBusy
                  ? "回合完成后可咨询"
                  : busy
                    ? "已预留，完成后按实际用量结算"
                    : quote
                      ? `预计 ${points(quote.estimate_micro)} · 封顶 ${points(quote.cap_micro)} 积分${quote.affordable ? "" : " · 余额不足"}`
                      : draft.trim()
                        ? "正在获取报价……"
                        : "咨询按实际用量计费"}
              </small>
              {busy ? (
                <Button
                  quiet
                  type="button"
                  onClick={() =>
                    window.api.player
                      .stop(pending.current.request_id)
                      .catch((e) => setError(e.message))
                  }
                >
                  <Stop size={15} />
                  停止
                </Button>
              ) : (
                <Button type="submit" disabled={gameBusy || !quote?.affordable}>
                  发送
                  <ArrowUp size={16} />
                </Button>
              )}
            </div>
          </form>
        </section>
      )}
    </>
  );
}
