import React, { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Coins, FolderOpen, PenNib, Plus } from "@phosphor-icons/react";
import { safeUUID } from "../lib/crypto-safe.js";
import { Button, Notice, points } from "./shared.jsx";
import { authoringRequest as request, authoringAction as act } from "./authoring-api.js";
import { AuthoringConnect } from "./AuthoringConnect.jsx";
import { AuthoringProject } from "./AuthoringProject.jsx";

export function Authoring({ navigate, navigation, admin = false, creator = true, refreshAccount }) {
  const [data, setData] = useState(null), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [title, setTitle] = useState(""), [code, setCode] = useState(""), [busy, setBusy] = useState(false);
  const [projectId, setProjectId] = useState(() => new URLSearchParams(location.search).get("project"));
  const [initialVersion, setInitialVersion] = useState(() => Number(new URLSearchParams(location.search).get("version")) || null);
  const projectRequest = useRef(null);
  const mounted = useRef(true);
  useEffect(() => {
    const lifecycle = mounted;
    lifecycle.current = true;
    return () => { lifecycle.current = false; };
  }, []);
  const load = useCallback(async () => { const value = await request("/api/authoring"); if (mounted.current) setData(value); }, []);
  useEffect(() => { if (creator) load().catch(e => setError(e.message)); }, [creator, load]);
  useEffect(() => {
    if (!navigation) return;
    const params = new URLSearchParams(navigation.search);
    setProjectId(params.get("project"));
    setInitialVersion(Number(params.get("version")) || null);
  }, [navigation]);
  const select = id => {
    if (!mounted.current) return;
    setProjectId(id); setInitialVersion(null); setError(""); setNotice("");
    history.replaceState({}, "", `/play/authoring${id ? `?project=${encodeURIComponent(id)}` : ""}`);
    window.scrollTo(0, 0);
  };
  const run = async fn => {
    setBusy(true); setError(""); setNotice("");
    try { await fn(); await load(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return <main id="player-main" className="player-shell authoring-page" tabIndex={-1}>
    <div className="authoring-toolbar authoring-heading"><h1><PenNib size={25} aria-hidden="true" />我的创作</h1>
      <div className="authoring-actions"><Button quiet onClick={() => navigate("/play")}>返回大厅</Button>
        {admin && <Button quiet onClick={() => navigate("/play/authoring-admin")}>创作审批</Button>}</div>
    </div>
    {!creator ? <section className="authoring-access" aria-labelledby="authoring-access-title">
      <h2 id="authoring-access-title">把你的故事变成可玩的世界</h2>
      <p>连接自己的创作 Agent，按平台规范编制故事；你可以管理私人草稿、用专用积分试玩，再将确认的版本提交上架。</p>
      <ol className="authoring-steps"><li>联系管理员开通当前账号的创作者权限。</li><li>在这里连接 MCP，获取规范并导入作品。</li><li>试玩、修订、复核后，提交管理员审批。</li></ol>
      <Notice>当前账号尚未开通创作者权限。开通后首次进入可领取一次 10,000 专用试玩积分，不到期。</Notice>
      <div className="authoring-actions"><a className="player-button quiet" href="https://qm.qq.com/q/MDjwl91IwE" target="_blank" rel="noopener noreferrer">联系内测群管理员<ArrowRight size={16} aria-hidden="true" /></a>
        <Button quiet disabled={busy} onClick={async () => { setBusy(true); try { await refreshAccount?.(); } finally { setBusy(false); } }}>已开通，刷新权限</Button>
      </div>
    </section> : <>
      {error && <Notice error>{error}</Notice>}{notice && <Notice>{notice}</Notice>}
      {!data ? error ? <Button disabled={busy} onClick={() => run(async () => {})}>重新加载</Button> : <div aria-busy="true"><p role="status">正在打开创作空间……</p><div className="player-skeleton" /></div> : <>
        <p className="authoring-author">作者：{data.author}<span>草稿和资料仅本人可见，上架需管理员审批。</span></p>
        <div className="authoring-layout">
          <div className="authoring-content">
            {projectId ? <AuthoringProject key={`${projectId}:${initialVersion || "latest"}`} projectId={projectId} initialVersion={initialVersion} navigate={navigate} onClose={() => select(null)} onChanged={load} maxBytes={data.limits?.zip_bytes} previewAvailable={data.preview_available} /> : <section aria-labelledby="projects">
              <div className="authoring-toolbar"><h2 id="projects"><FolderOpen size={20} aria-hidden="true" />项目与版本</h2><Button quiet disabled={busy} onClick={() => run(async () => {})}>刷新项目</Button></div>
              <form className="authoring-form-row" onSubmit={e => { e.preventDefault(); run(async () => {
                const name = title.trim();
                if (projectRequest.current?.title !== name) projectRequest.current = { title: name, key: safeUUID() };
                const value = await act("create_project", { project_key: projectRequest.current.key, title: name });
                setTitle(""); projectRequest.current = null; select(value.id);
              }); }}><label>新项目名称<input value={title} onChange={e => setTitle(e.target.value)} required maxLength={180} disabled={busy} placeholder="给你的故事起个名字" /></label><Button disabled={busy || !title.trim()}><Plus size={16} aria-hidden="true" />创建项目</Button></form>
              {!data.projects.length && <div className="authoring-empty"><PenNib size={30} weight="light" aria-hidden="true" /><h3>第一部作品，从一个想法开始</h3><p>先创建项目，再上传 Agent 编制的 ZIP 内容包。也可以让已连接的 Agent 直接创建和导入。</p><a className="text-button" href="#agent-connect">查看 MCP 接入步骤<ArrowRight size={16} aria-hidden="true" /></a></div>}
              <div className="authoring-project-list">{data.projects.map(project => <button key={project.id} disabled={busy} onClick={() => select(project.id)}>
                <FolderOpen size={22} aria-hidden="true" /><span><strong>{project.title}</strong><small>{project.version ? `v${project.version} · 私人版本` : "尚未导入内容"}{project.published_story_id ? " · 已有上架作品" : ""}</small></span><ArrowRight size={18} aria-hidden="true" />
              </button>)}</div>
            </section>}
            <AuthoringConnect endpoint={data.endpoint} scopes={data.scopes} />
          </div>
          <aside className="authoring-sidebar" aria-label="试玩积分与记录">
            <section aria-labelledby="preview-balance"><h2 id="preview-balance"><Coins size={20} aria-hidden="true" />专用试玩积分</h2>
              <dl className="authoring-balance"><div><dt>可用</dt><dd>{points(data.wallet.preview_micro)}</dd></div><div><dt>预留</dt><dd>{points(data.wallet.preview_held_micro)}</dd></div></dl>
              <p className="muted">首次赠送 10,000 积分，不到期，仅用于自己的作品试玩。普通游玩余额单独计算。</p>
              <form onSubmit={e => { e.preventDefault(); run(async () => { await act("redeem", { code: code.trim() }); setCode(""); setNotice("兑换成功，积分已到账。"); }); }}>
                <label>试玩兑换码<input value={code} onChange={e => setCode(e.target.value)} required maxLength={120} autoComplete="off" disabled={busy} /></label><Button quiet disabled={busy || !code.trim()}>兑换试玩积分</Button>
              </form>
            </section>
            <section><h2>最近试玩积分记录</h2>{!data.ledger.length && <p className="muted">试玩和兑换后的积分变动会记录在这里。</p>}
              {data.ledger.map(item => <div className="authoring-ledger" key={item.id}><span>{item.reason}</span><small>可用 {Number(item.preview_delta) > 0 ? "+" : ""}{points(item.preview_delta)} · 预留 {Number(item.preview_held_delta) > 0 ? "+" : ""}{points(item.preview_held_delta)}</small></div>)}
            </section>
          </aside>
        </div>
      </>}
    </>}
  </main>;
}
