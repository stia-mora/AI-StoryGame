import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  CircleNotch,
  BookOpen,
  Minus,
  Plus,
  Stop,
  User,
  CaretLeft,
  CaretRight,
  ChatCircleText,
  Lightning,
  PencilSimple,
  ClockCounterClockwise,
  MapPin,
  SidebarSimple,
} from "@phosphor-icons/react";
import {
  lsGet,
  lsGetJSON,
  lsSet,
  lsSetJSON,
  lsRemove,
} from "../lib/storage.js";
import { safeUUID as uuid } from "../lib/crypto-safe.js";
import { TurnProgress } from "./Progress.jsx";
import { GenerationProgress } from "./GenerationProgress.jsx";
import { ActionChoices } from "./ActionChoices.jsx";
import { Assistant } from "./Assistant.jsx";
import { InformationPanel, SaveRail } from "./WorkspacePanels.jsx";
import { useComposerKeys } from "./useComposerKeys.js";
import { useReadingScroll } from "./useReadingScroll.js";
import { useWorkspaceSplit } from "./useWorkspaceSplit.js";
import {
  Button,
  Loading,
  Narration,
  StreamingNarration,
  Notice,
  Receipt,
  points,
  description,
  actionLabel,
} from "./shared.jsx";

function mergeMessages(older, newer) {
  const entries = new Map([...older, ...newer].map((message) => [message.id, message]));
  return [...entries.values()].sort((a, b) => parseInt(a.id) - parseInt(b.id) || (a.role === "user" ? -1 : 1));
}

const generationStages = ["preparing", "understanding", "retrieving", "generating", "saving"];

