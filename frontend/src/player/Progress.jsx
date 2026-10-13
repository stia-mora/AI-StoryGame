import React from "react";
import {
  GitBranch,
  MapPin,
  Package,
  Target,
  ArrowRight,
  Sparkle,
} from "@phosphor-icons/react";
import { description } from "./shared.jsx";

export function TurnProgress({ progress, turn, latest = false }) {
  if (!progress) return null;
  const content = (
    <div className="turn-progress-body">
      {progress.events?.length > 0 && (
        <div className="progress-events">
          {progress.events.map((event, i) => (
            <p key={i}>{event}</p>
          ))}
        </div>
      )}
      {progress.panels?.length > 0 && (
        <p className="progress-updated">
          本轮更新：{progress.panels.join(" · ")}
        </p>
      )}
      <div className="progress-sections">
        <section>
          <h4>
            <Package size={16} /> 本轮收获
          </h4>
          {progress.gains?.length ? (
            <ul>
              {progress.gains.map((item, i) => (
                <li key={i}>
                  <span>{item.kind}</span>
                  {item.text}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">本轮没有记录新增物品、能力或资源。</p>
          )}
          {progress.losses?.length > 0 && (
            <div className="progress-losses">
              <span>消耗与失去</span>
              {progress.losses.map((item, i) => (
                <p key={i}>{item.text}</p>
              ))}
            </div>
          )}
        </section>
        <section>
          <h4>
            <GitBranch size={16} /> 世界线变化
          </h4>
          {progress.changes?.length ? (
            <ul>
              {progress.changes.map((item, i) => (
                <li key={i}>
                  <span>{item.kind}</span>
                  {item.before && (
                    <>
                      <small>{item.before}</small>
                      <ArrowRight size={12} />
                    </>
                  )}
                  {item.after}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">暂未记录新的局势变化，故事正在继续。</p>
          )}
        </section>
      </div>
    </div>
  );
  return latest ? (
    <section className="turn-progress" aria-label="本轮进展">
      <header>
        <span className="eyebrow">这一页留下了什么</span>
        <span className="progress-saved">已随故事保存</span>
      </header>
      {content}
    </section>
  ) : (
    <details className="turn-progress historical">
      <summary>
        查看这一步的收获与变化{turn != null && ` · 第 ${turn} 回合`}
      </summary>
      {content}
    </details>
  );
}

export function Journey({ status, progress, journey = [] }) {
  return (
    <aside className="journey-panel" aria-label="当前局势与世界线">
      <div className="journey-heading">
        <span className="character-seal">{status.name?.slice(-2)}</span>
        <div>
          <span className="eyebrow">此刻的你</span>
          <h2>{status.name}</h2>
        </div>
      </div>
      <section className="current-situation">
        <h3>
          <MapPin size={15} /> 当前地点
        </h3>
        <p>{description(status.location) || "地点尚未记录"}</p>
        {status.time && <small>{description(status.time)}</small>}
        <h3>
          <Target size={15} /> 眼前的目标
        </h3>
        <p>
          {description(status.objective) ||
            "先观察眼前的场景，决定你的第一步。"}
        </p>
      </section>
      <section className="previous-step">
        <h3>上一步进展</h3>
        <p>{progress?.summary || "故事即将从这里展开。"}</p>
        {progress?.gains?.length > 0 && (
          <div className="recent-gain">
            <Sparkle size={16} />
            <span>{progress.gains.map((g) => g.text).join(" · ")}</span>
          </div>
        )}
      </section>
      <section className="worldline-trail">
        <h3>
          <GitBranch size={16} /> 你的世界线
        </h3>
        <ol>
          {journey.slice(-4).map((step, i) => (
            <li key={`${step.turn}-${i}`}>
              <span className="trail-node" />
              <span className="eyebrow">
                {step.turn === 0 ? "序章" : `第 ${step.turn} 回合`}
              </span>
              <p>
                {step.changes?.find((c) => c.kind === "世界线")?.after ||
                  step.changes?.find(
                    (c) => c.kind === "目标" || c.kind === "地点",
                  )?.after ||
                  step.summary ||
                  "局势继续发展"}
              </p>
            </li>
          ))}
        </ol>
        {!journey.length && <p className="muted">你的选择会在这里留下足迹。</p>}
      </section>
    </aside>
  );
}
