import React, { useEffect, useState } from "react";

const phases = ["understanding", "retrieving", "generating", "saving"];
const elapsed = (milliseconds) => {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
};

export function GenerationProgress({ phase, startedAt, confirmedAt, opening = false }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const current = Math.max(0, phases.indexOf(phase));
  const labels = [opening ? "准备开场" : "理解行动", "整理资料", "生成剧情", "保存结算"];
  const waited = now - startedAt;
  return (
    <section className="generation-progress" aria-label="本轮生成进度">
      <ol aria-label="生成阶段">
        {labels.map((label, index) => (
          <li key={label} aria-current={index === current ? "step" : undefined} data-complete={index < current}>
            <span aria-hidden="true">{index < current ? "✓" : index + 1}</span>{label}
          </li>
        ))}
      </ol>
      <p><span role="timer" aria-label="本轮已等待时间">已等待 {elapsed(waited)}</span>
        {confirmedAt && <span>服务端最近响应：{elapsed(now - confirmedAt)} 前</span>}
      </p>
      <p className="fine-print">{waited >= 60000
        ? "等待较久，可以先查看历史回合或角色状态，也可以停止生成。剩余时间暂无法准确估算。"
        : "按实际生成阶段更新，耗时取决于模型响应。可以查看历史回合或角色状态。"}</p>
    </section>
  );
}
