import React, { useEffect, useState } from "react";
import { points } from "./shared.jsx";

const unchanged = (s) => s;
export function ActionChoices({
  options,
  saveId,
  onSend,
  navigate,
  disabled = false,
  transform = unchanged,
}) {
  const [quotes, setQuotes] = useState({});
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setQuotes({});
    options.forEach(async (message) => {
      try {
        const quote = await window.api.player.quote({
          save_id: saveId,
          kind: "turn",
          message: transform(message),
        });
        if (active) setQuotes((old) => ({ ...old, [message]: { quote } }));
      } catch (error) {
        if (active)
          setQuotes((old) => ({ ...old, [message]: { error: error.message } }));
      }
    });
    const timer = setTimeout(() => setRevision((old) => old + 1), 60000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [options, saveId, revision, transform]);
  const unavailable = Object.values(quotes).some((item) => item.error);
  const insufficient = Object.values(quotes).some(
    (item) => item.quote && !item.quote.affordable,
  );
  return (
    <section className="action-options" aria-label="剧情选项">
      <div className="choices-heading">
        <h2>选择行动</h2>
        <span>点击即行动</span>
      </div>
      <div className="choices-grid">
        {options.map((message, i) => {
          const { quote, error } = quotes[message] || {};
          const letter = String.fromCharCode(65 + i);
          return (
            <button
              key={message}
              type="button"
              aria-label={`${letter} ${message}`}
              disabled={disabled || !quote?.affordable}
              onClick={() => onSend(transform(message), quote)}
            >
              <span>{letter}</span>
              <span className="choice-body">{message}</span>
              <span className="choice-cost">
                {quote
                  ? `预计 ${points(quote.estimate_micro)} · 封顶 ${points(quote.cap_micro)} 积分${quote.affordable ? "" : " · 余额不足"}`
                  : error || "正在估算费用……"}
              </span>
            </button>
          );
        })}
      </div>
      <p className="fine-print">封顶是本轮扣费上限，实扣按用量结算，未用预留自动退回。</p>
      {unavailable && (
        <button
          className="text-button"
          type="button"
          onClick={() => setRevision((old) => old + 1)}
        >
          重新获取选项费用
        </button>
      )}
      {insufficient && (
        <button
          className="text-button"
          type="button"
          onClick={() => navigate("/play/wallet")}
        >
          余额不足，查看积分与兑换码
        </button>
      )}
    </section>
  );
}
