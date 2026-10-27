import React, { useCallback, useEffect, useState } from "react";
import { Button, Loading, Notice, points } from "./shared.jsx";
import "./authoring.css";

async function request(path, body) {
  const response = await fetch(path, { credentials: "include", ...(body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }) });
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail || value.error || "操作未完成，请重试");
  return value;
}
const act = (name, data) => request(`/api/authoring/action/${name}`, data);
const statusName = value => ({ pending: "排队中", running: "执行中", succeeded: "已完成", failed: "未完成", pending_review: "待审批", published: "已上架", rejected: "已拒绝" }[value] || value);

export function Authoring({ navigate, admin = false }) {
  const [data, setData] = useState(null), [draft, setDraft] = useState(null);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [title, setTitle] = useState(""), [rights, setRights] = useState(""), [code, setCode] = useState("");
  const [identity, setIdentity] = useState(""), [pats, setPats] = useState([]), [token, setToken] = useState("");
  const [selectedVersion, setSelectedVersion] = useState(0);
  const load = useCallback(async () => {
    const result = await request("/api/authoring");
    setData(result);
    const listed = await window.api.federation.patList();
    setPats(listed.items || listed.pats || []);
  }, []);
  const open = useCallback(async (id, version) => {
    const value = await act("get_draft", { project_id: id, ...(version ? { version: Number(version) } : {}) });
    setDraft(value); setRights(value.revisions[0]?.rights_note || "");
    setIdentity(value.revisions[0]?.contract.play.identities[0]?.id || "");
    setSelectedVersion(value.revisions[0]?.version || 0);
  }, []);
  useEffect(() => {
    load().catch(e => setError(e.message));
    const project = new URLSearchParams(window.location.search).get("project");
    if (project) open(project).catch(e => setError(e.message));
  }, [load, open]);
  const run = async (fn) => {
    setBusy(true); setError(""); setNotice("");
    try { await fn(); await load(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const current = draft?.revisions[0];
  return <main id="player-main" className="player-shell authoring-page">
    <div className="authoring-toolbar"><h1>我的创作</h1><Button quiet onClick={() => navigate("/play")}>返回大厅</Button>
      {admin && <Button quiet onClick={() => navigate("/play/authoring-admin")}>创作审批</Button>}</div>
    {data?.author && <p>作者：{data.author}</p>}
    {error && <Notice error>{error}</Notice>}{notice && <p role="status">{notice}</p>}
    {!data ? <><Loading />{error && <Button onClick={() => load().catch(e => setError(e.message))}>重新加载</Button>}</> : <>
      <section aria-labelledby="preview-balance"><h2 id="preview-balance">专用试玩积分</h2>
        <p>可用 {points(data.wallet.preview_micro)} · 预留 {points(data.wallet.preview_held_micro)} 积分</p>
        <p>首次赠送 10,000 积分，不到期，仅用于你自己的作品试玩。普通游玩余额单独计算。</p>
        <form onSubmit={e => { e.preventDefault(); run(async () => { await act("redeem", { code }); setCode(""); setNotice("兑换成功，积分已到账。"); }); }}>
          <label>兑换码<input value={code} onChange={e => setCode(e.target.value)} required maxLength={120} autoComplete="off" /></label>
          <Button disabled={busy}>兑换</Button></form>
      </section>
      <section aria-labelledby="agent-connect"><h2 id="agent-connect">连接自己的 Agent</h2>
        <label>MCP 地址<input readOnly value={data.endpoint} onFocus={e => e.target.select()} /></label>
        <p>在 Codex 或 Claude Code 中添加远程 MCP，使用浏览器登录授权。Agent 使用自己的模型编制作品，平台提供规范、校验、试玩和提交。</p>
        <details><summary>使用个人令牌接入</summary>
          <Button disabled={busy} onClick={() => run(async () => {
            const value = await window.api.federation.patCreate({ name: "创作 Agent", scopes: data.scopes });
            setToken(value.token);
          })}>生成创作令牌</Button>
          {token && <label>令牌仅展示本次，请妥善保存<input readOnly value={token} onFocus={e => e.target.select()} autoComplete="off" /></label>}
          {pats.map(pat => <div className="authoring-row" key={pat.id}><span>{pat.name} {pat.revoked_at ? "已撤销" : ""}</span>
            {!pat.revoked_at && <Button quiet disabled={busy} onClick={() => run(() => window.api.federation.patRevoke(pat.id))}>撤销</Button>}</div>)}
        </details>
      </section>
      <section aria-labelledby="projects"><h2 id="projects">项目与版本</h2>
        <form onSubmit={e => { e.preventDefault(); run(async () => {
          const value = await act("create_project", { project_key: crypto.randomUUID(), title }); setTitle(""); await open(value.id);
        }); }}><label>新项目名称<input value={title} onChange={e => setTitle(e.target.value)} required maxLength={180} /></label><Button disabled={busy}>创建项目</Button></form>
        {!data.projects.length && <p>创建项目，或让 Agent 调用创作工具创建并上传私人草稿。</p>}
        {data.projects.map(project => <div className="authoring-row" key={project.id}>
          <span>{project.title} · v{project.version}</span><Button quiet disabled={busy} onClick={() => run(() => open(project.id))}>查看版本</Button></div>)}
        {draft && <div className="authoring-detail"><h3>{draft.project.title}</h3><p>项目编号：<code>{draft.project.id}</code></p>
          {draft.jobs.map(job => <p key={job.id}>{job.kind === "import" ? "内容导入" : "作品试玩"} · {statusName(job.status)}{job.error && `：${job.error}`}</p>)}
          <Button quiet disabled={busy} onClick={() => run(() => open(draft.project.id, current?.version))}>刷新任务与版本</Button>
          {!!draft.project.version && <form onSubmit={e => { e.preventDefault(); run(() => open(draft.project.id, selectedVersion)); }}>
            <label>查看历史版本<input type="number" min="1" max={draft.project.version} value={selectedVersion} onChange={e => setSelectedVersion(e.target.value)} required /></label>
            <Button quiet disabled={busy}>打开指定版本</Button>
          </form>}
          {current && <><p>当前版本 v{current.version}</p>
            <p>结构：{current.report.valid ? "通过" : "未通过"} · 语义质量：待人工核对</p>
            <p>实际试玩：{current.report.checks?.playtest === "passed" ? "已有成功保存的回复" : "尚未执行成功"}</p>
            {current.playtests?.map(item => <p key={item.id}>试玩 {statusName(item.status)}{item.error && `：${item.error}`}</p>)}
            {current.contract.completeness.unresolved?.map((item, index) => <p key={index}>待办：{item}</p>)}
            <label>试玩身份<select value={identity} onChange={e => setIdentity(e.target.value)}>
              {current.contract.play.identities.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <Button disabled={busy} onClick={() => run(async () => {
              const result = await act("preview", { mode: "create", revision_id: current.id, identity_id: identity, request_id: crypto.randomUUID(), name: "旅人" });
              navigate(result.url);
            })}>免费创建试玩存档</Button>
            <label>来源与授权说明<textarea value={rights} onChange={e => setRights(e.target.value)} maxLength={2000} rows={3} /></label>
            <Button disabled={busy || !rights.trim()} onClick={() => run(async () => {
              await act("review", { revision_id: current.id, rights_note: rights }); await open(draft.project.id, current.version); setNotice("此版本已标记作者复核。");
            })}>确认已复核此版本</Button>
            <Button disabled={busy || !current.reviewed_at} onClick={() => run(async () => {
              await act("submit", { revision_id: current.id }); await open(draft.project.id, current.version); setNotice("已提交，等待管理员审批。");
            })}>提交上架审批</Button>
            {draft.submissions.filter(item => item.revision_id === current.id).map(item => <p key={item.id}>v{current.version} · {statusName(item.status)}{item.reason && `：${item.reason}`}</p>)}
            <details><summary>内容配置与校验报告</summary><pre>{JSON.stringify({ fingerprint: current.fingerprint, contract: current.contract, report: current.report }, null, 2)}</pre></details>
          </>}
        </div>}
      </section>
      <section><h2>最近试玩积分记录</h2>{data.ledger.map(item => <div className="authoring-row" key={item.id}>
        <span>{item.reason}</span><span>可用 {points(item.preview_delta)} · 预留 {points(item.preview_held_delta)}</span></div>)}</section>
    </>}
  </main>;
}

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
    {!data ? <Loading /> : <>
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
