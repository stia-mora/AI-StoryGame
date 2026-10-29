import React, { useEffect, useState } from "react";
import { Button, Notice } from "./shared.jsx";
import { authoringRequest as request, authoringStatus as statusName } from "./authoring-api.js";
import "./authoring.css";

export { Authoring } from "./AuthoringHome.jsx";

export function AuthoringAdmin({ navigate }) {
  const [data, setData] = useState(null), [error, setError] = useState(""), [message, setMessage] = useState("");
  const [profile, setProfile] = useState(""), [reason, setReason] = useState(""), [busy, setBusy] = useState(false);
  const [amount, setAmount] = useState(1000), [purpose, setPurpose] = useState("preview");
  const [inspection, setInspection] = useState(null), [submission, setSubmission] = useState("");
  const inspect = async (id, offset = 0) => {
    setInspection(await request(`/api/authoring/admin/submissions/${id}?offset=${offset}`));
    setSubmission(id);
  };
  const load = async () => { const value = await request("/api/authoring/admin"); setData(value); setProfile(String(value.config.preview_profile_id || "")); };
  useEffect(() => { load().catch(e => setError(e.message)); }, []);
  const run = async (fn) => { setBusy(true); setError(""); setMessage(""); try { await fn(); await load(); } catch (e) { setError(e.message); } finally { setBusy(false); } };
  return <main id="player-main" className="player-shell authoring-page"><div className="authoring-toolbar"><h1>创作审批</h1><Button quiet onClick={() => navigate("/play/authoring")}>返回创作</Button></div>
    {error && <Notice error>{error}</Notice>}{message && <p role="status">{message}</p>}
    {!data ? <><p role="status">正在读取审批信息……</p>{error && <Button onClick={() => run(async () => {})}>重新加载</Button>}</> : <>
      <section><h2>试玩服务模型</h2><label>模型<select value={profile} onChange={e => setProfile(e.target.value)}><option value="">请选择</option>
        {data.profiles.filter(p => p.enabled).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <Button disabled={busy || !profile} onClick={() => run(() => request("/api/authoring/admin", { action: "configure", profile_id: Number(profile) }))}>保存试玩模型</Button></section>
      <section><h2>上架申请</h2><label>拒绝原因<input value={reason} onChange={e => setReason(e.target.value)} maxLength={2000} /></label>
        {data.submissions.length === 0 && <p>暂无申请。</p>}{data.submissions.map(item => <article key={item.id}><h3>{item.title} · v{item.version}</h3>
          <p>{item.username} · {statusName(item.status)}</p><p>{item.rights_note}</p>{item.reason && <p>{item.reason}</p>}
          <Button quiet disabled={busy} onClick={() => run(() => inspect(item.id))}>审阅内容与试玩记录</Button>
          <details><summary>校验报告</summary><pre>{JSON.stringify(item.report, null, 2)}</pre></details>
          {item.status === "pending_review" && <><Button disabled={busy || !profile} onClick={() => run(() => request("/api/authoring/admin", { action: "approve", submission_id: item.id, profile_id: Number(profile) }))}>批准上架</Button>
            <Button quiet disabled={busy || !reason.trim()} onClick={() => run(() => request("/api/authoring/admin", { action: "reject", submission_id: item.id, reason }))}>拒绝</Button></>}
          {item.status === "published" && <Button quiet disabled={busy || !reason.trim()} onClick={() => run(() => request("/api/authoring/admin", { action: "suspend", submission_id: item.id, reason }))}>暂停游玩</Button>}
        </article>)}</section>
      {inspection && <section><h2>版本内容审阅</h2><details open><summary>契约与实际试玩记录</summary><pre>{JSON.stringify({ contract: inspection.contract, playtests: inspection.playtests }, null, 2)}</pre></details>
        {inspection.chapters.map(ch => <article key={ch.chapter_index}><h3>{ch.title}</h3><p className="authoring-chapter">{ch.content}</p></article>)}
        <Button quiet disabled={busy || !inspection.offset} onClick={() => run(() => inspect(submission, Math.max(0, inspection.offset - 10)))}>前十章</Button>
        <Button quiet disabled={busy || inspection.chapters.length < 10} onClick={() => run(() => inspect(submission, inspection.offset + 10))}>后十章</Button>
      </section>}
      <section><h2>发行兑换码</h2><label>用途<select value={purpose} onChange={e => setPurpose(e.target.value)}><option value="preview">创作者专用试玩</option><option value="player">普通游玩</option></select></label>
        <label>积分<input type="number" min="1" max="1000000" value={amount} onChange={e => setAmount(e.target.value)} /></label>
        <Button disabled={busy || Number(amount) <= 0} onClick={() => run(async () => {
          const value = await request("/api/admin/player/codes", { points: Number(amount), purpose, max_uses: 1, label: purpose === "preview" ? "创作者试玩" : "普通游玩" });
          setMessage(`兑换码（仅展示本次）：${value.code}`);
        })}>生成兑换码</Button></section>
    </>}
  </main>;
}
