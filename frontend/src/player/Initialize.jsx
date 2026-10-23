import React, { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowUp, ArrowRight, BookOpen, CaretDown, Check, CircleNotch, Copy, PencilSimple, Shuffle, User } from "@phosphor-icons/react";
import { lsGetJSON, lsRemove, lsSetJSON } from "../lib/storage.js";
import { BookCover, Button, Notice } from "./shared.jsx";
import { useComposerKeys } from "./useComposerKeys.js";

export function Initialize({ story, uid, navigate, refresh, guest = false, login }) {
  const key = `player-setup-${uid || "guest"}-${story.id}`;
  const soul = story.martial_soul_creation;
  const steps = ["identity", "name", ...(soul ? ["soul"] : []), "background", "review"];
  const [setup, setSetup] = useState(() => {
    const saved = lsGetJSON(key, {});
    return {
      identity: "", custom: "", name: "", background: "", martial: null, draft: "", drafts: {},
      ...saved,
      step: steps.includes(saved.step) ? saved.step : "identity",
      backgroundDone: saved.backgroundDone || saved.step === "review" || Boolean(saved.background),
      reviewed: saved.reviewed || saved.step === "review",
    };
  });
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [copied, setCopied] = useState(false);
  const inFlight = useRef(false), copyTimer = useRef(null), input = useRef(null), question = useRef(null), scroller = useRef(null), lastStep = useRef(setup.step);
  const identity = story.identities.find((item) => String(item.id) === setup.identity);
  const identityName = setup.custom || identity?.name;
  const soulValid = !soul || (
    (setup.martial?.mode === "random" && soul.allow_random) ||
    (setup.martial?.mode === "custom" && soul.allow_custom && setup.martial.name?.trim()) ||
    (setup.martial?.mode === "recommended" && soul.choices.some((item) => item.name === setup.martial.name))
  );
  const named = Boolean(identityName && setup.name.trim());
  const ready = Boolean(named && soulValid && setup.backgroundDone);
  const fields = [
    { id: "identity", label: "身份", value: identityName, complete: Boolean(identityName), available: true },
    { id: "name", label: "名字", value: setup.name, complete: Boolean(setup.name.trim()), available: Boolean(identityName) },
    ...(soul ? [{ id: "soul", label: "武魂", value: setup.martial?.mode === "random" ? "随机觉醒" : setup.martial?.name, complete: Boolean(soulValid), available: named }] : []),
    { id: "background", label: "背景", value: setup.background || (setup.backgroundDone ? "未补充" : "可选"), complete: Boolean(setup.backgroundDone), available: Boolean(named && soulValid) },
  ];
  const navigation = [...fields, { id: "review", label: "确认", complete: false, available: ready }];
  const prompts = {
    identity: ["你想以什么身份进入故事？", "选择一个推荐身份，或在下方写下自己的想法。"],
    name: ["这个世界该怎样称呼你？", "写下你的角色名字。"],
    soul: ["选择你的武魂", soul?.allow_custom ? "选择推荐武魂，也可以在下方输入名称。" : "从下方选项中选择武魂。"],
    background: ["还有想带入故事的设定吗？", "经历、性格、目标都可以，也可以直接跳过。"],
    review: ["确认角色设定", "每项设定都可以单独修改，确认后创建角色。"],
  };
  const maxLength = setup.step === "background" ? 1200 : setup.step === "identity" ? 80 : 40;
  const canType = setup.step !== "soul" || soul?.allow_custom;
  const reviewed = setup.step === "review";
  const summaryText = fields.map((field) => `${field.label}：${field.value || "待设定"}`).join("\n");

  const changeStep = (next, values = {}, submitted = false) => {
    if (inFlight.current) return;
    setError("");
    setCopied(false);
    clearTimeout(copyTimer.current);
    setSetup((old) => {
      const updated = { ...old, ...values };
      const drafts = { ...old.drafts, [old.step]: submitted ? "" : old.draft };
      const existing = {
        identity: updated.custom,
        name: updated.name,
        soul: updated.martial?.mode === "custom" ? updated.martial.name : "",
        background: updated.background,
      };
      // Submitted values become edit fallbacks; other unsent steps survive.
      if (submitted) delete drafts[old.step];
      return { ...updated, step: next, drafts, draft: drafts[next] ?? existing[next] ?? "", reviewed: updated.reviewed || next === "review" };
    });
  };
  const nextStep = (normal) => setup.reviewed ? "review" : normal;
  useEffect(() => { lsSetJSON(key, setup); }, [key, setup]);
  useEffect(() => {
    if (lastStep.current === setup.step) return;
    if (scroller.current && question.current) {
      scroller.current.scrollTop += question.current.getBoundingClientRect().top - scroller.current.getBoundingClientRect().top - 16;
    }
    if (input.current && !input.current.disabled) input.current.focus({ preventScroll: true });
    else question.current?.focus({ preventScroll: true });
    lastStep.current = setup.step;
  }, [setup.step]);
  useEffect(() => () => clearTimeout(copyTimer.current), []);

  const send = (event) => {
    event.preventDefault();
    if (guest || inFlight.current || !canType) return;
    const text = setup.draft.trim();
    if (!text) return;
    if (setup.step === "identity") changeStep(nextStep("name"), { identity: "", custom: text }, true);
    if (setup.step === "name") changeStep(nextStep(soul ? "soul" : "background"), { name: text }, true);
    if (setup.step === "soul") changeStep(nextStep("background"), { martial: { mode: "custom", name: text } }, true);
    if (setup.step === "background") changeStep("review", { background: text, backgroundDone: true }, true);
  };
  const composerKeys = useComposerKeys(send);
  const create = async () => {
    if (inFlight.current || guest) return;
    if (!ready) { setError("请先完成身份、名字及故事需要的选项。"); return; }
    inFlight.current = true;
    setBusy(true); setError("");
    try {
      const result = await window.api.player.create({
        story_id: story.id, name: setup.name.trim(), identity_id: setup.identity, background: setup.background,
        ...(setup.custom ? { custom_identity: setup.custom } : {}),
        ...(soul ? { martial_soul: setup.martial } : {}),
      });
      lsRemove(key);
      // Refreshing the lobby must not turn an already created character into a retry.
      try { await refresh(); } catch { /* The saved character can be opened directly. */ }
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
    <main id="player-main" className="play-workspace setup-workspace" data-view="story" data-guest={guest} aria-busy={busy} tabIndex={-1}>
      <section className="workspace-center" aria-label="故事初始化">
        <header className="workspace-reader-header setup-header">
          <button className="icon-button" aria-label="返回故事大厅" disabled={busy} onClick={() => navigate("/play")}><ArrowLeft size={18} /></button>
          <h1>{story.title}</h1>
          <span className="setup-phase">角色设定</span>
        </header>
        {!guest && (
          <nav className="setup-step-nav" aria-label="角色设定步骤">
            {navigation.map((step, index) => (
              <button key={step.id} aria-current={setup.step === step.id ? "step" : undefined} disabled={busy || !step.available} onClick={() => changeStep(step.id)}>
                <span className="setup-step-marker" aria-hidden="true">{step.complete ? <Check size={13} /> : index + 1}</span>
                {step.label}
              </button>
            ))}
          </nav>
        )}
        <div className="workspace-reading" ref={scroller} role="region" aria-label="初始化对话" tabIndex={0}>
          <div className="workspace-paper setup-conversation">
            <div className="setup-story-context">
              <BookCover story={story} />
              <div>
                <span className="setup-context-label"><BookOpen size={15} />{story.identities.length} 个推荐身份</span>
                <details><summary>故事简介<CaretDown size={14} /></summary><p>{story.introduction}</p></details>
              </div>
            </div>
            {!guest && !reviewed && fields.some((field) => field.complete && field.id !== setup.step) && (
              <ol className="setup-transcript" aria-label="已确认设定">
                {fields.filter((field) => field.complete && field.id !== setup.step).map((field) => (
                  <li key={field.id}><User size={15} /><span>{field.label}</span><p>{field.value}</p></li>
                ))}
              </ol>
            )}
            <section className="setup-question" ref={question} tabIndex={-1} aria-labelledby="setup-question-title">
              <div className="setup-question-heading">
                <span className="setup-guide-mark" aria-hidden="true"><BookOpen size={19} /></span>
                <div>
                  <h2 id="setup-question-title">{guest ? "选择一个身份，开始你的故事" : prompts[setup.step][0]}</h2>
                  <p>{guest ? "登录后可以选择推荐身份，也可以自己描述角色。" : prompts[setup.step][1]}</p>
                </div>
              </div>
              {(guest || setup.step === "identity") && (
                <div className="setup-choices" role="group" aria-label="推荐身份">
                  {story.identities.map((item, index) => guest ? (
                    <div className="setup-guest-identity" key={item.id}><strong>{item.name}</strong>{(item.description || item.role) && <p>{item.description || item.role}</p>}</div>
                  ) : (
                    <button key={item.id} disabled={busy} aria-pressed={setup.identity === String(item.id) && !setup.custom} onClick={() => changeStep(nextStep("name"), { identity: String(item.id), custom: "" }, true)}>
                      <span className="setup-choice-index" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                      <span className="setup-choice-copy"><strong>{item.name}</strong>{(item.description || item.role) && <span>{item.description || item.role}</span>}</span>
                      <ArrowRight size={17} aria-hidden="true" />
                    </button>
                  ))}
                </div>
              )}
              {!guest && setup.step === "soul" && soul && (
                <div className="setup-choices setup-soul-choices" role="group" aria-label="武魂选项">
                  {soul.choices.map((item) => (
                    <button key={item.name} disabled={busy} aria-pressed={setup.martial?.mode === "recommended" && setup.martial.name === item.name} onClick={() => changeStep(nextStep("background"), { martial: { mode: "recommended", name: item.name } }, true)}>
                      <span className="setup-choice-copy"><strong>{item.name}</strong><span>{item.description}</span></span><ArrowRight size={16} aria-hidden="true" />
                    </button>
                  ))}
                  {soul.allow_random && <button className="setup-random" disabled={busy} onClick={() => changeStep(nextStep("background"), { martial: { mode: "random", name: "" } }, true)}><Shuffle size={18} /><span className="setup-choice-copy"><strong>随机觉醒</strong><span>觉醒时揭晓，重试不会重抽。</span></span><ArrowRight size={16} aria-hidden="true" /></button>}
                </div>
              )}
              {!guest && setup.step === "background" && <Button quiet disabled={busy} onClick={() => changeStep("review", { background: "", backgroundDone: true }, true)}>{setup.background ? "清空背景，返回确认" : "跳过，使用当前设定"}</Button>}
              {!guest && reviewed && (
                <div className="setup-review">
                  <dl>{fields.map((field) => (
                    <div key={field.id}><dt>{field.label}</dt><dd>{field.value || "待设定"}</dd><button className="text-button" aria-label={`修改${field.label}`} disabled={busy} onClick={() => changeStep(field.id)}><PencilSimple size={15} /><span>修改</span></button></div>
                  ))}</dl>
                  <button className="text-button setup-copy" disabled={busy} onClick={copy}><span className="copy-icons" data-copied={copied} aria-hidden="true"><Copy size={16} /><Check size={16} className={copied ? "feedback-check" : ""} /></span>{copied ? "已复制" : "复制设定"}</button>
                </div>
              )}
            </section>
          </div>
        </div>
        <div className="workspace-composer-dock setup-dock">
          {error && <Notice error>{error}</Notice>}
          {guest ? <Button onClick={login}>登录后创建角色<ArrowRight size={17} /></Button> : reviewed ? (
            <Button disabled={busy || !ready} onClick={create}>{busy ? <CircleNotch size={18} className="setup-spinner" /> : <ArrowRight size={18} />}{busy ? "正在创建角色……" : "确认设定，进入故事"}</Button>
          ) : (
            <form className="workspace-composer setup-composer" onSubmit={send}>
              <div className="setup-composer-label"><label htmlFor="setup-message">{setup.step === "name" ? "你的名字" : "初始化设定"}</label><span aria-hidden="true">{setup.draft.length}/{maxLength}</span></div>
              <textarea
                ref={input} id="setup-message" value={setup.draft} disabled={busy || !canType}
                onChange={(event) => setSetup((old) => ({ ...old, draft: event.target.value }))}
                maxLength={maxLength} rows={2}
                placeholder={!canType ? "请点击上方选项完成选择" : setup.step === "identity" ? "写下你想扮演的身份……" : setup.step === "name" ? "输入你在故事中的名字……" : setup.step === "soul" ? "输入你想觉醒的武魂名称……" : "写下经历、性格或你想完成的事……"}
                {...composerKeys}
              />
              <Button type="submit" disabled={busy || !canType || !setup.draft.trim()} aria-label="发送设定"><ArrowUp size={19} /></Button>
            </form>
          )}
          <div className="setup-dock-note"><span>创建角色免费 · 生成前显示报价</span>{!guest && !reviewed && <span>{canType ? "Ctrl / ⌘ + Enter 发送" : "点击选项继续"}</span>}</div>
        </div>
      </section>
      {!guest && (
        <aside className="workspace-right setup-summary" aria-label="当前初始化设定">
          <div className="setup-summary-heading"><User size={18} /><h2>{reviewed ? "创建前核对" : "当前设定"}</h2></div>
          <p className="setup-summary-note">{reviewed ? "确认后将以这些设定进入故事。" : "选择项目可以回看或修改，输入中的草稿会保留。"}</p>
          <nav aria-label="设定摘要">{fields.map((field) => (
            <button key={field.id} disabled={busy || !field.available} aria-label={`设定：${field.label}`} aria-current={setup.step === field.id ? "step" : undefined} onClick={() => changeStep(field.id)}>
              <span className="setup-summary-check" data-complete={field.complete} aria-hidden="true">{field.complete ? <Check size={14} /> : null}</span>
              <span><strong>{field.label}</strong><span>{reviewed && field.complete ? "已填写" : field.value || "待设定"}</span></span><PencilSimple size={14} aria-hidden="true" />
            </button>
          ))}</nav>
          <p className="fine-print">自由设定描述角色的愿望与背景。能力、物品与事件仍由故事规则决定。</p>
        </aside>
      )}
    </main>
  );
}
