import React from "react";
import { createRoot } from "react-dom/client";
import "../api-client.js";
import "../player/player.css";
import "../player/workspace.css";
import { PlayerApp } from "../player/PlayerApp.jsx";

class PlayerBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <main className="player-shell">
        <h1>页面暂时未能打开</h1>
        <p>已保存的故事仍在。刷新页面后继续。</p>
        <button onClick={() => location.reload()}>刷新页面</button>
      </main>
    ) : (
      this.props.children
    );
  }
}
createRoot(document.getElementById("root")).render(
  <PlayerBoundary>
    <PlayerApp />
  </PlayerBoundary>,
);
