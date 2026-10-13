import React, { useEffect, useRef, useState } from "react";
import { X, ArrowRight } from "@phosphor-icons/react";

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
    <main className="player-shell" aria-busy="true">
      <div className="player-skeleton" />
      <div className="player-skeleton short" />
      <p className="muted">正在打开故事……</p>
    </main>
  );
}
export function Empty({ title, children }) {
  return (
    <section className="player-empty">
      <h2>{title}</h2>
      <p>{children}</p>
    </section>
  );
}
export function Drawer({ title, onClose, children }) {
  const ref = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const old = document.activeElement;
    ref.current?.querySelector("button")?.focus();
    const key = (event) => {
      if (event.key === "Escape") closeRef.current();
      if (event.key === "Tab") {
        const items = Array.from(
          ref.current?.querySelectorAll(
            'button,a,input,textarea,select,[tabindex="0"]',
          ) || [],
        ).filter(
          (node) =>
            !node.disabled &&
            node.tabIndex >= 0 &&
            node.getClientRects().length,
        );
        if (!items?.length) return;
        const first = items[0],
          last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = previous;
      old?.focus();
    };
  }, []);
  return (
    <div className="drawer-backdrop">
      <button
        className="drawer-shade"
        aria-label="关闭面板"
        onClick={onClose}
      />
      <aside
        className="player-drawer"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={ref}
      >
        <header>
          <h2>{title}</h2>
          <button className="icon-button" onClick={onClose} aria-label="关闭">
            <X size={22} />
          </button>
        </header>
        {children}
      </aside>
    </div>
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
  return (
    <div className={`book-cover ${large ? "large" : ""}`} aria-hidden="true">
      {story.cover ? (
        <img src={story.cover} alt="" />
      ) : (
        <>
          <div className="cover-orbit" />
          <div className="cover-mountain back" />
          <div className="cover-mountain" />
          <span className="cover-title">{story.title.split(/[·｜|]/)[0]}</span>
          <span className="cover-caption">一个世界 · 你的选择</span>
        </>
      )}
    </div>
  );
}
export function StoryCard({ story, onStart }) {
  return (
    <article className="story-card">
      <BookCover story={story} />
      <div className="story-copy">
        <span className="eyebrow">可游玩故事</span>
        <h2>{story.title}</h2>
        <p>{story.introduction}</p>
        <Button onClick={onStart}>
          走进故事 <ArrowRight size={18} />
        </Button>
      </div>
    </article>
  );
}
