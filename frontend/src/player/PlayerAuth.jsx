import React from "react";
import { BookOpen, ArrowRight } from "@phosphor-icons/react";
import "../i18n/index.js";
import { LoginApp } from "../login-app.jsx";
import "./auth.css";

export default function PlayerAuth({ register = false }) {
  return (
    <main id="player-main" className="player-auth">
      <section className="player-auth-intro" aria-labelledby="auth-intro-title">
        <BookOpen size={36} weight="light" aria-hidden="true" />
        <p className="eyebrow">故事之间 · 你的下一章</p>
        <h2 id="auth-intro-title">走进故事，<br />成为其中的人。</h2>
        <p>选一个世界，遇见同行的人。<br />接下来的故事，由你的选择继续。</p>
        <dl>
          <div><dt>选择故事</dt><dd>从感兴趣的世界与身份开始。</dd></div>
          <div><dt>留下足迹</dt><dd>角色与进度自动保存，随时回来继续。</dd></div>
          <div><dt>安心游玩</dt><dd>创建角色与阅读免费，生成剧情前确认积分。</dd></div>
        </dl>
        <a href="/play">先逛逛故事大厅<ArrowRight size={17} aria-hidden="true" /></a>
      </section>
      <LoginApp initialMode={register ? "register" : "login"} />
    </main>
  );
}
