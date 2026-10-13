import React, { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight } from "@phosphor-icons/react";
import { Button, Loading, Notice, points } from "./shared.jsx";

const names = {
  daily: "每日免费积分",
  expire: "免费积分到期",
  reserve: "回合预留",
  settle: "回合结算",
  release: "预留释放",
  redeem: "兑换码",
  grant: "管理员发放",
};
export function Wallet({ refresh, navigate }) {
  const [wallet, setWallet] = useState(null),
    [items, setItems] = useState([]),
    [code, setCode] = useState(""),
    [message, setMessage] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [hasMore, setHasMore] = useState(false),
    [loadingMore, setLoadingMore] = useState(false);
  const load = async () => {
    try {
      const [w, l] = await Promise.all([
        window.api.player.wallet(),
        window.api.player.ledger(),
      ]);
      setWallet(w);
      setItems(l.items);
      setHasMore(l.items.length === 50);
    } catch (e) {
      setError(e.message);
    }
  };
  useEffect(() => {
    load();
  }, []);
  const redeem = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await window.api.player.redeem(code);
      setCode("");
      setMessage("兑换成功，积分已加入长期余额。");
      await load();
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  if (!wallet)
    return error ? (
      <main className="player-shell">
        <Notice error>{error}</Notice>
        <Button onClick={load}>重新加载</Button>
      </main>
    ) : (
      <Loading />
    );
  return (
    <main id="player-main" className="player-shell wallet-page">
      <button className="back-link" onClick={() => navigate("/play")}>
        <ArrowLeft size={18} /> 故事书架
      </button>
      <span className="eyebrow">让故事继续</span>
      <h1>我的积分</h1>
      <div className="wallet-balances">
        {[
          ["今日免费", wallet.free_micro, "北京时间零点刷新，当日有效"],
          ["长期积分", wallet.permanent_micro, "兑换或发放所得，不随日期清零"],
          ["正在预留", wallet.held_micro, "回合保存后结算，余量自动退回"],
        ].map(([label, value, help]) => (
          <section key={label}>
            <h2>{label}</h2>
            <strong>{points(value)}</strong>
            <p>{help}</p>
          </section>
        ))}
      </div>
      <p className="billing-policy">
        每 1000 输入 Token {wallet.rates.input} 积分 · 每 1000 输出 Token{" "}
        {wallet.rates.output}{" "}
        积分。优先使用今日免费积分；每轮发送前显示估算和封顶费用。创建角色和阅读存档免费，失败且未保存的回合不扣费。
      </p>
      <section className="redeem-section">
        <h2>兑换积分</h2>
        <form onSubmit={redeem}>
          <label className="sr-only" htmlFor="redeem-code">
            兑换码
          </label>
          <input
            id="redeem-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="输入兑换码"
            autoComplete="off"
            maxLength={120}
            required
          />
          <Button disabled={busy || !code.trim()}>
            兑换 <ArrowRight size={17} />
          </Button>
        </form>
        {error && <Notice error>{error}</Notice>}
        {message && <Notice>{message}</Notice>}
      </section>
      <section className="ledger-section">
        <h2>积分明细</h2>
        {!items.length ? (
          <p className="muted">还没有积分变动。</p>
        ) : (
          <ul>
            {items.map((i) => (
              <li key={i.id}>
                <div>
                  <strong>{names[i.kind] || i.kind}</strong>
                  <p>{i.reason}</p>
                  <time>{new Date(i.created_at).toLocaleString("zh-CN")}</time>
                </div>
                <div className="ledger-amount">
                  <span>
                    {i.kind === "settle"
                      ? `实扣 ${points(i.charged_micro)}`
                      : points(i.free_delta + i.permanent_delta)}{" "}
                    积分
                  </span>
                  {i.held_delta !== 0 && (
                    <small>
                      预留 {i.held_delta > 0 ? "+" : ""}
                      {points(i.held_delta)}
                    </small>
                  )}
                  <small>
                    精确变动 {(i.free_delta + i.permanent_delta) / 1e6}
                  </small>
                </div>
              </li>
            ))}
          </ul>
        )}
        {hasMore && (
          <Button
            quiet
            disabled={loadingMore}
            onClick={async () => {
              setLoadingMore(true);
              try {
                const more = await window.api.player.ledger(
                  items[items.length - 1].id,
                );
                setItems((previous) => [...previous, ...more.items]);
                setHasMore(more.items.length === 50);
              } catch (e) {
                setError(e.message);
              } finally {
                setLoadingMore(false);
              }
            }}
          >
            加载更早明细
          </Button>
        )}
      </section>
    </main>
  );
}
