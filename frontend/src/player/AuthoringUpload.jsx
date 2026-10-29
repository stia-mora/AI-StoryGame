import React, { useRef, useState } from "react";
import { UploadSimple } from "@phosphor-icons/react";
import { Button, Notice } from "./shared.jsx";
import { authoringAction as act, authoringRequest } from "./authoring-api.js";

export function ValidationReport({ report }) {
  if (!report) return null;
  return <div className="authoring-validation" aria-label="内容包校验结果">
    <p><strong>{report.valid ? "结构校验通过" : "内容包需要修正"}</strong></p>
    {[['errors', '阻断错误'], ['warnings', '警告'], ['missing', '缺项']].map(([key, label]) => report[key]?.length > 0 && <div key={key}>
      <h4>{label} · {report[key].length}</h4><ul>{report[key].map((item, index) => <li key={index}>
        {typeof item === "string" ? item : <>{item.path && <code>{item.path} </code>}{item.message || item.code}</>}
      </li>)}</ul>
    </div>)}
    <details><summary>完整校验报告</summary><pre tabIndex={0}>{JSON.stringify(report, null, 2)}</pre></details>
  </div>;
}

export function AuthoringUpload({ project, maxBytes = 50 * 1024 * 1024, disabled, onImported, onBusy }) {
  const [file, setFile] = useState(null), [validated, setValidated] = useState(null);
  const [stage, setStage] = useState(""), [error, setError] = useState("");
  const uploaded = useRef(null);
  const busy = !!stage;
  const run = async fn => {
    setError(""); onBusy(true);
    try { await fn(); } catch (e) { setError(e.message); } finally { setStage(""); onBusy(false); }
  };
  const validate = () => run(async () => {
    if (!file || file.size === 0 || file.size > maxBytes || !/\.zip$/i.test(file.name))
      throw new Error(`请选择不超过 ${Math.floor(maxBytes / 1024 / 1024)} MiB 的 ZIP 内容包。`);
    if (!crypto.subtle) throw new Error("上传需使用 HTTPS 或 localhost，以便安全校验文件指纹。");
    setValidated(null);
    if (!uploaded.current) {
      setStage("正在计算文件指纹……");
      const hash = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
      const sha256 = Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, "0")).join("");
      uploaded.current = await act("begin_upload", { project_id: project.id, size: file.size, sha256 });
    }
    if (!uploaded.current.complete) {
      setStage("正在上传内容包……");
      await authoringRequest(uploaded.current.http_url, undefined, { method: "PUT", body: file, headers: { "Content-Type": "application/zip" } });
      uploaded.current.complete = true;
    }
    setStage("正在校验结构、引用与来源……");
    const report = await act("validate_package", { upload_id: uploaded.current.upload_id });
    setValidated({ report, expectedVersion: project.version });
  });
  const importDraft = () => run(async () => {
    setStage("正在提交私人版本导入……");
    const result = await act("import_draft", {
      project_id: project.id, upload_id: uploaded.current.upload_id, expected_version: validated.expectedVersion,
    });
    if (result.accepted === false) { setValidated({ ...validated, report: result.report }); return; }
    await onImported(result);
  });
  return <div className="authoring-upload">
    <h3><UploadSimple size={18} aria-hidden="true" />上传内容包</h3>
    <p className="muted">上传 Agent 编制的 v2 内容包，包含 authoring.json。先校验，再导入为独立私人版本；现有版本和试玩存档会保留。</p>
    <label>ZIP 内容包<input type="file" accept=".zip,application/zip" disabled={disabled || busy} onChange={e => {
      setFile(e.target.files?.[0] || null); setValidated(null); setError(""); uploaded.current = null;
    }} /></label>
    <p className="muted">最多 {Math.floor(maxBytes / 1024 / 1024)} MiB{file && ` · 已选择 ${file.name}（${(file.size / 1024 / 1024).toFixed(2)} MiB）`}</p>
    <p className="muted">每个账号最多保留 4 个上传引用，24 小时后清理；同一项目的相同文件会复用引用。</p>
    {error && <Notice error>{error}</Notice>}
    {stage && <p role="status">{stage}</p>}
    <div className="authoring-actions">
      <Button quiet disabled={disabled || busy || !file} onClick={validate}>{validated ? "重新校验" : "上传并校验"}</Button>
      {validated?.report.valid && <Button disabled={disabled || busy || validated.expectedVersion !== project.version} onClick={importDraft}>导入为 v{validated.expectedVersion + 1}</Button>}
    </div>
    {validated && validated.expectedVersion !== project.version && <p role="status">项目已有新版本，请重新校验后再导入。</p>}
    <ValidationReport report={validated?.report} />
  </div>;
}
