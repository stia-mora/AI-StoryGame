import React, { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, CaretLeft, CaretRight, MagnifyingGlass } from "@phosphor-icons/react";
import { Button, Empty, Loading, Notice, points } from "./shared.jsx";

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
  const [wallet, setWallet] = useState(null);
  const [code, setCode] = useState(""), [message, setMessage] = useState(""), [error, setError] = useState("");
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true);
  const [ledgerError, setLedgerError] = useState("");
  const emptyFilters = { q: "", kind: "", date_from: "", date_to: "" };
  const [draft, setDraft] = useState(emptyFilters), [filters, setFilters] = useState(emptyFilters);
  const [page, setPage] = useState(1), [revision, setRevision] = useState(0);
  const [result, setResult] = useState({ items: [], total: 0, pages: 1, page: 1 });
  const redeemBlocked = wallet && wallet.free_micro + wallet.permanent_micro + wallet.held_micro > 5000 * 1e6;
  const load = async () => {
    const value = await window.api.player.wallet();
    setWallet(value);
    setError("");
    setRevision((value) => value + 1);
  };
  useEffect(() => { load().catch((e) => setError(e.message)); }, []);
  useEffect(() => {
    let current = true;
    setLoading(true);
    setLedgerError("");
    window.api.player.ledger({ ...filters, page, page_size: 10 })
      .then((value) => { if (current) { setResult(value); if (value.page !== page) setPage(value.page); } })
      .catch((e) => { if (current) setLedgerError(e.message); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [filters, page, revision]);
  const pager = (
    <nav className="ledger-pagination" aria-label="积分明细分页">
      <span aria-live="polite">共 {result.total} 条 · 第 {result.page} / {result.pages} 页</span>
      <button className="icon-button" aria-label="上一页明细" disabled={loading || page <= 1} onClick={() => setPage(page - 1)}><CaretLeft size={18} /></button>
      <div className="ledger-page-numbers">
        {Array.from({ length: Math.min(5, result.pages) }, (_, i) => Math.max(1, Math.min(page - 2, result.pages - 4)) + i).map((number) => (
          <button key={number} aria-label={`第 ${number} 页`} aria-current={page === number ? "page" : undefined} disabled={loading} onClick={() => setPage(number)}>{number}</button>
        ))}
      </div>
      <button className="icon-button" aria-label="下一页明细" disabled={loading || page >= result.pages} onClick={() => setPage(page + 1)}><CaretRight size={18} /></button>
    </nav>
  );
  const redeem = async (e) => {
    e.preventDefault();
    if (redeemBlocked) return;
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
      <main id="player-main" className="player-shell">
        <Notice error>{error}</Notice>
        <Button onClick={() => load().catch((e) => setError(e.message))}>重新加载</Button>
      </main>
    ) : (
      <Loading />
    );
  return (
    <main id="player-main" className="player-shell wallet-page">
      <button className="back-link" onClick={() => navigate("/play")}>
        <ArrowLeft size={18} /> 故事大厅
      </button>
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
          <Button disabled={busy || redeemBlocked || !code.trim()}>
            兑换 <ArrowRight size={17} />
          </Button>
        </form>
        {redeemBlocked && <Notice>当前游玩积分（含预留）已超过 5000，请先使用已有积分后再兑换。</Notice>}
        {error && <Notice error>{error}</Notice>}
        {message && <Notice>{message}</Notice>}
      </section>
      <section className="ledger-section" aria-labelledby="ledger-title">
        <h2 id="ledger-title">积分明细</h2>
        <form className="ledger-filters" onSubmit={(event) => {
          event.preventDefault();
          if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) { setLedgerError("开始日期不能晚于结束日期"); return; }
          setPage(1); setFilters({ ...draft, q: draft.q.trim() });
        }}>
          <label className="ledger-query"><MagnifyingGlass size={18} aria-hidden="true" /><input aria-label="查询积分明细" placeholder="搜索故事、存档或备注" maxLength={120} value={draft.q} onChange={(e) => setDraft({ ...draft, q: e.target.value })} /></label>
          <label><span className="sr-only">变动类型</span><select aria-label="变动类型" value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}><option value="">全部类型</option>{Object.entries(names).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>
          <label className="ledger-date">开始日期<input type="date" aria-label="开始日期" value={draft.date_from} onChange={(e) => setDraft({ ...draft, date_from: e.target.value })} /></label>
          <label className="ledger-date">结束日期<input type="date" aria-label="结束日期" value={draft.date_to} onChange={(e) => setDraft({ ...draft, date_to: e.target.value })} /></label>
          <Button type="submit">查询</Button>
          <Button quiet type="button" onClick={() => { setDraft(emptyFilters); setFilters(emptyFilters); setPage(1); }}>重置</Button>
        </form>
        <p className="ledger-timezone">日期按北京时间查询，每页 10 条。</p>
        {ledgerError ? <div><Notice error>{ledgerError}</Notice><Button quiet onClick={() => setRevision(revision + 1)}>重试明细查询</Button></div> : <>
          {pager}
          <div className="ledger-results" aria-busy={loading}>
            {loading ? <div className="ledger-loading" role="status">正在查询明细……<div className="player-skeleton short" /></div> : !result.items.length ? <Empty title="没有符合条件的明细">试试其他日期或类型。</Empty> : (
              <ul>{result.items.map((item) => (
                <li key={item.id}>
                  <div className="ledger-description">
                    <strong>{names[item.kind] || item.kind}</strong>
                    {(item.story_title || item.save_title) && <p>{[item.story_title, item.save_title].filter(Boolean).join(" · ")}</p>}
                    <p>{item.reason}</p>
                    <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}</time>
                  </div>
                  <div className="ledger-amount">
                    <span>{item.kind === "settle" ? `实扣 ${points(item.charged_micro)}` : `${item.free_delta + item.permanent_delta > 0 ? "+" : ""}${points(item.free_delta + item.permanent_delta)}`} 积分</span>
                    {item.held_delta !== 0 && <small>预留 {item.held_delta > 0 ? "+" : ""}{points(item.held_delta)}</small>}
                    <small>精确变动 {(item.free_delta + item.permanent_delta) / 1e6}</small>
                  </div>
                </li>
              ))}</ul>
            )}
          </div>
        </>}
      </section>
    </main>
  );
}
