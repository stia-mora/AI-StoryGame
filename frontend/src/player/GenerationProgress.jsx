import React, { useEffect, useState } from "react";

const phases = ["understanding", "retrieving", "generating", "saving"];
const elapsed = (milliseconds) => {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
};

const minutes = (seconds) => `${Math.max(0.5, Math.ceil(seconds / 30) / 2)} 分钟`;

export function GenerationProgress({ phase, startedAt, confirmedAt, opening = false, timing }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const current = Math.max(0, phases.indexOf(phase));
  const labels = [opening ? "准备开场" : "理解行动", "整理资料", "生成剧情", "保存结算"];
  const waited = now - startedAt;
  const remaining = timing && timing.high_seconds - waited / 1000;
  return (
    <section className="generation-progress" aria-label="本轮生成进度">
      <ol aria-label="生成阶段">
        {labels.map((label, index) => (
          <li key={label} aria-current={index === current ? "step" : undefined} data-complete={index < current}>
            <span aria-hidden="true">{index < current ? "✓" : index + 1}</span>{label}
          </li>
        ))}
      </ol>
      <p><span>阶段 {current + 1}/4</span><span role="timer" aria-label="本轮已等待时间">已等待 {elapsed(waited)}</span>
        {confirmedAt && <span>服务端最近响应：{elapsed(now - confirmedAt)} 前</span>}
      </p>
      {timing && <p className="fine-print">{remaining > 0 ? `剩余参考约 ${minutes(Math.max(0, timing.low_seconds - waited / 1000))}–${minutes(remaining)}` : "已超过近期参考用时，仍在等待本轮结果"} · 依据本存档同模型近期 {timing.samples} 次记录，非完成保证。</p>}
      <p className="fine-print">{timing ? "阶段数量不代表耗时比例。等待时可查看历史或角色状态，也可停止生成。" : waited >= 60000
        ? "等待较久，可以先查看历史回合或角色状态，也可以停止生成。剩余时间暂无法准确估算。"
        : "按实际生成阶段更新，耗时取决于模型响应。可以查看历史回合或角色状态。"}</p>
    </section>
  );
}