export function Reader({
  saveId,
  uid,
  navigate,
  prefs,
  setPrefs,
  refreshWallet,
  saves = [],
  saveTotal = saves.length,
}) {
  const [view, setView] = useState(null),
    [error, setError] = useState(""),
    [draft, setDraft] = useState(() =>
      lsGet(`player-draft-${uid}-${saveId}`, ""),
    );
  const [quote, setQuote] = useState(null),
    [quoteError, setQuoteError] = useState(""),
    [busy, setBusy] = useState(false),
    [streamText, setStreamText] = useState("");
  const [mobileView, setMobileView] = useState("story"),
    [assistantOpen, setAssistantOpen] = useState(false),
    [saveState, setSaveState] = useState("已保存");
  const [quoteRevision, setQuoteRevision] = useState(0);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [generationNotice, setGenerationNotice] = useState("");
  const [stateUnread, setStateUnread] = useState(0);
  const [stage, setStage] = useState("preparing"), [startedAt, setStartedAt] = useState(null), [confirmedAt, setConfirmedAt] = useState(null);
  const [selectedId, setSelectedId] = useState(null),
    [helperBusy, setHelperBusy] = useState(false);
  const changeAssistant = useCallback((open) => {
    setAssistantOpen(open);
    setMobileView(open ? "assistant" : "story");
  }, []);
  const [pace, setPace] = useState(() =>
      lsGet(`player-pace-${uid}-${saveId}`, "standard"),
    ),
    [inputMode, setInputMode] = useState("action");
  const split = useWorkspaceSplit(uid);
  const transformChoice = useCallback(
    (s) => (pace === "brisk" ? `【快进至下一处关键抉择】${s}` : s),
    [pace],
  );
  const transformPreset = useCallback(
    (s) => `【快进至下一处关键抉择】${s}`,
    [],
  );
  const modelMessage = transformChoice(
    inputMode === "dialogue" && draft.trim() ? `【角色对话】${draft}` : draft,
  );
  const rounds = useMemo(
    () => (view?.messages || []).filter((m) => m.role === "assistant"),
    [view?.messages],
  );
  const selectedIndex = Math.max(
    0,
    selectedId
      ? rounds.findIndex((m) => m.id === selectedId)
      : rounds.length - 1,
  );
  const selected = rounds[selectedIndex];
  const latest = !selectedId || selectedIndex === rounds.length - 1;
  const displayView = !latest && view ? {
    ...view,
    status: selected?.status || { name: view.status.name },
    latest_progress: selected?.progress,
    messages: view.messages.filter((message) => parseInt(message.id) <= parseInt(selected.id)),
    journey: (view.journey || []).filter((step) => parseInt(step.message_id) <= parseInt(selected.id)),
  } : view;
  const { scroller, bindScroller, away, jump, reset, scrollEvents } = useReadingScroll(
    streamText || selected?.text, busy && latest, mobileView,
  );
  const selectedAction =
    selected &&
    view?.messages?.find((m) => m.id === selected.id.replace(/-gm$/, "-user"));
  const readRound = (id) => {
    setSelectedId(id || null);
    setMobileView("story");
    reset();
    if (mobileView !== "story") {
      requestAnimationFrame(() => scroller.current?.focus({ preventScroll: true }));
    }
  };
  useEffect(() => {
    lsSet(`player-pace-${uid}-${saveId}`, pace);
  }, [pace, uid, saveId]);
  const execution = useRef(null),
    action = useRef(null),
    input = useRef(null),
    mounted = useRef(true);
  const requestKey = `player-request-${uid}-${saveId}`;
  const options = useMemo(
    () =>
      (view?.options || []).map((option) =>
        (typeof option === "string"
          ? option
          : option.text || option.label || description(option)
        ).replace(/\*\*|__/g, ""),
      ),
    [view?.options],
  );
  const load = useCallback(async () => {
    const v = await window.api.player.save(saveId);
    if (v.pending_action?.id)
      action.current = { ...v.pending_action, kind: "turn" };
    if (mounted.current) setView((old) => old ? {
      ...v, messages: mergeMessages(old.messages, v.messages), history_before: old.history_before,
    } : v);
    return v;
  }, [saveId]);
  const loadEarlier = async () => {
    if (historyBusy || !view?.history_before) return;
    setHistoryBusy(true);
    try {
      const page = await window.api.player.history(saveId, view.history_before);
      if (mounted.current) setView((old) => ({ ...old, messages: mergeMessages(page.messages, old.messages), history_before: page.history_before }));
    } catch (e) { if (mounted.current) setError(e.message); }
    finally { if (mounted.current) setHistoryBusy(false); }
  };
  const finish = useCallback(
    async (id) => {
      try {
        const result = await window.api.player.request(id);
        if (mounted.current && execution.current?.request_id === id) {
          setConfirmedAt(Date.now());
          if (result.progress?.phase) setStage((current) => generationStages.indexOf(result.progress.phase) > generationStages.indexOf(current) ? result.progress.phase : current);
          if (!execution.current.started_at && result.created_at) setStartedAt(Date.parse(result.created_at));
        }
        if (result.status === "settled" || result.status === "released") {
          // Polling and SSE close can both finish an old request after the next one starts.
          if (execution.current?.request_id !== id) return true;
          const followNewer = () => {
            const pending = lsGetJSON(requestKey, null);
            if (!pending?.request_id || pending.request_id === id) return false;
            execution.current = pending;
            if (mounted.current) {
              setBusy(true);
              setSaveState("正在查询保存结果");
            }
            return true;
          };
          if (followNewer()) return false;
          await load();
          if (execution.current?.request_id !== id) return true;
          if (followNewer()) return false;
          lsRemove(requestKey);
          execution.current = null;
          if (mounted.current) {
            setBusy(false);
            setStreamText("");
            setSaveState(
              result.status === "settled"
                ? result.receipt?.partial
                  ? "已保存部分内容"
                  : "已保存"
                : "未保存 · 未扣费",
            );
            if (result.status === "settled") setError("");
            setQuote(null);
          }
          if (result.status === "settled" && result.receipt?.saved) {
            setDraft("");
            action.current = null;
          }
          // A confirmed save must not keep the composer locked behind a wallet read.
          Promise.resolve().then(refreshWallet).catch(() => {
            if (mounted.current && !execution.current) setError("本轮已结束，积分余额刷新失败，请稍后打开积分页查看。");
          });
          return true;
        }
      } catch (e) {
        if (mounted.current && e.status !== 404) setError(e.message);
      }
      return false;
    },
    [load, refreshWallet, requestKey],
  );
  useEffect(() => {
    mounted.current = true;
    load().catch((e) => setError(e.message));
    const pending = lsGetJSON(requestKey, null);
    if (pending) {
      execution.current = pending;
      setBusy(true);
      setStartedAt(pending.started_at || Date.now());
      setSaveState("正在查询保存结果");
      finish(pending.request_id).then(async (completed) => {
        if (completed) return;
        try {
          await window.api.player.request(pending.request_id);
        } catch (e) {
          if (e.status === 404) {
            lsRemove(requestKey);
            execution.current = null;
            if (mounted.current) {
              setBusy(false);
              setSaveState("未发送 · 未扣费");
              setError("上次请求未被服务器受理，请重试。");
            }
          }
        }
      });
    }
    return () => {
      mounted.current = false;
    };
  }, [load, finish, requestKey]);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => {
      if (execution.current) finish(execution.current.request_id);
    }, 3000);
    return () => clearInterval(timer);
  }, [busy, finish]);
  useEffect(() => {
    lsSet(`player-draft-${uid}-${saveId}`, draft);
  }, [draft, uid, saveId]);
  const kind = view?.has_opening ? "turn" : "opening";
  useEffect(() => {
    setQuote(null);
    setQuoteError("");
    if (!view || busy || helperBusy || !latest || (kind === "turn" && !draft.trim()))
      return;
    let active = true;
    const timer = setTimeout(async () => {
      try {
        const q = await window.api.player.quote({
          save_id: saveId,
          kind,
          message: kind === "opening" ? "" : modelMessage,
        });
        if (active) setQuote(q);
      } catch (e) {
        if (active) setQuoteError(e.message);
      }
    }, 450);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [
    modelMessage,
    kind,
    view?.has_opening,
    saveId,
    busy,
    helperBusy,
    quoteRevision,
    latest,
  ]);
  useEffect(() => {
    if (!quote || busy) return;
    const timer = setTimeout(() => setQuoteRevision((v) => v + 1), 60000);
    return () => clearTimeout(timer);
  }, [quote, busy]);
  const executeAction = async (message, selectedQuote) => {
    if (!latest || busy || helperBusy || execution.current || !selectedQuote?.affordable)
      return;
    if (
      !action.current ||
      action.current.message !== message ||
      action.current.kind !== kind
    )
      action.current = { id: uuid(), message, kind };
    const request = {
      save_id: saveId,
      kind,
      message,
      action_id: action.current.id,
      request_id: uuid(),
      quote_id: selectedQuote.id,
      cap_micro: selectedQuote.cap_micro,
      started_at: Date.now(),
      timing: selectedQuote.timing,
    };
    execution.current = request;
    lsSetJSON(requestKey, request);
    setQuote(selectedQuote);
    setBusy(true);
    setStartedAt(request.started_at);
    setConfirmedAt(null);
    setStage("preparing");
    setError("");
    setStreamText("");
    setGenerationNotice("");
    setSelectedId(null);
    setSaveState("正在生成");
    const channel = window.api.player.execute(request, {
      on_notice: (data) => mounted.current && setGenerationNotice(data.message),
      on_saving: (data) => {
        if (mounted.current) {
          Promise.resolve().then(refreshWallet).catch(() => {});
          setConfirmedAt(Date.now());
          setStage(data?.phase || "preparing");
          setSaveState(
            kind === "opening" ? "正在准备故事" : "正在理解你的行动",
          );
        }
      },
      on_stage: (data) => {
        if (mounted.current) {
          setConfirmedAt(Date.now());
          setStage(data.phase);
          setSaveState(data.label);
        }
      },
      on_token: (data) => {
        if (mounted.current) {
          setConfirmedAt(Date.now());
          setStage("generating");
          setSaveState("故事正在展开");
          setStreamText((t) => t + data.text);
        }
      },
      on_receipt: (receipt) => {
        if (mounted.current) {
          setStreamText(receipt.text);
          setStage("saving");
          setSaveState("正在确认保存结果");
        }
      },
      on_saved: (data) => {
        if (data.saved && kind === "turn") {
          setDraft("");
          action.current = null;
        }
      },
      on_error: (data) => {
        if (mounted.current) setError(data.message);
      },
      onError: (e) => {
        if (mounted.current) {
          setError(
            e.status
              ? e.message
              : "连接暂时中断，正在查询保存结果，请勿重复发送。",
          );
          setSaveState("正在查询保存结果");
        }
      },
      onClose: () => finish(request.request_id),
    });
    await channel.done;
    const completed = await finish(request.request_id);
    if (!completed) {
      // A rejected execution may have no server request; recover quote and preserve the logical action.
      try {
        await window.api.player.request(request.request_id);
      } catch (e) {
        // A timeout/offline response cannot prove that the execution was rejected.
        // Retain its ID and keep polling until the server confirms a terminal result.
        if (
          e.status === 404 &&
          execution.current?.request_id === request.request_id
        ) {
          lsRemove(requestKey);
          execution.current = null;
          setBusy(false);
          setQuote(null);
          setSaveState("未发送 · 未扣费");
        }
      }
    }
  };
  const send = (e) => {
    e?.preventDefault();
    return executeAction(kind === "opening" ? "" : modelMessage, quote);
  };
  const composerKeys = useComposerKeys(send);
  const sendChoice = (message, selectedQuote) => {
    if (busy || helperBusy || execution.current || !selectedQuote?.affordable)
      return;
    setInputMode("action");
    setDraft(message.replace(/^【快进至下一处关键抉择】/, ""));
    return executeAction(message, selectedQuote);
  };
  const stop = async () => {
    if (execution.current) {
      try {
        await window.api.player.stop(execution.current.request_id);
        setSaveState("正在保存已生成内容");
      } catch (e) {
        setError(e.message);
      }
    }
  };
  if (!view)
    return error ? (
      <main id="player-main" className="player-shell">
        <Notice error>{error}</Notice>
        <Button onClick={() => load().catch((e) => setError(e.message))}>
          重新加载
        </Button>
      </main>
    ) : (
      <Loading />
    );
  const pager = (
    <div className="workspace-pagination">
      <button
        className="icon-button"
        aria-label="上一回合"
        disabled={!rounds.length || selectedIndex === 0}
        onClick={() => readRound(rounds[selectedIndex - 1].id)}
      >
        <CaretLeft size={18} />
      </button>
      <span>
        {rounds.length
          ? `${selectedIndex + 1} / ${rounds.length} 页`
          : "故事尚未展开"}
      </span>
      <button
        className="icon-button"
        aria-label="下一回合"
        disabled={selectedIndex >= rounds.length - 1}
        onClick={() => readRound(rounds[selectedIndex + 1].id)}
      >
        <CaretRight size={18} />
      </button>
      {!latest && (
        <button className="text-button" onClick={() => readRound(null)}>
          回到当前回合
        </button>
      )}
    </div>
  );
  const rail = (
    <SaveRail
      view={view}
      saves={saves}
      saveTotal={saveTotal}
      navigate={navigate}
      rounds={rounds}
      selectedId={selected?.id}
      onRead={readRound}
      busy={busy || helperBusy}
      saveState={saveState}
      loadEarlier={loadEarlier}
      historyBusy={historyBusy}
    />
  );
  const information = <InformationPanel view={displayView} historical={!latest} uid={uid} active={mobileView === "state"} desktopHidden={split.collapsed || split.dragging} onRead={readRound} onUnreadChange={setStateUnread} />;
  const changeView = (next) => {
    setMobileView(next);
    setAssistantOpen(next === "assistant");
  };
  return (
    <main id="player-main" className="play-workspace has-reader-split" data-view={mobileView} tabIndex={-1}>
      {view.story?.cover && (
        <img
          className="workspace-backdrop"
          src={view.story.cover}
          alt=""
          aria-hidden="true"
          onError={(e) => { e.currentTarget.hidden = true; }}
        />
      )}
      <aside id="player-records" className="workspace-rail" aria-label="剧本与回合记录">
        {rail}
      </aside>
      <div className="workspace-panes" ref={split.panes} data-dragging={split.dragging} data-state-collapsed={split.collapsed} style={split.ratio === null ? undefined : { "--reader-share": `${split.ratio}fr`, "--state-share": `${100 - split.ratio}fr` }}>
      <section id="player-story" className="workspace-center" aria-label="当前剧情">
        <header className="workspace-reader-header">
          <h1>{view.save.story_title}</h1>
          <span className="workspace-player-name">
            <User size={14} />{view.status.name}
          </span>
          <span className="workspace-round-label">
            {busy && latest
              ? "正在展开"
              : selected?.turn === 0
                ? "序章"
                : `第 ${selected?.turn ?? view.save.turn} 回合`}
          </span>
          {displayView.status.location && (
            <span className="workspace-scene">
              <MapPin size={14} />
              <span>{description(displayView.status.location)}</span>
              {displayView.status.time && <span>{description(displayView.status.time)}</span>}
            </span>
          )}
          <div className="workspace-reading-tools">
            <button className="icon-button" aria-label="故事评论" disabled={busy || helperBusy} onClick={() => navigate(`/play/stories/${view.save.story_id}/comments?save=${saveId}`)}><ChatCircleText size={18} /></button>
            <button className="icon-button workspace-state-toggle" aria-label={split.collapsed ? "展开状态栏" : "收起状态栏"} aria-expanded={!split.collapsed} aria-controls="player-state" onClick={split.toggle}><SidebarSimple size={18} />{stateUnread > 0 && <span className="workspace-tab-change" aria-label="状态有未读变化" />}</button>
            <button
              className="icon-button"
              aria-label="缩小字号"
              disabled={prefs.font <= 16}
              onClick={() => setPrefs((p) => ({ ...p, font: p.font - 1 }))}
            >
              <Minus size={16} />
            </button>
            <span>{prefs.font}</span>
            <button
              className="icon-button"
              aria-label="放大字号"
              disabled={prefs.font >= 24}
              onClick={() => setPrefs((p) => ({ ...p, font: p.font + 1 }))}
            >
              <Plus size={16} />
            </button>
          </div>
        </header>
        <div
          className="workspace-reading"
          role="region"
          aria-label="剧情正文"
          tabIndex={0}
          ref={bindScroller}
          {...scrollEvents}
        >
          <div className="workspace-paper">
            {!view.has_opening && !busy && (
              <section className="workspace-opening">
                <div className="workspace-opening-identity">
                  <User size={22} />
                  <strong>{view.status.name}</strong>
                  <span>{view.status.role}</span>
                </div>
                <h2><BookOpen size={18} />开场待生成</h2>
                <p>
                  {view.character_setup && !view.character_setup.completed
                    ? `武魂${view.character_setup.mode === "random" ? "将在觉醒时随机揭晓" : `已选择「${view.character_setup.name}」`}。这次开场会直接完成觉醒、测定先天魂力，并进入下一处成长选择。`
                    : "角色已经创建。开场会推进起点事件，再从四个完整行动中选择，也可以写下自己的想法。"}
                </p>
              </section>
            )}
            {selected && !(busy && latest) && (
              <>
                {selectedAction && (
                  <div className="workspace-action">
                    <span>你的行动</span>
                    <p>{actionLabel(selectedAction.text)}</p>
                  </div>
                )}
                <article>
                  <Narration text={selected.text} />
                  <TurnProgress progress={selected.progress} />
                  <Receipt receipt={selected.receipt} />
                </article>
              </>
            )}
            {busy && latest && (
              <article aria-busy="true">
                <div className="workspace-action">
                  <span>你的行动</span>
                  <p>{actionLabel(action.current?.message || "开始故事")}</p>
                </div>
                <StreamingNarration text={streamText} />
              </article>
            )}
            {error && <Notice error>{error}</Notice>}
            {busy && generationNotice && <Notice>{generationNotice}</Notice>}
            {!busy && view.has_opening && latest && options.length > 0 && (
              <ActionChoices
                options={options}
                saveId={saveId}
                onSend={sendChoice}
                navigate={navigate}
                disabled={helperBusy}
                transform={transformPreset}
              />
            )}
            {!latest && (
              <p className="workspace-history-note">
                正在只读查看{selected?.turn === 0 ? "序章" : `第 ${selected?.turn} 回合`}及该回合保存的状态。
              </p>
            )}
          </div>
        </div>
        <div className="workspace-composer-dock">
          {busy && <GenerationProgress phase={stage} startedAt={startedAt} confirmedAt={confirmedAt} opening={kind === "opening"} timing={quote?.timing || execution.current?.timing} />}
          {away && latest && (
            <button
              className="workspace-jump"
              onClick={jump}
            >
              <ArrowDown size={15} />
              跳至最新
            </button>
          )}
          <div className="workspace-dock-toolbar">
            {pager}
            <span className="workspace-autosave" aria-live="polite">
              {busy ? <CircleNotch size={13} /> : <Check size={13} />}{" "}
              {saveState}
            </span>
          </div>
          {!latest ? <div className="workspace-history-actions"><Button type="button" onClick={() => readRound(null)}>返回最新回合后行动</Button></div> : <form className="workspace-composer" onSubmit={send}>
            {kind === "turn" && (
              <>
                <label className="sr-only" htmlFor="player-action">
                  你要如何行动？
                </label>
                <textarea
                  id="player-action"
                  ref={input}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder={
                    inputMode === "dialogue"
                      ? "写下你要对谁说什么……"
                      : "描述你的行动、目标，或写一段对话……"
                  }
                  maxLength={6000}
                  rows={2}
                  disabled={busy || helperBusy}
                  {...composerKeys}
                />
                <div className="workspace-input-modes">
                  <button
                    type="button"
                    aria-pressed={inputMode === "action"}
                    disabled={busy || helperBusy}
                    onClick={() => setInputMode("action")}
                  >
                    <PencilSimple size={15} />
                    自由行动
                  </button>
                  <button
                    type="button"
                    aria-pressed={inputMode === "dialogue"}
                    disabled={busy || helperBusy}
                    onClick={() => setInputMode("dialogue")}
                  >
                    <ChatCircleText size={15} />
                    角色对话
                  </button>
                  <button
                    className="workspace-pace"
                    type="button"
                    aria-pressed={pace === "brisk"}
                    disabled={busy || helperBusy}
                    onClick={() =>
                      setPace(pace === "brisk" ? "standard" : "brisk")
                    }
                    title="合并日常准备与行程，停在下一处关键抉择"
                  >
                    <Lightning size={15} />
                    {pace === "brisk" ? "快进开启" : "快进"}
                  </button>
                </div>
              </>
            )}
            <div className="workspace-composer-footer">
              <div className="quote-note" aria-live="polite">
                {busy ? (
                  <span>
                    已预留{" "}
                    {points(quote?.cap_micro || execution.current?.cap_micro)}{" "}
                    积分 · 保存后结算
                  </span>
                ) : helperBusy ? (
                  <span>助手正在咨询，完成后可继续行动</span>
                ) : quoteError ? (
                  <span className="error-text">{quoteError}</span>
                ) : quote ? (
                  <>
                    <span>{quote.funding === "preview" ? "专用试玩 · " : ""}预计 {points(quote.estimate_micro)} 积分</span>
                    <span>
                      本轮封顶 {points(quote.cap_micro)}
                      {!quote.affordable && " · 余额不足"}
                    </span>
                    <span>封顶是扣费上限，实扣按用量结算，未用预留自动退回。</span>
                  </>
                ) : (
                  <span>
                    {draft.trim() || kind === "opening"
                      ? "正在估算本轮费用……"
                      : "Ctrl / ⌘ + Enter 发送 · 草稿自动保留"}
                  </span>
                )}
              </div>
              {busy ? (
                <Button quiet type="button" onClick={stop}>
                  <Stop size={17} />
                  停止生成
                </Button>
              ) : (
                <Button
                  type="submit"
                  disabled={helperBusy || !quote?.affordable}
                >
                  {kind === "opening" ? "生成开场" : "行动"}
                  <ArrowUp size={17} />
                </Button>
              )}
            </div>
            {quote && !quote.affordable && (
              <button
                className="text-button"
                type="button"
                onClick={() => navigate(quote.funding === "preview" ? "/play/authoring" : "/play/wallet")}
              >
                查看积分与兑换码
              </button>
            )}
          </form>}
        </div>
      </section>
      <div className="workspace-splitter" {...split.handleProps}><span aria-hidden="true" /></div>
      <aside id="player-state" className="workspace-right" aria-label="当前局势与世界线" inert={split.dragging}>
        {information}
        {split.dragging && <div className="workspace-resize-shield" aria-hidden="true" />}
      </aside>
      </div>
      <Assistant
        uid={uid}
        saveId={saveId}
        name={view.status.name}
        gameBusy={busy || !latest}
        historical={!latest}
        onBusy={setHelperBusy}
        open={assistantOpen}
        onOpenChange={changeAssistant}
        onUse={(value) => {
          setMobileView("story");
          setInputMode("action");
          setDraft(value);
          requestAnimationFrame(() => input.current?.focus());
        }}
        refreshWallet={refreshWallet}
      />
      <nav className="workspace-mobile-nav" aria-label="游玩视图">
        {[
          ["story", "剧情", BookOpen, "player-story"],
          ["state", "状态", User, "player-state"],
          ["records", "记录", ClockCounterClockwise, "player-records"],
          ["assistant", "助手", ChatCircleText, "player-assistant-panel"],
        ].map(([id, label, Icon, controls]) => (
          <button
            key={id}
            aria-current={mobileView === id ? "page" : undefined}
            aria-controls={controls}
            onClick={() => changeView(id)}
          >
            <Icon size={20} weight={mobileView === id ? "fill" : "regular"} />
            {label}
            {id === "state" && stateUnread > 0 && <span className="workspace-tab-change" aria-label="状态有未读变化" />}
            {id === "assistant" && helperBusy && (
              <span className="workspace-nav-busy" aria-label="正在咨询" />
            )}
          </button>
        ))}
      </nav>
    </main>
  );
}
