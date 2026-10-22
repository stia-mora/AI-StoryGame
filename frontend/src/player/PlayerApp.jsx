import React, { useCallback, useEffect, useState } from "react";
import {
  BookOpen,
  ArrowLeft,
  ArrowRight,
  Coins,
  Moon,
  Sun,
  MagnifyingGlass,
  Play,
  Clock,
} from "@phosphor-icons/react";
import { lsGetJSON, lsSetJSON } from "../lib/storage.js";
import {
  Button,
  Empty,
  Loading,
  Notice,
  StoryCard,
  points,
  BookCover,
} from "./shared.jsx";
import { Reader } from "./Reader.jsx";
import { Wallet } from "./Wallet.jsx";
import { Manage } from "./Manage.jsx";
import { MartialSoulPicker } from "./MartialSoulPicker.jsx";
import { PlayerHelp } from "./PlayerHelp.jsx";

export function PlayerApp() {
  const [path, setPath] = useState(location.pathname);
  const [data, setData] = useState(null),
    [error, setError] = useState("");
  const [search, setSearch] = useState("");
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
  const saveId = /^\/play\/saves\/(\d+)$/.exec(path)?.[1];
  const storyId = /^\/play\/stories\/(\d+)$/.exec(path)?.[1];
  const story = data?.stories.find((s) => String(s.id) === storyId);
  return (
    <div
      className={`player-app ${saveId ? "has-workspace" : ""}`}
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
        <button
          className="player-home-link"
          aria-current={path === "/play" || path === "/Player.html" ? "page" : undefined}
          onClick={() => navigate("/play")}
        >
          故事大厅
        </button>
        <nav aria-label="玩家导航">
          <button className="text-button" onClick={() => setHelpOpen(true)}>指引</button>
          <button
            className="icon-button"
            aria-label={prefs.night ? "切换日间阅读" : "切换夜间阅读"}
            onClick={() => setPrefs((p) => ({ ...p, night: !p.night, theme: "manual" }))}
          >
            {prefs.night ? <Sun size={21} /> : <Moon size={21} />}
          </button>
          {data?.user && <button
            className="wallet-link"
            onClick={() => navigate("/play/wallet")}
          >
            <Coins size={19} />
            <span>
              {data?.wallet
                ? points(data.wallet.free_micro + data.wallet.permanent_micro)
                : "—"}{" "}
              积分
            </span>
          </button>}
          {data?.user ? (
            <details className="player-account" onKeyDown={(event) => {
              if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary").focus(); }
            }}>
              <summary aria-label="账户菜单">账户</summary>
              <div className="player-account-menu">
                <strong>{data.user.name}</strong>
                <button disabled={signingOut} onClick={logout}>{signingOut ? "正在退出……" : "退出登录 / 切换账号"}</button>
              </div>
            </details>
          ) : <button className="text-button" onClick={login}>登录 / 注册</button>}
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
      ) : !data.user && (saveId || path === "/play/wallet" || path === "/play/manage") ? (
        <main id="player-main" className="player-shell">
          <Empty title="登录后继续">存档、游玩和积分信息仅对本人开放。</Empty>
          <Button onClick={login}>登录后继续</Button>
          <Button onClick={() => navigate("/play")}>浏览故事</Button>
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
            <Empty title="故事暂未上架">可以返回故事书架，选择其他故事。</Empty>
            <Button onClick={() => navigate("/play")}>返回书架</Button>
          </main>
        )
      ) : (
        <main id="player-main" className="player-shell home">
          <div className="home-intro">
            <h1><BookOpen size={22} />故事大厅</h1>
            <label className="library-search">
              <span className="sr-only">搜索故事</span>
              <MagnifyingGlass size={18} />
              <input
                type="search"
                placeholder="搜索故事"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
          </div>
          {(!data.user || data.saves.length === 0) && <div className="player-onboarding">
            <span>{data.user ? "选择故事与身份，开始你的第一段冒险。" : "以游客身份浏览故事，登录后创建角色并保存进度。"}</span>
            <button className="text-button" onClick={() => setHelpOpen(true)}>查看游玩指引</button>
          </div>}
          {data.saves.length > 0 && (
            <section className="continue-story">
              <span className="continue-label"><Clock size={18} />最近游玩</span>
              <h2>{data.saves[0].story_title}</h2>
              <span className="save-metadata">{data.saves[0].name} · 第 {data.saves[0].turn} 回合</span>
              <Button
                onClick={() => navigate(`/play/saves/${data.saves[0].id}`)}
              >
                <Play size={16} weight="fill" />继续游玩
              </Button>
            </section>
          )}
          <div className="section-heading">
            <h2>全部故事</h2>
            <span>{data.stories.length} 部</span>
          </div>
          <div className="workspace-library">
            {data.stories.length ? (
              data.stories
                .filter((s) =>
                  `${s.title} ${s.introduction}`.includes(search.trim()),
                )
                .map((s) => (
                  <StoryCard
                    key={s.id}
                    story={s}
                    onStart={() => navigate(`/play/stories/${s.id}`)}
                  />
                ))
            ) : (
              <Empty title="下一段故事正在准备中">
                故事上架后会出现在这里。
              </Empty>
            )}
          </div>
          {data.stories.length > 0 &&
            !data.stories.some((s) =>
              `${s.title} ${s.introduction}`.includes(search.trim()),
            ) && <Empty title="没有找到这个故事">换个关键词试试。</Empty>}
          {data.saves.length > 1 && (
            <section className="older-saves" aria-label="其他存档">
              <h2>其他存档</h2>
              {data.saves.slice(1).map((s) => (
                <button
                  key={s.id}
                  onClick={() => navigate(`/play/saves/${s.id}`)}
                >
                  <span>
                    {s.story_title} · {s.name}
                  </span>
                  <span className="muted">第 {s.turn} 回合</span>
                  <ArrowRight size={16} />
                </button>
              ))}
            </section>
          )}
          <footer className="player-footer">
            <span>开局和行动按实际模型用量消耗积分，阅读存档免费。</span>
            {data.user?.creator && <a href="/Platform.html">创作工作台</a>}
            {data.user?.admin && (
              <button onClick={() => navigate("/play/manage")}>
                玩家服务管理
              </button>
            )}
          </footer>
        </main>
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
    <main id="player-main" className="player-shell start-page">
      <button className="back-link" onClick={() => navigate("/play")}>
        <ArrowLeft size={18} /> 故事书架
      </button>
      <div className="start-layout">
        <BookCover story={story} large />
        <section>
          <span className="eyebrow">你会是谁？</span>
          <h1>{story.title}</h1>
          <p className="muted">{story.introduction}</p>
          {guest ? <div className="guest-story-details">
            <h2>可选身份</h2>
            {story.identities.map((i) => <p key={i.id}><strong>{i.name}</strong><br />{i.description || i.role}</p>)}
            <Button onClick={login}>登录后创建角色</Button>
            <p className="fine-print">创建角色免费，生成前会显示积分估算与费用上限。</p>
          </div> : <form onSubmit={start}>
            <fieldset>
              <legend>选择一个起点</legend>
              {story.identities.map((i) => (
                <label
                  className={`identity-choice ${identity === String(i.id) ? "selected" : ""}`}
                  key={i.id}
                >
                  <input
                    type="radio"
                    name="identity"
                    value={i.id}
                    checked={identity === String(i.id)}
                    onChange={() => setIdentity(String(i.id))}
                  />
                  <span>
                    <strong>{i.name}</strong>
                    <small>{i.description || i.role}</small>
                  </span>
                </label>
              ))}
            </fieldset>
            {story.martial_soul_creation && (
              <MartialSoulPicker
                config={story.martial_soul_creation}
                value={martialSoul}
                onChange={setMartialSoul}
              />
            )}
            <label className="field-label" htmlFor="player-name">
              你的名字
            </label>
            <input
              id="player-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={40}
              required
              placeholder="这个世界会如何称呼你"
              autoComplete="off"
            />
            <details className="background-details">
              <summary>补充你的背景（可选）</summary>
              <textarea
                aria-label="角色背景"
                value={background}
                onChange={(e) => setBackground(e.target.value)}
                maxLength={1200}
                rows={4}
                placeholder="你想带入故事的经历、性格或心愿"
              />
            </details>
            {error && <Notice error>{error}</Notice>}
            <Button type="submit" disabled={busy || !name.trim()}>
              {busy ? "正在准备角色……" : "带着这个身份出发"}
            </Button>
            <p className="fine-print">
              创建角色免费。进入后会先显示开场的积分估算，由你开始生成。
            </p>
          </form>}
        </section>
      </div>
    </main>
  );
}
