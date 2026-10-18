import React, { useId, useState } from "react";
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
} from "@phosphor-icons/react";
import { BookCover, description, actionLabel } from "./shared.jsx";
import { TurnProgress } from "./Progress.jsx";

const tabs = [
  ["overview", "局势", Target],
  ["character", "角色", User],
  ["inventory", "背包", Package],
  ["people", "人物", Users],
  ["tasks", "任务", ListChecks],
  ["worldline", "世界线", GitBranch],
];

function Records({ title, values, empty = "尚无记录" }) {
  const items = Array.isArray(values) ? values : values ? [values] : [];
  return (
    <details className="workspace-records" open>
      <summary>
        {title}
        <span>{items.length || "—"}</span>
      </summary>
      {items.length ? (
        <ul>
          {items.map((item, i) => (
            <li key={i}>{description(item)}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">{empty}</p>
      )}
    </details>
  );
}

export function InformationPanel({ view, onRead }) {
  const [tab, setTab] = useState("overview");
  const panelId = useId();
  const { status, latest_progress: progress, journey = [] } = view;
  return (
    <div className="workspace-information">
      <div className="workspace-tabs" role="tablist" aria-label="存档信息">
        {tabs.map(([id, title, Icon]) => (
          <button
            key={id}
            role="tab"
            id={`${panelId}-tab-${id}`}
            aria-controls={`${panelId}-panel-${id}`}
            aria-selected={id === tab}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => setTab(id)}
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
              setTab(tabs[next][0]);
              const nextTab =
                e.currentTarget.parentElement?.querySelectorAll('[role="tab"]')[
                  next
                ];
              nextTab?.focus();
            }}
          >
            <Icon size={17} />
            {title}
            {progress?.panels?.includes(title) && (
              <span className="workspace-tab-change" aria-label="本轮已更新" />
            )}
          </button>
        ))}
      </div>
      <div className="workspace-world-id">
        <User size={17} />
        <strong>{status.name}</strong>
        <small>存档 {view.save.id}</small>
      </div>
      <section
        className="workspace-information-scroll"
        role="tabpanel"
        id={`${panelId}-panel-${tab}`}
        aria-labelledby={`${panelId}-tab-${tab}`}
        tabIndex={0}
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
