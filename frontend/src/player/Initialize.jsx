import React, { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowUp, BookOpen, Check, Copy, PencilSimple, User } from "@phosphor-icons/react";
import { lsGetJSON, lsRemove, lsSetJSON } from "../lib/storage.js";
import { BookCover, Button, Notice } from "./shared.jsx";
import { useComposerKeys } from "./useComposerKeys.js";

export function Initialize({ story, uid, navigate, refresh, guest = false, login }) {
  const key = `player-setup-${uid || "guest"}-${story.id}`;
  const soul = story.martial_soul_creation;
  const initial = { step: "identity", identity: "", custom: "", name: "", background: "", martial: null, draft: "" };
  const [setup, setSetup] = useState(() => ({ ...initial, ...lsGetJSON(key, {}) }));
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [copied, setCopied] = useState(false);
  const inFlight = useRef(false), scroller = useRef(null), copyTimer = useRef(null), input = useRef(null), lastStep = useRef(setup.step);
  const identity = story.identities.find((item) => String(item.id) === setup.identity);
  const identityName = setup.custom || identity?.name;
  const patch = (value) => { setError(""); setSetup((old) => ({ ...old, draft: "", ...value })); };
  useEffect(() => { lsSetJSON(key, setup); }, [key, setup]);
  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
    if (lastStep.current !== setup.step) input.current?.focus({ preventScroll: true });
    lastStep.current = setup.step;
  }, [setup.step]);
  useEffect(() => () => clearTimeout(copyTimer.current), []);
  const prompts = {
    identity: "先选一个身份。你也可以直接写下自己想扮演的人。",
    name: "这个世界该怎样称呼你？发送你的角色名字。",
    soul: "你想觉醒什么武魂？点击推荐项，也可以填写自己的武魂名称，或选择随机觉醒。",
    background: "还有想带入故事的经历、性格或目标吗？写在下方，也可以直接跳过。",
    review: "设定已整理好。确认后创建角色，接下来在这里查看开场报价，再决定开始生成。",
  };
  const summary = [
    ["身份", identityName, "identity"], ["名字", setup.name, "name"],
    ...(soul ? [["武魂", setup.martial?.mode === "random" ? "随机觉醒" : setup.martial?.name, "soul"]] : []),
    ["背景", setup.background || "未补充", "background"],
  ];
  const summaryText = summary.map(([label, value]) => `${label}：${value || "待设定"}`).join("\n");
  const send = (event) => {
    event.preventDefault();
    if (inFlight.current) return;
    const text = setup.draft.trim();
    if (!text) return;
    if (setup.step === "identity") patch({ identity: "", custom: text, step: "name" });
    if (setup.step === "name") patch({ name: text, step: soul ? "soul" : "background" });
    if (setup.step === "soul") patch({ martial: { mode: "custom", name: text }, step: "background" });
    if (setup.step === "background") patch({ background: text, step: "review" });
  };
  const composerKeys = useComposerKeys(send);
  const create = async () => {
    if (inFlight.current || guest) return;
    if (!setup.name.trim() || !identityName || (soul && !setup.martial)) { setError("请先完成身份、名字及故事需要的选项。"); return; }
    inFlight.current = true;
    setBusy(true); setError("");
    try {
      const result = await window.api.player.create({
        story_id: story.id, name: setup.name.trim(), identity_id: setup.identity, background: setup.background,
        ...(setup.custom ? { custom_identity: setup.custom } : {}),
        ...(soul ? { martial_soul: setup.martial } : {}),
      });
      lsRemove(key);
      await refresh();
      navigate(`/play/saves/${result.save.id}`);
    } catch (e) { setError(e.message); }
    finally { inFlight.current = false; setBusy(false); }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(summaryText);
      setCopied(true);
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(false), 2500);
    } catch { setError("复制失败，可以直接选择设定文字复制。"); }
  };
  return (
    <main id="player-main" className="play-workspace setup-workspace" data-view="story" tabIndex={-1}>
      <aside className="workspace-rail" aria-label="故事介绍">
        <div className="workspace-rail-content">
          <button className="back-link" onClick={() => navigate("/play")}><ArrowLeft size={18} />故事大厅</button>
          <div className="workspace-story"><BookCover story={story} /><h2>{story.title}</h2></div>
          <p className="setup-introduction">{story.introduction}</p>
          <p className="fine-print">初始化与创建角色免费，生成剧情前会显示费用。</p>
        </div>
      </aside>
      <section className="workspace-center" aria-label="故事初始化">
        <header className="workspace-reader-header"><h1>{story.title}</h1><span className="setup-phase"><BookOpen size={15} />初始化设定</span></header>
        <div className="workspace-reading" ref={scroller} role="region" aria-label="初始化对话" tabIndex={0}>
          <div className="workspace-paper setup-conversation">
            <div className="setup-message"><span className="setup-speaker"><BookOpen size={18} />故事向导</span><p>{story.introduction}</p><p>先一起确定你的角色。所有设定在创建前都可以修改。</p></div>
            {identityName && <div className="setup-answer"><User size={16} /><p>我想扮演{identityName}。</p><button disabled={busy} className="icon-button" aria-label="修改身份" onClick={() => patch({ step: "identity" })}><PencilSimple size={15} /></button></div>}
            {setup.name && <div className="setup-answer"><User size={16} /><p>我的名字是{setup.name}。</p><button disabled={busy} className="icon-button" aria-label="修改名字" onClick={() => patch({ step: "name" })}><PencilSimple size={15} /></button></div>}
            {soul && setup.martial && <div className="setup-answer"><User size={16} /><p>{setup.martial.mode === "random" ? "我想随机觉醒武魂。" : `我选择${setup.martial.name}。`}</p><button disabled={busy} className="icon-button" aria-label="修改武魂" onClick={() => patch({ step: "soul" })}><PencilSimple size={15} /></button></div>}
            {setup.background && <div className="setup-answer"><User size={16} /><p>{setup.background}</p></div>}
            <div className="setup-message" aria-live="polite"><span className="setup-speaker"><BookOpen size={18} />故事向导</span><p>{guest ? "可以先了解故事与可选身份。登录后，在这里完成角色设定。" : prompts[setup.step]}</p></div>
            {(guest || setup.step === "identity") && <div className="setup-choices" aria-label="推荐身份">{story.identities.map((item) => <button disabled={busy || guest} key={item.id} onClick={() => patch({ identity: String(item.id), custom: "", step: "name" })}><strong>{item.name}</strong><span>{item.description || item.role}</span></button>)}</div>}
            {!guest && setup.step === "soul" && soul && <div className="setup-choices" aria-label="武魂选项">
              {soul.choices.map((item) => <button key={item.name} disabled={busy} onClick={() => patch({ martial: { mode: "recommended", name: item.name }, step: "background" })}><strong>{item.name}</strong><span>{item.description}</span></button>)}
              {soul.allow_random && <button disabled={busy} onClick={() => patch({ martial: { mode: "random", name: "" }, step: "background" })}><strong>随机觉醒</strong><span>结果由服务端确定，重试不会重抽。</span></button>}
            </div>}
            {!guest && setup.step === "background" && <Button quiet disabled={busy} onClick={() => patch({ background: "", step: "review" })}>跳过，使用当前设定</Button>}
            {!guest && setup.step === "review" && <div className="setup-review"><h2>本次角色设定</h2><dl>{summary.map(([label, value, step]) => <div key={label}><dt>{label}</dt><dd>{value || "待设定"}</dd><button className="text-button" disabled={busy} onClick={() => patch({ step })}>修改</button></div>)}</dl><button className="text-button setup-copy" onClick={copy}><span className="copy-icons" data-copied={copied} aria-hidden="true"><Copy size={16} /><Check size={16} className={copied ? "feedback-check" : ""} /></span>{copied ? "已复制" : "复制设定"}</button></div>}
            {error && <Notice error>{error}</Notice>}
          </div>
        </div>
        <div className="workspace-composer-dock setup-dock">
          {guest ? <><Button onClick={login}>登录后创建角色</Button><p className="fine-print">创建角色免费，生成剧情前显示报价。</p></> : setup.step === "review" ? <><Button disabled={busy} onClick={create}>{busy ? "正在创建角色……" : "确认设定，进入故事"}<ArrowUp size={18} /></Button><span className="fine-print" role="status">创建角色免费，尚未开始生成或扣费。</span></> : <form className="workspace-composer setup-composer" onSubmit={send}>
            <label className="sr-only" htmlFor="setup-message">{setup.step === "name" ? "你的名字" : "初始化设定"}</label>
            <textarea ref={input} id="setup-message" value={setup.draft} disabled={busy || (setup.step === "soul" && !soul?.allow_custom)} onChange={(e) => setSetup((old) => ({ ...old, draft: e.target.value }))} maxLength={setup.step === "background" ? 1200 : setup.step === "identity" ? 80 : 40} placeholder={setup.step === "identity" ? "描述你想扮演的身份，或点击上方推荐项" : setup.step === "name" ? "输入角色名字" : setup.step === "soul" ? "输入武魂名称，或点击上方选项" : "补充你的经历、性格或目标"} rows={2} {...composerKeys} />
            <Button type="submit" disabled={busy || !setup.draft.trim()} aria-label="发送设定"><ArrowUp size={19} /></Button>
            <span className="quote-note">初始化免费 · Ctrl / ⌘ + Enter 发送 · 草稿自动保存</span>
          </form>}
        </div>
      </section>
      <aside className="workspace-right setup-summary" aria-label="当前初始化设定"><h2>当前设定</h2><dl>{summary.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || "待设定"}</dd></div>)}</dl><p className="fine-print">自由设定描述角色的愿望与背景。能力、物品与事件仍由故事规则决定。</p></aside>
    </main>
  );
}
