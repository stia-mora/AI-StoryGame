import React, { useCallback, useEffect, useState } from "react";
import {
  BookOpen,
  ArrowLeft,
  ArrowRight,
  Coins,
  Moon,
  Sun,
  FolderOpen,
  Question,
  UserCircle,
  CaretDown,
  CheckCircle,
} from "@phosphor-icons/react";
import { lsGetJSON, lsSetJSON } from "../lib/storage.js";
import {
  Button,
  Empty,
  Loading,
  Notice,
  points,
  BookCover,
} from "./shared.jsx";
import { Reader } from "./Reader.jsx";
import { Wallet } from "./Wallet.jsx";
import { Manage } from "./Manage.jsx";
import { MartialSoulPicker } from "./MartialSoulPicker.jsx";
import { PlayerHelp } from "./PlayerHelp.jsx";
import { Lobby } from "./Lobby.jsx";

export function PlayerApp() {
  const [path, setPath] = useState(location.pathname);
  const [data, setData] = useState(null),
    [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [saveSearch, setSaveSearch] = useState("");
  const [helpOpen, setHelpOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const login = () => location.assign(`/Login.html?next=${encodeURIComponent(location.pathname)}`);
  const logout = async () => {
    setSigningOut(true);
    try {
      await window.api.auth.logout();
      setData(null);
      location.replace("/play");
    } catch (e) {
      setError(`退出失败：${e.message}。请重试。`);
      setSigningOut(false);
    }
  };
  const [prefs, setPrefs] = useState(() => {
    const saved = lsGetJSON("player-reading", {});
    const theme =
      saved.theme || (typeof saved.night === "boolean" ? "manual" : "system");
    return {
      font: 18,
      ...saved,
      theme,
      night:
        theme === "system"
          ? window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false
          : saved.night,
    };
  });
  const navigate = useCallback((url) => {
    if (url === "/play/saves") setSaveSearch("");
    history.pushState({}, "", url);
    setPath(url);
    window.scrollTo(0, 0);
  }, []);
  const reload = useCallback(async () => {
    try {
      const session = await window.api.player.session();
      const result = session.authenticated
        ? await window.api.player.bootstrap()
        : { ...(await window.api.player.catalog()), user: null, saves: [], wallet: null };
      if (!Array.isArray(result?.stories))
        throw new Error("玩家服务尚未启动，请刷新或重启后端服务。");
      setData(result);
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }, []);
  useEffect(() => {
    reload();
    const pop = () => setPath(location.pathname);
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, [reload]);
  useEffect(() => {
    lsSetJSON("player-reading", prefs);
    document.documentElement.dataset.reading = prefs.night ? "night" : "day";
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content", prefs.night ? "oklch(20% 0.008 255)" : "oklch(96% 0.006 255)",
    );
  }, [prefs]);
  useEffect(() => {
    if (prefs.theme !== "system") return;
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const change = (event) => setPrefs((p) => ({ ...p, night: event.matches }));
    media?.addEventListener("change", change);
    return () => media?.removeEventListener("change", change);
  }, [prefs.theme]);
  const archive = path === "/play/saves";
  const saveId = /^\/play\/saves\/(\d+)$/.exec(path)?.[1];
  const storyId = /^\/play\/stories\/(\d+)$/.exec(path)?.[1];
  const story = data?.stories.find((s) => String(s.id) === storyId);
  return (
    <div
      className={`player-app ${saveId ? "has-workspace" : "player-entry"}`}
      style={{ "--reading-size": `${prefs.font}px` }}
    >
      <a className="skip-link" href="#player-main">
        跳到正文
      </a>
      <header className="player-header">
        <button aria-label="故事大厅" className="player-brand" onClick={() => navigate("/play")}>
          <BookOpen size={25} weight="light" />
          <span>故事之间</span>
        </button>
        <div className="player-main-nav" role="navigation" aria-label="故事导航">
          <button aria-current={!archive && !saveId && path !== "/play/wallet" && path !== "/play/manage" ? "page" : undefined} onClick={() => { setSearch(""); navigate("/play"); }}>
            <BookOpen size={18} aria-hidden="true" />故事大厅
          </button>
          <button aria-current={archive ? "page" : undefined} onClick={() => navigate("/play/saves")}>
            <FolderOpen size={18} aria-hidden="true" />我的存档
          </button>
        </div>
        {data?.user && <button className="wallet-link" aria-current={path === "/play/wallet" ? "page" : undefined} onClick={() => navigate("/play/wallet")}>
          <Coins size={19} aria-hidden="true" />
          <span>{data.wallet ? points(data.wallet.free_micro + data.wallet.permanent_micro) : "—"} 积分</span>
        </button>}
        <nav aria-label="玩家导航">
          <button className="header-help" aria-label="指引" onClick={() => setHelpOpen(true)}><Question size={21} aria-hidden="true" /><span>指引</span></button>
          <button className="icon-button" aria-label={prefs.night ? "切换日间阅读" : "切换夜间阅读"} onClick={() => setPrefs((p) => ({ ...p, night: !p.night, theme: "manual" }))}>
            {prefs.night ? <Sun size={21} /> : <Moon size={21} />}
          </button>
          {data?.user ? (
            <details className="player-account" onKeyDown={(event) => {
              if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary").focus(); }
            }}>
              <summary aria-label="账户菜单"><UserCircle size={22} aria-hidden="true" /><span>账户</span><CaretDown size={12} aria-hidden="true" /></summary>
              <div className="player-account-menu">
                <strong>{data.user.name}</strong>
                <button disabled={signingOut} onClick={logout}>{signingOut ? "正在退出……" : "退出登录 / 切换账号"}</button>
              </div>
            </details>
          ) : !data ? <span className="header-account-loading" aria-hidden="true" /> : <Button quiet onClick={login}>登录 / 注册</Button>}
        </nav>
      </header>
      <PlayerHelp open={helpOpen} onClose={() => setHelpOpen(false)} />
      {data && error && <div className="player-shell" role="alert"><Notice error>{error}</Notice></div>}
      {!data ? (
        error ? (
          <main id="player-main" className="player-shell">
            <Notice error>{error}</Notice>
            <Button onClick={reload}>重新加载</Button>
          </main>
        ) : (
          <Loading />
        )
      ) : !data.user && (saveId || archive || path === "/play/wallet" || path === "/play/manage") ? (
        <main id="player-main" className="player-shell">
          <Empty title="登录后继续">存档、游玩和积分信息仅对本人开放。</Empty>
          <Button onClick={login}>登录后继续</Button>
          <Button quiet onClick={() => navigate("/play")}>浏览故事</Button>
        </main>
      ) : saveId ? (
        <Reader
          key={saveId}
          saveId={Number(saveId)}
          uid={data.user.id}
          navigate={navigate}
          prefs={prefs}
          setPrefs={setPrefs}
          refreshWallet={reload}
          saves={data.saves}
        />
      ) : path === "/play/wallet" ? (
        <Wallet refresh={reload} navigate={navigate} />
      ) : path === "/play/manage" && data.user?.admin ? (
        <Manage navigate={navigate} />
      ) : storyId ? (
        story ? (
          <Start key={story.id} story={story} navigate={navigate} refresh={reload} guest={!data.user} login={login} />
        ) : (
          <main id="player-main" className="player-shell">
            <Empty title="故事暂未上架">可以返回故事大厅，选择其他故事。</Empty>
            <Button onClick={() => navigate("/play")}>返回大厅</Button>
          </main>
        )
      ) : (
        <Lobby data={data} navigate={navigate} search={archive ? saveSearch : search} setSearch={archive ? setSaveSearch : setSearch} onHelp={() => setHelpOpen(true)} archive={archive} />
      )}
    </div>
  );
}

export function Start({ story, navigate, refresh, guest = false, login }) {
  const [identity, setIdentity] = useState(
    String(story.identities[0]?.id || ""),
  );
  const [name, setName] = useState(""),
    [background, setBackground] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [martialSoul, setMartialSoul] = useState({
    mode: "recommended",
    name: story.martial_soul_creation?.choices[0]?.name || "",
  });
  const start = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await window.api.player.create({
        story_id: story.id,
        name: name.trim(),
        identity_id: identity,
        background,
        ...(story.martial_soul_creation ? { martial_soul: martialSoul } : {}),
      });
      await refresh();
      navigate(`/play/saves/${result.save.id}`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <main id="player-main" className="player-shell start-page entry-start" tabIndex={-1}>
      <button className="back-link" onClick={() => navigate("/play")}>
        <ArrowLeft size={18} aria-hidden="true" /> 故事大厅
      </button>
      <div className="entry-start-layout">
        <aside className="start-story" aria-label="故事介绍">
          <div className="start-story-heading">
            <BookCover story={story} large />
            <div>
              <span className="lobby-caption"><BookOpen size={15} aria-hidden="true" />{story.identities.length} 种可选身份</span>
              <h1>{story.title}</h1>
            </div>
          </div>
          <p className="start-introduction">{story.introduction}</p>
          <p className="start-free-note"><CheckCircle size={17} aria-hidden="true" />创建角色免费</p>
        </aside>
        <section className="start-creation" aria-label={guest ? "可选身份" : "创建角色"}>
          {guest ? (
            <div className="guest-story-details">
              <h2>可选身份</h2>
              <dl className="guest-identities">
                {story.identities.map((item) => <div key={item.id}><dt>{item.name}</dt><dd>{item.description || item.role}</dd></div>)}
              </dl>
              <div className="creation-submit">
                <Button onClick={login}>登录后创建角色<ArrowRight size={18} /></Button>
                <p className="fine-print">生成剧情前会显示积分估算与本次费用上限。</p>
              </div>
            </div>
          ) : (
            <form onSubmit={start} aria-busy={busy}>
              <fieldset disabled={busy} className="entry-identity-options">
                <legend><span className="creation-step" aria-hidden="true">1</span>选择身份</legend>
                {story.identities.map((item) => (
                  <label className={`identity-choice ${identity === String(item.id) ? "selected" : ""}`} key={item.id}>
                    <input type="radio" name="identity" value={item.id} checked={identity === String(item.id)} onChange={() => setIdentity(String(item.id))} />
                    <span><strong>{item.name}</strong><small>{item.description || item.role}</small></span>
                  </label>
                ))}
              </fieldset>
              <fieldset disabled={busy} className="entry-character-fields">
                <legend><span className="creation-step" aria-hidden="true">2</span>角色信息</legend>
                <label className="field-label" htmlFor="player-name">你的名字</label>
                <input id="player-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={40} required placeholder="输入角色名字" autoComplete="off" />
                <details className="background-details">
                  <summary>补充角色背景<span>可选</span></summary>
                  <textarea aria-label="角色背景" value={background} onChange={(event) => setBackground(event.target.value)} maxLength={1200} rows={4} placeholder="经历、性格，或你想带入故事的心愿" />
                </details>
                {story.martial_soul_creation && <MartialSoulPicker config={story.martial_soul_creation} value={martialSoul} onChange={setMartialSoul} />}
              </fieldset>
              {error && <Notice error>{error}</Notice>}
              <div className="creation-submit">
                <Button type="submit" disabled={busy || !name.trim() || !identity}>
                  {busy ? "正在准备角色……" : "带着这个身份出发"}{!busy && <ArrowRight size={18} aria-hidden="true" />}
                </Button>
                <p className="fine-print">创建角色免费。进入后先查看开场的积分估算，再开始生成。</p>
              </div>
            </form>
          )}
        </section>
      </div>
    </main>
  );
}
