import React, { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowsClockwise, Play } from "@phosphor-icons/react";
import { safeUUID } from "../lib/crypto-safe.js";
import { Button, Notice } from "./shared.jsx";
import { authoringAction as act, authoringStatus as statusName } from "./authoring-api.js";
import { AuthoringUpload, ValidationReport } from "./AuthoringUpload.jsx";

export function AuthoringProject({ projectId, initialVersion = null, navigate, onClose, onChanged, maxBytes, previewAvailable }) {
  const [draft, setDraft] = useState(null), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false), [uploadBusy, setUploadBusy] = useState(false), [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(initialVersion), [requestedVersion, setRequestedVersion] = useState(1);
  const [rights, setRights] = useState(""), [identity, setIdentity] = useState(""), [name, setName] = useState("旅人");
  const displayedRevision = useRef(null), latestRead = useRef(0), previewRequest = useRef(null);
  const mounted = useRef(true);
  const refresh = useCallback(async (target = version) => {
    if (!mounted.current) return;
    const request = ++latestRead.current;
    const value = await act("get_draft", { project_id: projectId, ...(target ? { version: Number(target) } : {}) });
    if (!mounted.current || request !== latestRead.current) return;
    const current = value.revisions[0];
    if (displayedRevision.current !== current?.id) {
      setRights(current?.rights_note || "");
      setIdentity(current?.contract.play.identities[0]?.id || "");
      setRequestedVersion(current?.version || 1);
      displayedRevision.current = current?.id;
      previewRequest.current = null;
    }
    setDraft(value);
    history.replaceState({}, "", `/play/authoring?project=${encodeURIComponent(projectId)}${target ? `&version=${Number(target)}` : ""}`);
  }, [projectId, version]);
  useEffect(() => {
    let current = true;
    const reads = latestRead;
    const lifecycle = mounted;
    lifecycle.current = true;
    setLoading(true); setError("");
    refresh().catch(e => { if (current) setError(e.message); }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; reads.current++; lifecycle.current = false; };
  }, [refresh]);
  const active = draft?.jobs.some(job => ["pending", "running"].includes(job.status));
  useEffect(() => {
    if (!active || busy || uploadBusy || error) return;
    const timer = setTimeout(() => {
      refresh().then(onChanged).catch(e => setError(`任务刷新失败：${e.message} 请手动刷新。`));
    }, 3000);
    return () => clearTimeout(timer);
  }, [draft, active, busy, uploadBusy, error, refresh, onChanged]);
  const run = async fn => {
    setBusy(true); setError(""); setNotice("");
    try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const current = draft?.revisions[0];
  const disabled = busy || uploadBusy;
  const submission = draft?.submissions.find(item => item.revision_id === current?.id);
  const submitted = ["pending_review", "published"].includes(submission?.status);
  const saves = (draft?.preview_saves || []).filter(save => save.revision_id === current?.id);
  return <section className="authoring-project" aria-label="项目详情" aria-busy={loading}>
    <div className="authoring-toolbar">
      <Button quiet disabled={disabled} onClick={onClose}><ArrowLeft size={16} aria-hidden="true" />全部项目</Button>
      <Button quiet disabled={disabled || loading} onClick={() => run(async () => { await refresh(); await onChanged(); })}><ArrowsClockwise size={16} aria-hidden="true" />刷新任务与版本</Button>
    </div>
    {error && <Notice error>{error}</Notice>}
    {notice && <Notice>{notice}</Notice>}
    {loading && <p role="status">正在读取私人项目……</p>}
    {draft && <>
      <h2>{draft.project.title}</h2>
      <p className="muted">私人项目 · {draft.project.version ? `最新版本 v${draft.project.version}` : "尚未导入版本"}</p>
      <details><summary>项目编号（提供给 Agent）</summary><code>{draft.project.id}</code></details>
      {draft.jobs.length > 0 && <details open={active || undefined}><summary>最近任务{active ? " · 自动刷新中" : ""}</summary>
        {draft.jobs.map(job => <div className="authoring-row" key={job.id}><span>{job.kind === "import" ? "内容导入" : "作品试玩"} · {statusName(job.status)}
          {job.error && <small>{job.error}</small>}</span>
          {job.kind === "import" && ["pending", "running"].includes(job.status) && <span>{job.progress || 0}%</span>}
        </div>)}
      </details>}
      <AuthoringUpload project={draft.project} maxBytes={maxBytes} disabled={busy || active} onBusy={setUploadBusy} onImported={async result => {
        setNotice(result.reused ? "已复用相同内容的导入任务，可在最近任务中查看。" : "导入任务已接受，完成后会生成私人版本。你可以离开此页，任务会继续。");
        if (version !== null) setVersion(null);
        await refresh(null); await onChanged();
      }} />
      {!!draft.project.version && <div className="authoring-version">
        <div className="authoring-toolbar"><h3>版本 v{current?.version}</h3>
          <form className="authoring-version-form" onSubmit={e => { e.preventDefault(); setVersion(Number(requestedVersion)); }}>
            <label>查看历史版本<input type="number" min="1" max={draft.project.version} value={requestedVersion} onChange={e => setRequestedVersion(e.target.value)} required disabled={disabled} /></label>
            <Button quiet disabled={disabled}>打开指定版本</Button>
            {version !== null && <Button quiet type="button" disabled={disabled} onClick={() => setVersion(null)}>回到最新版本</Button>}
          </form>
        </div>
        {current && <>
          <dl className="authoring-checks"><div><dt>结构校验</dt><dd>{current.report.valid ? "通过" : "未通过"}</dd></div>
            <div><dt>实际试玩</dt><dd>{current.report.checks?.playtest === "passed" ? "已保存成功回复" : "尚未执行成功"}</dd></div>
            <div><dt>作者复核</dt><dd>{current.reviewed_at ? "已复核" : "待复核"}</dd></div>
            <div><dt>上架审批</dt><dd>{submission ? statusName(submission.status) : "未提交"}</dd></div>
          </dl>
          {submission?.reason && <Notice>审批说明：{submission.reason}</Notice>}
          {current.contract.completeness.unresolved?.length > 0 && <div className="authoring-todos"><h4>待作者确认</h4><ul>{current.contract.completeness.unresolved.map((item, index) => <li key={index}>待办：{item}</li>)}</ul></div>}
          <div className="authoring-playtest"><h3>试玩此版本</h3>
            {previewAvailable === false && <Notice>管理员尚未配置可用的试玩服务模型。可以继续编制和校验，配置完成后再试玩。</Notice>}
            <div className="authoring-form-row"><label>试玩身份<select value={identity} disabled={disabled} onChange={e => setIdentity(e.target.value)}>
              {current.contract.play.identities.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
              <label>角色名字<input value={name} maxLength={40} disabled={disabled} onChange={e => setName(e.target.value)} /></label>
            </div>
            <Button disabled={disabled || previewAvailable === false || !identity || !name.trim()} onClick={() => run(async () => {
              const key = `${current.id}:${identity}:${name.trim()}`;
              if (previewRequest.current?.key !== key) previewRequest.current = { key, id: safeUUID() };
              const result = await act("preview", { mode: "create", revision_id: current.id, identity_id: identity, request_id: previewRequest.current.id, name: name.trim() });
              navigate(result.url);
            })}><Play size={16} aria-hidden="true" />免费创建试玩存档</Button>
            <p className="muted">创建存档免费。进入阅读界面后，生成前会显示报价，只消耗专用试玩积分。</p>
            {saves.map(save => <div className="authoring-row" key={save.id}><span>{save.title}<small>{save.turn > 0 ? `第 ${save.turn} 回合` : "开场试玩"}</small></span>
              <Button quiet disabled={disabled} onClick={() => navigate(`/play/saves/${save.id}`)}>继续试玩</Button></div>)}
          </div>
          <div className="authoring-review"><h3>复核并提交</h3>
            <p className="muted">请核对故事内容、人物与开局，以及下方校验报告。结构校验通过不代表语义、授权或实际试玩已通过。</p>
            <label>来源与授权说明<textarea value={rights} onChange={e => setRights(e.target.value)} maxLength={2000} rows={4} disabled={disabled || submitted} placeholder="说明原创内容或使用的资料，以及相应授权。" /></label>
            <div className="authoring-actions">
              <Button quiet disabled={disabled || submitted || !rights.trim()} onClick={() => run(async () => {
                await act("review", { revision_id: current.id, rights_note: rights }); await refresh(); setNotice("此版本已标记作者复核。");
              })}>确认已复核此版本</Button>
              <Button disabled={disabled || submitted || !current.reviewed_at || rights.trim() !== current.rights_note?.trim()} onClick={() => run(async () => {
                await act("submit", { revision_id: current.id }); await refresh(); setNotice("已提交，等待管理员审批。");
              })}>提交上架审批</Button>
            </div>
            {!current.reviewed_at && <p className="muted">填写来源授权并确认复核后，才能提交此版本。上传不会自动公开。</p>}
          </div>
          <details><summary>内容配置与校验报告</summary><ValidationReport report={current.report} />
            <pre tabIndex={0}>{JSON.stringify({ fingerprint: current.fingerprint, contract: current.contract }, null, 2)}</pre>
          </details>
        </>}
      </div>}
    </>}
  </section>;
}
