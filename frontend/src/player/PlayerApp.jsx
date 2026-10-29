import React, { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Coins,
  Moon,
  Sun,
  FolderOpen,
  Question,
  UserCircle,
  CaretDown,
  PenNib,
} from "@phosphor-icons/react";
import { lsGetJSON, lsSetJSON } from "../lib/storage.js";
import {
  Button,
  Empty,
  Loading,
  Notice,
  points,
} from "./shared.jsx";
import { Reader } from "./Reader.jsx";
import { Wallet } from "./Wallet.jsx";
import { Manage } from "./Manage.jsx";
import { Initialize } from "./Initialize.jsx";
import { PlayerHelp } from "./PlayerHelp.jsx";
import { Lobby } from "./Lobby.jsx";
import { Comments } from "./Comments.jsx";

const PlayerAuth = lazy(() => import("./PlayerAuth.jsx"));
const Authoring = lazy(() => import("./Authoring.jsx").then(m => ({ default: m.Authoring })));
const AuthoringAdmin = lazy(() => import("./Authoring.jsx").then(m => ({ default: m.AuthoringAdmin })));

export function PlayerApp() {
  const [route, setRoute] = useState(() => ({ pathname: location.pathname, search: location.search }));
  const path = route.pathname;
  const authPage = path === "/Login.html" || /^\/play\/(login|register)\/?$/.test(path);
  const [data, setData] = useState(null),
    [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [saveSearch, setSaveSearch] = useState("");
  const [helpOpen, setHelpOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const latestReload = useRef(0);
  const latestWallet = useRef(0);
  const previousPath = useRef(path);
  const accountMenu = useRef(null);
  const login = () => navigate(`/play/login?next=${encodeURIComponent(location.pathname + location.search + location.hash)}`);
  const logout = async () => {
    setSigningOut(true);
    try {
      await window.api.auth.logout();
      latestReload.current++;
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
    if (accountMenu.current) accountMenu.current.open = false;
    if (url === "/play/saves") setSaveSearch("");
    history.pushState({}, "", url);
    const target = new URL(url, location.origin);
    setRoute({ pathname: target.pathname, search: target.search });
    window.scrollTo(0, 0);
  }, []);
  const updateWallet = useCallback((wallet) => {
    // Invalidate bootstrap reads started before this confirmed balance change.
    latestReload.current++;
    latestWallet.current++;
    setData((old) => old ? { ...old, wallet } : old);
  }, []);
  const refreshWallet = useCallback(async () => {
    const revision = ++latestWallet.current;
    const wallet = await window.api.player.wallet();
    if (revision === latestWallet.current) updateWallet(wallet);
  }, [updateWallet]);
  useEffect(() => {
    const dismiss = (event) => {
      if (accountMenu.current && !accountMenu.current.contains(event.target)) accountMenu.current.open = false;
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("focusin", dismiss);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("focusin", dismiss);
    };
  }, []);
  useEffect(() => {
    if (accountMenu.current) accountMenu.current.open = false;
  }, [path]);
  const reload = useCallback(async () => {
    const request = ++latestReload.current;
    try {
      const session = await window.api.player.session();
      const result = session.authenticated
        ? await window.api.player.bootstrap()
        : { ...(await window.api.player.catalog()), user: null, saves: [], wallet: null };
      if (!Array.isArray(result?.stories))
        throw new Error("玩家服务尚未启动，请刷新或重启后端服务。");
      if (request !== latestReload.current) return;
      setData(result);
      setError("");
    } catch (e) {
      if (request !== latestReload.current) return;
      setError(e.message);
    }
  }, []);
  useEffect(() => {
    if (!authPage) reload();
    const pop = () => setRoute({ pathname: location.pathname, search: location.search });
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, [reload, authPage]);
  useEffect(() => {
    if (previousPath.current !== path && (path === "/play" || path === "/play/saves")) reload();
    previousPath.current = path;
  }, [path, reload]);
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
  const commentsId = /^\/play\/stories\/(\d+)\/comments$/.exec(path)?.[1];
  const commentsSave = new URLSearchParams(location.search).get("save");
  const commentsReturn = /^\d+$/.test(commentsSave || "") ? `/play/saves/${commentsSave}` : null;
  const story = data?.stories.find((s) => String(s.id) === (storyId || commentsId));
  return (
    <div
      className={`player-app ${saveId || storyId ? "has-workspace" : "player-entry"}${authPage ? " player-auth-page" : ""}`}
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
          <button aria-current={!authPage && !archive && !saveId && !path.startsWith("/play/authoring") && path !== "/play/wallet" && path !== "/play/manage" ? "page" : undefined} onClick={() => { setSearch(""); navigate("/play"); }}>
            <BookOpen size={18} aria-hidden="true" />故事大厅
          </button>
          <button aria-current={archive ? "page" : undefined} onClick={() => navigate("/play/saves")}>
            <FolderOpen size={18} aria-hidden="true" />我的存档
          </button>
          <button aria-current={path.startsWith("/play/authoring") ? "page" : undefined} onClick={() => navigate("/play/authoring")}>
            <PenNib size={18} aria-hidden="true" />我的创作
          </button>
        </div>
        {data?.user && <button className="wallet-link" aria-current={path === "/play/wallet" ? "page" : undefined} onClick={() => navigate("/play/wallet")}>
          <Coins size={19} aria-hidden="true" />
          <span>{data.wallet ? points(data.wallet.free_micro + data.wallet.permanent_micro) : "—"} 积分</span>
          {data.wallet?.held_micro > 0 && <small>预留 {points(data.wallet.held_micro)}</small>}
        </button>}
        <nav aria-label="玩家导航">
          <button className="header-help" aria-label="指引" onClick={() => setHelpOpen(true)}><Question size={21} aria-hidden="true" /><span>指引</span></button>
          <button className="icon-button" aria-label={prefs.night ? "切换日间阅读" : "切换夜间阅读"} onClick={() => setPrefs((p) => ({ ...p, night: !p.night, theme: "manual" }))}>
            {prefs.night ? <Sun size={21} /> : <Moon size={21} />}
          </button>
          {data?.user ? (
            <details ref={accountMenu} className="player-account" onKeyDown={(event) => {
              if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary").focus(); }
            }}>
              <summary aria-label="账户菜单"><UserCircle size={22} aria-hidden="true" /><span>账户</span><CaretDown size={12} aria-hidden="true" /></summary>
              <div className="player-account-menu">
                <strong>{data.user.name}</strong>
                <button onClick={() => navigate("/play/authoring")}>我的创作</button>
                <button disabled={signingOut} onClick={logout}>{signingOut ? "正在退出……" : "退出登录 / 切换账号"}</button>
              </div>
            </details>
          ) : authPage ? null : !data ? <span className="header-account-loading" aria-hidden="true" /> : <Button quiet onClick={login}>登录 / 注册</Button>}
        </nav>
      </header>
      <PlayerHelp open={helpOpen} onClose={() => setHelpOpen(false)} />
      {data && error && <div className="player-shell" role="alert"><Notice error>{error}</Notice></div>}
      {authPage ? (
        <Suspense fallback={<Loading />}><PlayerAuth key={path} register={/^\/play\/register/.test(path)} /></Suspense>
      ) : !data ? (
        error ? (
          <main id="player-main" className="player-shell">
            <Notice error>{error}</Notice>
            <Button onClick={reload}>重新加载</Button>
          </main>
        ) : (
          <Loading />
        )
      ) : !data.user && (saveId || archive || path.startsWith("/play/authoring") || path === "/play/wallet" || path === "/play/manage") ? (
        <main id="player-main" className="player-shell">
          <Empty title={path.startsWith("/play/authoring") ? "登录后开始创作" : "登录后继续"}>{path.startsWith("/play/authoring") ? "连接创作 Agent、管理私人作品、试玩并提交上架。" : "存档、游玩和积分信息仅对本人开放。"}</Empty>
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
          refreshWallet={refreshWallet}
          saves={data.saves}
          saveTotal={data.save_total ?? data.saves.length}
        />
      ) : path.startsWith("/play/authoring") ? (
        <Suspense fallback={<Loading />}>{path === "/play/authoring-admin" && data.user.admin ? <AuthoringAdmin navigate={navigate} /> : <Authoring navigate={navigate} navigation={route} admin={data.user.admin} creator={data.user.creator} refreshAccount={reload} />}</Suspense>
      ) : path === "/play/wallet" ? (
        <Wallet onWalletChange={updateWallet} navigate={navigate} />
      ) : path === "/play/manage" && data.user?.admin ? (
        <Manage navigate={navigate} />
      ) : (storyId || commentsId) ? (
        story ? (
          commentsId ? <Comments key={`${story.id}-${data.user?.id || "guest"}`} story={story} user={data.user} navigate={navigate} login={login} returnTo={commentsReturn} /> : <Initialize key={story.id} uid={data.user?.id} story={story} navigate={navigate} refresh={reload} guest={!data.user} login={login} />
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
