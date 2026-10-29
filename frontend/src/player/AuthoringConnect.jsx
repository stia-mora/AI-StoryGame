import React, { useState } from "react";
import { Copy, Key, Plug } from "@phosphor-icons/react";
import { Button, Notice } from "./shared.jsx";

export function AuthoringConnect({ endpoint, scopes }) {
  const [pats, setPats] = useState(null), [token, setToken] = useState(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const prompt = `请使用创作 MCP 编制一部可玩的互动故事。先调用 authoring_get_contract 获取 summary、schemas 和 example，再确认题材、来源授权、章节范围及可玩身份。创建私人项目，按规范编制 v2 内容包和 authoring.json，上传并校验，逐项修复阻断错误后导入。轮询任务并核对版本及缺项。试玩前先报价，取得我的费用上限确认后执行；不要自行消耗积分。最后给出项目复核链接，由我在网页确认版本和来源授权，再提交管理员审批。未知资料明确标注，不编造已完成的检查。`;
  const config = JSON.stringify({ mcpServers: { authoring: { type: "http", url: endpoint } } }, null, 2);
  const copy = async (value, label) => {
    try { await navigator.clipboard.writeText(value); setNotice(`已复制${label}`); }
    catch { setNotice("复制失败，请选中内容后手动复制。"); }
  };
  const list = async () => {
    const result = await window.api.federation.patList();
    setPats((result.items || result.pats || []).filter(pat => pat.scopes?.some(scope => scope.startsWith("authoring:"))));
  };
  const run = async fn => {
    setBusy(true); setError(""); setNotice("");
    try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return <section className="authoring-connect" aria-labelledby="agent-connect">
    <h2 id="agent-connect"><Plug size={20} aria-hidden="true" />连接创作 Agent</h2>
    <p className="muted">你的 Agent 负责阅读和编制，平台负责规范、校验、私人草稿、试玩与上架审批。</p>
    <ol className="authoring-steps">
      <li>在支持远程 MCP 的客户端添加下方地址，选择浏览器登录授权。</li>
      <li>把创作任务发给 Agent，让它获取规范、上传内容并修复校验问题。</li>
      <li>回到这里试玩、复核来源授权，并提交指定版本上架。</li>
    </ol>
    <label>MCP 地址<div className="authoring-copy-field"><input readOnly value={endpoint} onFocus={e => e.target.select()} />
      <Button quiet type="button" onClick={() => copy(endpoint, "MCP 地址")}><Copy size={16} aria-hidden="true" />复制地址</Button></div></label>
    <details><summary>客户端配置与创作任务</summary>
      <p>客户端支持 JSON 配置时，可使用下方远程 MCP 配置。保存后在客户端完成浏览器授权。</p>
      <pre tabIndex={0}>{config}</pre>
      <Button quiet onClick={() => copy(config, "配置")}><Copy size={16} aria-hidden="true" />复制配置</Button>
      <label>发给 Agent 的任务<textarea readOnly rows={7} value={prompt} onFocus={e => e.target.select()} /></label>
      <Button quiet onClick={() => copy(prompt, "创作任务")}><Copy size={16} aria-hidden="true" />复制创作任务</Button>
    </details>
    <details onToggle={e => { if (e.currentTarget.open && pats === null && !busy) run(list); }}>
      <summary><Key size={17} aria-hidden="true" />个人令牌接入</summary>
      <p>客户端支持 Bearer 令牌时，可使用个人令牌。令牌仅本次显示，不要放进作品包或公开配置。</p>
      <p>在客户端的请求头设置中填入 <code>Authorization: Bearer &lt;你的个人令牌&gt;</code>。</p>
      {error && <Notice error>{error}</Notice>}
      <div className="authoring-actions">
        <Button quiet disabled={busy || !!token} onClick={() => run(async () => {
          const value = await window.api.federation.patCreate({ name: "创作 Agent", scopes });
          setToken({ id: value.pat?.id, value: value.token });
          await list();
        })}>生成创作令牌</Button>
        <Button quiet disabled={busy} onClick={() => run(list)}>刷新令牌列表</Button>
      </div>
      {token && <div className="authoring-token">
        <label>令牌仅展示本次，请妥善保存<input readOnly type="password" value={token.value} onFocus={e => e.target.select()} autoComplete="off" /></label>
        <Button quiet onClick={() => copy(token.value, "令牌")}>复制令牌</Button>
        <Button quiet onClick={() => setToken(null)}>已保存，隐藏令牌</Button>
      </div>}
      {pats?.map(pat => <div className="authoring-row" key={pat.id}>
        <span>{pat.name}<small>{pat.revoked_at ? "已撤销" : "创作权限"}</small></span>
        {!pat.revoked_at && <Button quiet disabled={busy} onClick={() => run(async () => {
          await window.api.federation.patRevoke(pat.id);
          setToken(null);
          await list();
          setNotice("令牌已撤销，使用它的 Agent 需重新授权。");
        })}>撤销</Button>}
      </div>)}
      {pats?.length === 0 && <p className="muted">暂无创作令牌。推荐优先使用浏览器授权。</p>}
    </details>
    {notice && <p role="status">{notice}</p>}
  </section>;
}
