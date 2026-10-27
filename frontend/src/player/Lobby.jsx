import React, { useEffect, useState } from "react";
import { ArrowRight, BookOpen, Clock, FolderOpen, MagnifyingGlass, Play, X } from "@phosphor-icons/react";
import { BookCover, Button, Empty, StoryCard } from "./shared.jsx";

function SaveList({ saves, navigate }) {
  return (
    <ul className="lobby-save-list">
      {saves.map((save) => (
        <li key={save.id}>
          <button onClick={() => navigate(`/play/saves/${save.id}`)}>
            <span className="save-avatar" aria-hidden="true">{Array.from(save.name || save.title || "")[0]}</span>
            <span className="save-copy">
              <strong>{save.story_title}</strong>
              <span>{save.name || save.title} · {save.turn > 0 ? `第 ${save.turn} 回合` : "待开场"}</span>
            </span>
            <ArrowRight size={18} aria-hidden="true" />
          </button>
        </li>
      ))}
    </ul>
  );
}

export function Lobby({ data, navigate, search, setSearch, onHelp, archive = false }) {
  const [page, setPage] = useState(1);
  const [remote, setRemote] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [retry, setRetry] = useState(0);
  const saveTotal = data.save_total ?? data.saves.length;
  const paginated = archive && saveTotal > data.saves.length;
  useEffect(() => {
    if (!paginated) return;
    let current = true;
    setRemote(null);
    setLoadError("");
    const timer = setTimeout(() => {
      window.api.player.savesPage(page, search.trim()).then(
        result => { if (current) setRemote(result); },
        error => { if (current) setLoadError(error.message); },
      );
    }, search.trim() ? 200 : 0);
    return () => { current = false; clearTimeout(timer); };
  }, [paginated, page, search, retry]);
  const query = search.trim().toLocaleLowerCase();
  const stories = data.stories.filter((story) => `${story.title} ${story.introduction}`.toLocaleLowerCase().includes(query));
  const localSaves = data.saves.filter((save) => `${save.story_title} ${save.name || ""} ${save.title || ""}`.toLocaleLowerCase().includes(query));
  const saves = paginated ? (remote?.items || []) : localSaves;
  const latest = data.saves[0];
  const latestStory = latest && data.stories.find((story) => story.id === latest.story_id);
  return (
    <main id="player-main" className="player-shell player-lobby" tabIndex={-1}>
      <div className="lobby-toolbar">
        <h1>{archive ? "我的存档" : "故事大厅"}</h1>
        <div className="lobby-search" role="search">
          <MagnifyingGlass size={19} aria-hidden="true" />
          <input
            type="search"
            aria-label={archive ? "搜索存档" : "搜索故事"}
            placeholder={archive ? "搜索故事或角色名" : "搜索故事名称或简介"}
            value={search}
            maxLength={archive ? 120 : undefined}
            onChange={(event) => { setPage(1); setSearch(event.target.value); }}
          />
          {search && <button className="icon-button" aria-label="清除搜索" onClick={() => { setPage(1); setSearch(""); }}><X size={17} /></button>}
        </div>
      </div>

      {!archive && latest && (
        <section className="lobby-resume" aria-label="最近游玩">
          {latestStory && <BookCover story={latestStory} />}
          <div className="resume-copy">
            <span className="lobby-caption"><Clock size={15} aria-hidden="true" />最近游玩</span>
            <h2>{latest.story_title}</h2>
            <p>{latest.name || latest.title} <span>·</span> {latest.turn > 0 ? `第 ${latest.turn} 回合` : "待开场"}</p>
          </div>
          <Button onClick={() => navigate(`/play/saves/${latest.id}`)}><Play size={16} weight="fill" aria-hidden="true" />继续游玩</Button>
        </section>
      )}

      {!archive && (!data.user || !latest) && (
        <div className="lobby-welcome">
          <BookOpen size={20} aria-hidden="true" />
          <p>{data.user ? "选择一个故事，创建你的第一个角色。" : "先找一个喜欢的故事，登录后创建角色、保存进度。"}</p>
          <button className="text-button" onClick={onHelp}>游玩指引<ArrowRight size={15} aria-hidden="true" /></button>
        </div>
      )}

      {archive ? (
        <section className="lobby-archive" aria-label="存档列表">
          <div className="lobby-section-heading"><h2>全部存档</h2><span role="status">{paginated ? (remote ? `${remote.total} 个` : "正在加载") : `${saves.length} 个${query ? ` / 共 ${saveTotal} 个` : ""}`}</span></div>
          {loadError && <div role="alert">加载存档失败：{loadError} <Button quiet onClick={() => setRetry(value => value + 1)}>重试</Button></div>}
          {paginated && !remote ? null : saves.length ? <SaveList saves={saves} navigate={navigate} /> : (
            <Empty title={query ? "没有找到这个存档" : "还没有存档"}>
              {query ? "换个故事名称或角色名试试。" : "选择故事并创建角色后，进度会保存在这里。"}
            </Empty>
          )}
          {paginated && remote?.pages > 1 && <div className="lobby-section-heading">
            <Button quiet disabled={remote.page <= 1} onClick={() => setPage(remote.page - 1)}>上一页</Button>
            <span>第 {remote.page} / {remote.pages} 页</span>
            <Button quiet disabled={remote.page >= remote.pages} onClick={() => setPage(remote.page + 1)}>下一页</Button>
          </div>}
          {!saveTotal && <Button onClick={() => navigate("/play")}>去选择故事<ArrowRight size={17} /></Button>}
        </section>
      ) : (
        <div className="lobby-columns">
          <section className="lobby-library" aria-labelledby="lobby-library-title">
            <div className="lobby-section-heading"><h2 id="lobby-library-title">全部故事</h2><span role="status">{stories.length} 部{query && ` / 共 ${data.stories.length} 部`}</span></div>
            <div className="lobby-stories">
              {stories.map((story) => <StoryCard key={story.id} story={story} onStart={() => navigate(`/play/stories/${story.id}`)} onComments={() => navigate(`/play/stories/${story.id}/comments`)} />)}
            </div>
            {!stories.length && <Empty title={data.stories.length ? "没有找到这个故事" : "下一段故事正在准备中"}>{data.stories.length ? "换个关键词试试。" : "故事上架后会出现在这里。"}</Empty>}
            {query && !stories.length && data.stories.length > 0 && <Button quiet onClick={() => setSearch("")}>清除关键词</Button>}
          </section>
          <aside className="lobby-sidebar" aria-label="我的存档与指引">
            <div className="lobby-section-heading">
              <h2><FolderOpen size={18} aria-hidden="true" />我的存档</h2>
              {saveTotal > 0 && <button className="text-button" onClick={() => navigate("/play/saves")}>全部 {saveTotal}<ArrowRight size={14} /></button>}
            </div>
            {data.saves.length ? <SaveList saves={data.saves.slice(0, 4)} navigate={navigate} /> : <p className="lobby-sidebar-empty">{data.user ? "你的角色与游玩进度会收录在这里。" : "登录后，在这里继续你的故事。"}</p>}
            <div className="lobby-guide">
              <h2>开始之前</h2>
              <p>创建角色与阅读存档免费。生成剧情前，会显示积分估算与本次费用上限。</p>
              <button className="text-button" onClick={onHelp}>查看游玩指引<ArrowRight size={16} /></button>
            </div>
          </aside>
        </div>
      )}
      <footer className="player-footer lobby-footer">
        <span>故事之间</span>
        <div>
          {data.user?.admin && <button onClick={() => navigate("/play/manage")}>玩家服务管理</button>}
        </div>
      </footer>
    </main>
  );
}
