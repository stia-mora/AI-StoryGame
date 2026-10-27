import React, { useEffect, useRef, useState } from "react";
import { ArrowRight, BookOpen, Users } from "@phosphor-icons/react";

export const points = (micro = 0) => (Number(micro) / 1e6).toFixed(2);
export const actionLabel = (value = "") =>
  String(value)
    .replace(/^【快进至下一处关键抉择】/, "")
    .replace(/^【角色对话】/, "");
const fieldLabels = {
  quantity: "数量",
  count: "数量",
  value: "数值",
  level: "等级",
  type: "类别",
  status: "状态",
  relationship: "关系",
  condition: "状况",
  hp: "生命",
  max_hp: "生命上限",
  ac: "防御",
  role: "身份",
  unit: "单位",
};
export function description(value) {
  if (Array.isArray(value))
    return value.map(description).filter(Boolean).join(" · ");
  if (!value || typeof value !== "object") return String(value ?? "");
  const name = value.name || value.label || value.text || "";
  const detail = Object.entries(value)
    .filter(
      ([k, v]) =>
        !["name", "label", "text"].includes(k) && v != null && v !== "",
    )
    .map(([k, v]) =>
      k === "description"
        ? description(v)
        : `${fieldLabels[k] || k}：${description(v)}`,
    );
  return [name, ...detail].filter(Boolean).join(" · ");
}
export function Button({ children, quiet, ...props }) {
  return (
    <button
      className={quiet ? "player-button quiet" : "player-button"}
      {...props}
    >
      {children}
    </button>
  );
}
export function Notice({ children, error = false }) {
  return (
    <div
      className={`player-notice ${error ? "error" : ""}`}
      role={error ? "alert" : "status"}
    >
      {children}
    </div>
  );
}
export function Loading() {
  return (
    <main id="player-main" className="player-shell" aria-busy="true" aria-label="正在加载故事">
      <div className="player-skeleton" />
      <div className="player-skeleton short" />
      <p className="muted">正在打开故事……</p>
    </main>
  );
}
export function Empty({ title, children }) {
  return (
    <section className="player-empty" role="status">
      <p><strong>{title}</strong>{children && <> · {children}</>}</p>
    </section>
  );
}
export function Narration({ text }) {
  const inline = (s) =>
    String(s)
      .split(/(\*\*[^*]+\*\*)/g)
      .map((part, i) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={i}>{part.slice(2, -2)}</strong>
        ) : (
          part
        ),
      );
  return (
    <div className="narration">
      {String(text || "")
        .split(/\n\s*\n/)
        .filter(Boolean)
        .map((p, i) =>
          /^#{1,4}\s+/.test(p) ? (
            <h3 key={i}>{inline(p.replace(/^#{1,4}\s+/gm, ""))}</h3>
          ) : (
            <p key={i}>{inline(p)}</p>
          ),
        )}
    </div>
  );
}
export function StreamingNarration({ text = "" }) {
  const previous = useRef({ text: "", characters: [] });
  if (!text.startsWith(previous.current.text)) previous.current = { text: "", characters: [] };
  const added = Array.from(text.slice(previous.current.text.length));
  if (added.length) {
    previous.current = { text, characters: [...previous.current.characters, ...added.map((character, index) => ({ character, delay: index * 30 }))] };
  }
  return <div className="narration stream-narration">{previous.current.characters.map(({ character, delay }, index) => <span key={index} style={{ animationDelay: `${delay}ms` }}>{character}</span>)}</div>;
}
export function Receipt({ receipt }) {
  const [usage, setUsage] = useState(null);
  if (!receipt) return null;
  return (
    <details
      className="receipt"
      onToggle={async (e) => {
        if (e.currentTarget.open && !usage) {
          try {
            setUsage((await window.api.player.usage(receipt.request_id)).items);
          } catch {
            setUsage([]);
          }
        }
      }}
    >
      <summary>
        本轮实扣 {points(receipt.charged_micro)} 积分
        {receipt.partial ? " · 已保存部分回复" : ""}
      </summary>
      <p>
        输入 {receipt.input_tokens.toLocaleString()} Token · 输出{" "}
        {receipt.output_tokens.toLocaleString()} Token · 费率版本{" "}
        {receipt.rate_version}
      </p>
      {receipt.platform_micro > 0 && (
        <p>超过封顶部分由平台承担：{points(receipt.platform_micro)} 积分</p>
      )}
      {usage?.map((u, i) => (
        <p key={i}>
          {u.phase === "curator"
            ? "理解行动与准备上下文"
            : u.phase === "guide_plan"
              ? "查询局势与人物资料"
            : u.phase === "guide" || u.phase === "player_guide"
              ? "游玩助手咨询"
              : u.phase === "reply"
                ? "生成回复"
                : !u.billable
                  ? "平台维护或失败尝试"
                  : "本轮调用"}{" "}
          · 输入 {u.input_tokens} / 输出 {u.output_tokens}
          {u.cached_tokens > 0 ? ` / 缓存 ${u.cached_tokens}` : ""}
          {u.reasoning_tokens > 0
            ? ` / 推理 ${u.reasoning_tokens}（已含在输出中）`
            : ""}
          {!u.billable ? " · 平台承担" : ""}
        </p>
      ))}
      <p>
        完整扣费精度：{Number(receipt.charged_micro) / 1e6}{" "}
        积分。输入包含设定、历史与检索资料。
      </p>
    </details>
  );
}
export function BookCover({ story, large = false }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [story.cover]);
  const [title, ...subtitle] = story.title.split(/[·｜|：:]/);
  return (
    <div className={`book-cover ${large ? "large" : ""}`} aria-hidden="true">
      {story.cover && !failed ? (
        <img src={story.cover} alt="" loading="lazy" onError={() => setFailed(true)} />
      ) : (
        <>
          <BookOpen size={24} weight="light" className="cover-mark" />
          <span className="cover-title">{title.trim()}</span>
          {subtitle.length > 0 && <span className="cover-subtitle">{subtitle.join(" · ").trim()}</span>}
        </>
      )}
    </div>
  );
}
export function StoryCard({ story, onStart, onComments }) {
  return (
    <article className="story-card entry-story" aria-labelledby={`story-title-${story.id}`}>
      <BookCover story={story} />
      <div className="story-copy">
        <div className="story-card-heading">
          <span className="story-meta"><Users size={15} aria-hidden="true" />{story.identities.length} 种可选身份</span>
          <h3 id={`story-title-${story.id}`}>{story.title}</h3>
        </div>
        {story.introduction && <p className="story-introduction">{story.introduction}</p>}
        {story.author && <p className="story-meta">{story.author}{story.version ? ` · v${story.version}` : ""}</p>}
        <div className="story-card-actions"><Button quiet onClick={onStart}>
          开始故事 <ArrowRight size={18} />
        </Button>{onComments && <button className="text-button" aria-label={`查看${story.title}的评论`} onClick={onComments}>评论</button>}</div>
      </div>
    </article>
  );
}
