import React, { useEffect, useRef, useState } from "react";
import { ArrowLeft, ChatCircleText } from "@phosphor-icons/react";
import { lsGet, lsSet } from "../lib/storage.js";
import { Button, Notice } from "./shared.jsx";
import { useComposerKeys } from "./useComposerKeys.js";

export function Comments({ story, user, navigate, login, returnTo }) {
  const draftKey = `story-comment-${user?.id || "guest"}-${story.id}`;
  const [draft, setDraft] = useState(() => lsGet(draftKey, ""));
  const [items, setItems] = useState([]), [cursor, setCursor] = useState(null);
  const [loading, setLoading] = useState(true), [loadError, setLoadError] = useState("");
  const [posting, setPosting] = useState(false), [error, setError] = useState("");
  const [confirm, setConfirm] = useState(null), [deleting, setDeleting] = useState(null);
  const [notice, setNotice] = useState("");
  const inFlight = useRef(false);
  useEffect(() => { lsSet(draftKey, draft); }, [draftKey, draft]);
  useEffect(() => {
    let active = true;
    window.api.player.comments(story.id).then((page) => {
      if (active) { setItems(page.items); setCursor(page.next_cursor); setLoading(false); }
    }).catch((e) => { if (active) { setLoadError(e.message); setLoading(false); } });
    return () => { active = false; };
  }, [story.id]);
  const load = async () => {
    setLoading(true); setLoadError("");
    try {
      const page = await window.api.player.comments(story.id, cursor);
      setItems((old) => cursor ? [...old, ...page.items.filter((i) => !old.some((o) => o.id === i.id))] : page.items);
      setCursor(page.next_cursor);
    } catch (e) { setLoadError(e.message); }
    finally { setLoading(false); }
  };
  const post = async (event) => {
    event?.preventDefault();
    if (!user || loading || inFlight.current || !draft.trim() || draft.length > 2000) return;
    inFlight.current = true; setPosting(true); setError(""); setNotice("");
    try {
      const item = await window.api.player.postComment(story.id, draft.trim());
      setItems((old) => [item, ...old.filter((i) => i.id !== item.id)]);
      setDraft(""); setNotice("评论已发布");
    } catch (e) { setError(e.message); }
    finally { inFlight.current = false; setPosting(false); }
  };
  const remove = async (id) => {
    if (deleting !== null) return;
    setDeleting(id); setError(""); setNotice("");
    try {
      await window.api.player.deleteComment(story.id, id);
      setItems((old) => old.filter((i) => i.id !== id));
      setConfirm(null); setNotice("评论已删除");
    } catch (e) { setError(e.message); }
    finally { setDeleting(null); }
  };
  const keys = useComposerKeys(post);
  return (
    <main id="player-main" className="player-shell story-comments" tabIndex={-1}>
      <header className="comments-heading">
        <button className="back-link" aria-label={returnTo ? "返回当前存档" : "返回故事介绍"} onClick={() => navigate(returnTo || `/play/stories/${story.id}`)}><ArrowLeft size={20} />{returnTo ? "返回当前存档" : "返回故事介绍"}</button>
        <div><span>{story.title}</span><h1>故事评论</h1></div>
      </header>
      <p className="comments-note">聊聊人物、选择和游玩感受。评论公开可见，请勿留下私人信息。</p>
      {user ? (
        <form className="comment-composer" onSubmit={post} aria-label="发表评论">
          <label htmlFor="story-comment">以{user.name}的身份发表评论</label>
          <textarea id="story-comment" rows={4} maxLength={2000} value={draft} disabled={posting}
            onChange={(e) => setDraft(e.target.value)} placeholder="写下你的想法……" {...keys} />
          <div className="comment-composer-actions"><span>{draft.length}/2000 · Ctrl / ⌘ + Enter 发布</span><Button type="submit" disabled={posting || loading || !draft.trim()}>{posting ? "正在发布……" : "发布评论"}</Button></div>
        </form>
      ) : <div className="comments-login"><p>登录后可以发表评论。</p><Button onClick={login}>登录后评论</Button></div>}
      {error && <Notice error>{error}</Notice>}
      <p className="comments-feedback" role="status">{notice}</p>
      <section aria-labelledby="comments-list-title" aria-busy={loading}>
        <h2 id="comments-list-title"><ChatCircleText size={19} />最新评论</h2>
        {!items.length && loading && <p role="status">正在加载评论……</p>}
        {!items.length && !loading && !loadError && <p className="comments-empty">还没有评论，来聊聊这个故事吧。</p>}
        <ol className="comment-list">
          {items.map((item) => (
            <li key={item.id}>
              <article>
                <header className="comment-meta"><strong>{item.author}</strong><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false })}</time></header>
                <p className="comment-content">{item.content}</p>
                {item.can_delete && (confirm === item.id ? (
                  <div className="comment-delete-confirm"><span>确定删除这条评论？</span><button className="text-button" disabled={deleting !== null} onClick={() => remove(item.id)}>{deleting === item.id ? "正在删除……" : "确认删除"}</button><button className="text-button" disabled={deleting !== null} onClick={() => setConfirm(null)}>取消</button></div>
                ) : <button className="text-button comment-delete" disabled={deleting !== null} aria-label={`删除${item.author}的评论`} onClick={() => setConfirm(item.id)}>{user?.admin ? "删除评论" : "删除"}</button>)}
              </article>
            </li>
          ))}
        </ol>
        {loadError && <Notice error>{loadError}</Notice>}
        {(cursor || loadError) && <Button quiet disabled={loading} onClick={load}>{loading ? "正在加载……" : loadError ? "重试加载" : "加载更早评论"}</Button>}
      </section>
    </main>
  );
}
