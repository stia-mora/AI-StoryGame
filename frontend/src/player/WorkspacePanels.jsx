import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  Clock,
  GitBranch,
  MapPin,
  Target,
  User,
  Package,
  Users,
  CaretRight,
  Check,
  ListChecks,
  Sparkle,
} from "@phosphor-icons/react";
import { BookCover, description, actionLabel } from "./shared.jsx";
import { TurnProgress } from "./Progress.jsx";
import { lsGetJSON, lsSetJSON } from "../lib/storage.js";
import { stateUpdates } from "./stateUpdates.js";

const tabs = [
  ["overview", "局势", Target],
  ["character", "角色", User],
  ["inventory", "背包", Package],
  ["people", "人物", Users],
  ["tasks", "任务", ListChecks],
  ["worldline", "世界线", GitBranch],
];
const atEnd = (node) => node && node.scrollHeight - node.scrollTop - node.clientHeight <= 8;

function Records({ title, values, empty = "尚无记录" }) {
  const [open, setOpen] = useState(true);
  const id = useId();
  const items = Array.isArray(values) ? values : values ? [values] : [];
  return (
    <section className="workspace-records">
      <button className="records-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        {title}
        <span>{items.length || "—"}</span>
      </button>
      <div id={id} className="collapse-grid" data-open={open} inert={!open}><div>
      {items.length ? (
        <ul>
          {items.map((item, i) => (
            <li key={i}>{description(item)}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">{empty}</p>
      )}
      </div></div>
    </section>
  );
}

export function InformationPanel({ view, uid, active = true, desktopHidden = false, onRead, onUnreadChange }) {
  const [tab, setTab] = useState("overview");
  const panelId = useId();
  const readKey = `player-state-read-${uid || "guest"}-${view.save.id}`;
  const [read, setRead] = useState(() => lsGetJSON(readKey, {}));
  const [preview, setPreview] = useState(null);
  const [readIntent, setReadIntent] = useState(null);
  const [foreground, setForeground] = useState(() => !document.hidden);
  const content = useRef(null), tooltip = useRef(null), changeArea = useRef(null), closeTimer = useRef(null), frame = useRef(null);
  const previewTrigger = useRef(null);
  const updates = useMemo(() => stateUpdates(view), [view]);
  const unread = (id) => updates[id].filter((group) => group.order > (read[id] || 0));
  const unreadCount = Object.keys(updates).filter((id) => unread(id).length).length;
  const markRead = useCallback((id, groups) => {
    const desktop = window.matchMedia?.("(min-width: 1200px)").matches ?? true;
    const node = content.current;
    if (document.hidden || !(desktop ? !desktopHidden : active) || id !== tab || !groups.length || !atEnd(node)) return;
    if (node.checkVisibility && !node.checkVisibility()) return;
    if (node.querySelector('.collapse-grid[data-open="false"] li')) return;
    const order = Math.max(...groups.map((group) => group.order));
    setRead((old) => {
      if ((old[id] || 0) >= order) return old;
      const next = { ...old, [id]: order };
      lsSetJSON(readKey, next);
      return next;
    });
  }, [active, desktopHidden, readKey, tab]);
  const showPreview = (event) => {
    clearTimeout(closeTimer.current);
    previewTrigger.current = event.currentTarget;
    const groups = unread(tab).length ? unread(tab) : updates[tab].slice(0, 1);
    setPreview(groups.length ? { id: tab, groups } : null);
  };
  const closePreview = () => {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => {
      if (!changeArea.current?.contains(document.activeElement)) setPreview(null);
    }, 160);
  };
  const selectTab = (id) => {
    clearTimeout(closeTimer.current);
    setTab(id);
    setPreview(null);
    setReadIntent(null);
    const groups = updates[id];
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      if (content.current) content.current.scrollTop = 0;
      setReadIntent({ id, groups });
    });
  };
  const browsePanel = () => {
    setReadIntent(atEnd(content.current) ? { id: tab, groups: updates[tab] } : null);
  };
  useEffect(() => { onUnreadChange?.(unreadCount); }, [onUnreadChange, unreadCount]);
  useEffect(() => {
    const visibility = () => setForeground(!document.hidden);
    document.addEventListener("visibilitychange", visibility);
    return () => document.removeEventListener("visibilitychange", visibility);
  }, []);
  useEffect(() => {
    if (!foreground || !readIntent || preview) return;
    // Only the actual panel can acknowledge its contents. A changes tooltip
    // may cover the panel or omit records that have not been browsed yet.
    const timer = setTimeout(() => markRead(readIntent.id, readIntent.groups), 700);
    return () => clearTimeout(timer);
  }, [foreground, readIntent, preview, markRead]);
  useEffect(() => {
    if (!preview) return;
    const outside = (event) => { if (!changeArea.current?.contains(event.target)) setPreview(null); };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [preview]);
  useEffect(() => () => {
    clearTimeout(closeTimer.current);
    cancelAnimationFrame(frame.current);
  }, []);
  useEffect(() => () => cancelAnimationFrame(frame.current), [active, desktopHidden]);
  const { status, latest_progress: progress, journey = [] } = view;
  return (
    <div className="workspace-information">
      <div className="workspace-state-heading">
      <div className="workspace-tabs" role="tablist" aria-label="存档信息">
        {tabs.map(([id, title, Icon]) => (
          <button
            key={id}
            role="tab"
            id={`${panelId}-tab-${id}`}
            aria-controls={`${panelId}-panel`}
            aria-selected={id === tab}
            aria-label={title}
            aria-description={unread(id).length ? `${unread(id).length} 个回合有未读变化` : undefined}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => selectTab(id)}
            onKeyDown={(e) => {
              if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key))
                return;
              e.preventDefault();
              const index = tabs.findIndex(([key]) => key === tab);
              const next =
                e.key === "Home"
                  ? 0
                  : e.key === "End"
                    ? tabs.length - 1
                    : (index +
                        (e.key === "ArrowRight" ? 1 : -1) +
                        tabs.length) %
                      tabs.length;
              selectTab(tabs[next][0]);
              const nextTab =
                e.currentTarget.parentElement?.querySelectorAll('[role="tab"]')[
                  next
                ];
              nextTab?.focus();
            }}
          >
            <Icon size={17} />
            {title}
            {unread(id).length > 0 && (
              <span className="workspace-tab-change" aria-label="有未读变化" />
            )}
          </button>
        ))}
      </div>
      <div className="workspace-world-id">
        <User size={17} />
        <strong>{status.name}</strong>
        <small>存档 {view.save.id}</small>
      </div>
      {updates[tab].length > 0 && (
        <div
          className="workspace-change-bar"
          ref={changeArea}
          onMouseLeave={closePreview}
          onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setPreview(null); }}
          onKeyDown={(event) => {
            if (event.key !== "Escape") return;
            event.stopPropagation();
            if (tooltip.current?.contains(document.activeElement)) previewTrigger.current?.focus({ preventScroll: true });
            setPreview(null);
          }}
        >
          <button
            type="button"
            onMouseEnter={showPreview}
            onFocus={showPreview}
            onClick={showPreview}
            aria-description={unread(tab).length ? `${unread(tab).length} 个回合有未读变化` : undefined}
            aria-describedby={preview?.id === tab ? `${panelId}-updates` : undefined}
          >
            <Sparkle size={16} />
            <span>查看最近回合变化</span>
            <CaretRight size={14} />
          </button>
          {preview && (
            <div
              className="workspace-change-tooltip"
              role="tooltip"
              id={`${panelId}-updates`}
              ref={tooltip}
              tabIndex={0}
              onMouseEnter={() => clearTimeout(closeTimer.current)}
            >
              <strong>{tabs.find(([id]) => id === preview.id)[1]}变化</strong>
              {preview.groups.map((group) => (
                <section key={group.id}>
                  <h3>{group.turn === 0 ? "序章" : `第 ${group.turn ?? view.save.turn} 回合`}</h3>
                  <ul>
                    {group.entries.map((entry, index) => (
                      <li key={index}>
                        <span>{entry.label}</span>
                        {entry.before && <del>{entry.before}</del>}
                        <p>{entry.after}</p>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </div>
      )}
      </div>
      <section
        className="workspace-information-scroll"
        role="tabpanel"
        id={`${panelId}-panel`}
        aria-labelledby={`${panelId}-tab-${tab}`}
        tabIndex={0}
        ref={content}
        onScroll={browsePanel}
        onFocus={browsePanel}
        onClick={browsePanel}
      >
        {tab === "overview" && (
          <>
            <div className="workspace-location">
              <MapPin size={19} />
              <div>
                <h2>{description(status.location) || "地点尚未记录"}</h2>
                {status.time && (
                  <small>
                    <Clock size={13} />
                    {description(status.time)}
                  </small>
                )}
              </div>
            </div>
            <section className="workspace-objective">
              <h3>
                <Target size={16} />
                当前目标
              </h3>
              <p>
                {description(status.objective) ||
                  "从眼前的场景开始，决定你的第一步。"}
              </p>
            </section>
            <section className="workspace-last-step">
              <h3>上一步进展</h3>
              <p>{progress?.summary || "生成开场后，这里会记录你的进展。"}</p>
            </section>
            {progress && <TurnProgress progress={progress} latest />}
          </>
        )}
        {tab === "character" && (
          <>
            <div className="workspace-character">
              <User size={25} />
              <h2>{status.name}</h2>
              <p>{status.role}</p>
            </div>
            <Records
              title="已知属性"
              values={status.attributes}
              empty="属性尚未在故事中确认"
            />
            <Records title="能力与技能" values={status.abilities} />
            <Records title="资源" values={status.resources} />
          </>
        )}
        {tab === "inventory" && (
          <>
            <Records title="随身物品" values={status.inventory} />
            <Records title="资源" values={status.resources} />
          </>
        )}
        {tab === "people" && (
          <Records
            title="已知人物与关系"
            values={status.people}
            empty="遇见并认识的人会记录在这里"
          />
        )}
        {tab === "tasks" && (
          <>
            {status.objective && (
              <section className="workspace-objective">
                <h3>
                  <Target size={16} />
                  当前推进
                </h3>
                <p>{description(status.objective)}</p>
              </section>
            )}
            <h3>任务与成长目标</h3>
            {status.tasks?.length ? (
              <ul className="workspace-task-list">
                {status.tasks
                  .filter(
                    (task) => !status.objective || task.name !== "当前目标",
                  )
                  .map((task) => (
                    <li key={task.name}>
                      <div>
                        <strong>{task.name}</strong>
                        <span data-status={task.status}>
                          {
                            {
                              active: "进行中",
                              completed: "已完成",
                              failed: "失败",
                              paused: "暂缓",
                            }[task.status]
                          }
                        </span>
                      </div>
                      {task.description && <p>{task.description}</p>}
                      {task.progress && (
                        <>
                          <small className="muted">最近记录</small>
                          <small>{task.progress}</small>
                        </>
                      )}
                    </li>
                  ))}
              </ul>
            ) : (
              <p className="muted">尚未接取任务。目标确认后会记录在这里。</p>
            )}
          </>
        )}
        {tab === "worldline" && (
          <>
            {status.milestones?.length > 0 && (
              <Records title="已达成节点" values={status.milestones} />
            )}
            <h3>世界线记录</h3>
            <ol className="workspace-timeline">
              {journey.map((step, i) => (
                <li key={`${step.turn}-${i}`}>
                  <button onClick={() => onRead(step.message_id)}>
                    <span>
                      {step.turn === 0 ? "序章" : `第 ${step.turn} 回合`}
                    </span>
                    <CaretRight size={14} />
                  </button>
                  {!step.changes?.some((change) => change.kind !== "时间") &&
                    !step.gains?.length &&
                    !step.losses?.length && <p>{step.summary}</p>}
                  {step.changes?.map((change, j) => (
                    <small key={j}>
                      <span>{change.kind}</span>
                      {change.after}
                    </small>
                  ))}
                  {step.gains?.map((gain, j) => (
                    <small key={`g-${j}`}>
                      <span>获得</span>
                      {gain.text}
                    </small>
                  ))}
                  {step.losses?.map((loss, j) => (
                    <small key={`l-${j}`}>
                      <span>消耗</span>
                      {loss.text}
                    </small>
                  ))}
                  {step.events?.map((event, j) => (
                    <small key={`event-${j}`}>
                      <span>已知事件</span>
                      {event}
                    </small>
                  ))}
                </li>
              ))}
            </ol>
            {!journey.length && <p className="muted">故事尚未展开。</p>}
          </>
        )}
      </section>
    </div>
  );
}

export function SaveRail({
  view,
  loadEarlier,
  historyBusy,
  saves = [],
  navigate,
  rounds,
  selectedId,
  onRead,
  busy,
  saveState,
}) {
  return (
    <div className="workspace-rail-content">
      <button className="back-link" onClick={() => navigate("/play")}>
        <ArrowLeft size={16} />
        故事大厅
      </button>
      <div className="workspace-story">
        <BookCover story={view.story || { title: view.save.story_title }} />
        <h2>{view.save.story_title}</h2>
        <details>
          <summary>剧本介绍</summary>
          <p>
            {view.story?.introduction || "进入这个世界，用你的选择展开故事。"}
          </p>
        </details>
      </div>
      <div className="workspace-save-heading">
        <BookOpen size={17} />
        <span>{view.status.name}的旅程</span>
        <small>{rounds.length} 页</small>
      </div>
      <div className="workspace-save-status" aria-live="polite">
        <Check size={13} />
        {busy ? saveState : "已自动保存"}
      </div>
      {view.history_before && <button className="text-button" disabled={historyBusy} onClick={loadEarlier}>{historyBusy ? "正在加载……" : "加载更早回合"}</button>}
      <nav className="workspace-rounds" aria-label="回合记录">
        {rounds
          .slice()
          .reverse()
          .map((round, i) => (
            <button
              key={round.id}
              aria-current={selectedId === round.id ? "page" : undefined}
              onClick={() => onRead(round.id)}
            >
              <span>
                {round.turn === 0
                  ? "序章"
                  : `第 ${round.turn ?? rounds.length - i - 1} 回合`}
              </span>
              <small>
                {actionLabel(round.progress?.action) ||
                  round.progress?.summary ||
                  "故事开场"}
              </small>
            </button>
          ))}
        {!rounds.length && <p className="muted">生成开场后开始记录</p>}
      </nav>
      <details className="workspace-other-saves">
        <summary>切换存档</summary>
        {saves.length ? (
          saves.map((save) => (
            <button
              key={save.id}
              disabled={busy || save.id === view.save.id}
              onClick={() => navigate(`/play/saves/${save.id}`)}
            >
              <span>{save.name}</span>
              <span className="muted">
                {save.story_title} · {save.turn} 回合
              </span>
            </button>
          ))
        ) : (
          <p className="muted">没有其他存档</p>
        )}
      </details>
      <button
        className="workspace-new-story"
        disabled={busy}
        onClick={() => navigate(`/play/stories/${view.save.story_id}`)}
      >
        以新的身份开始
        <CaretRight size={16} />
      </button>
    </div>
  );
}
