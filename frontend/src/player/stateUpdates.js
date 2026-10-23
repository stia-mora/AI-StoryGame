import { description } from "./shared.jsx";

export function stateUpdates(view) {
  const result = Object.fromEntries(["overview", "character", "inventory", "people", "tasks", "worldline"].map((id) => [id, []]));
  const rounds = new Map((view.journey || []).map((step) => [step.message_id, { ...step, progress: step }]));
  for (const message of view.messages || []) {
    if (message.role === "assistant" && message.progress) rounds.set(message.id, { ...message, message_id: message.id });
  }
  const latest = (view.messages || []).filter((message) => message.role === "assistant").at(-1);
  if (view.latest_progress) {
    const id = latest?.id || `turn-${view.save.turn}`;
    rounds.set(id, { turn: latest?.turn ?? view.save.turn, message_id: id, progress: view.latest_progress });
  }
  const attributes = new Set((view.status.attributes || []).map((item) => item.name));
  for (const round of rounds.values()) {
    const entries = Object.fromEntries(Object.keys(result).map((id) => [id, []]));
    const progress = round.progress;
    for (const [items, verb] of [[progress.gains, "获得"], [progress.losses, "消耗 / 失去"]]) {
      for (const item of items || []) {
        const entry = { label: `${verb} · ${item.kind}`, after: description(item.text) };
        if (["属性", "能力"].includes(item.kind)) entries.character.push(entry);
        else {
          entries.inventory.push(entry);
          if (item.kind === "资源") entries.character.push(entry);
        }
      }
    }
    for (const change of progress.changes || []) {
      const id = change.kind === "任务" ? "tasks" : change.kind === "人物关系" ? "people"
        : ["世界线", "关键节点"].includes(change.kind) ? "worldline"
          : ["身份", "武魂", "魂力", "先天魂力", "魂师境界", "魂环", "伤势"].includes(change.kind) || attributes.has(change.kind) ? "character" : "overview";
      const entry = { label: change.kind, before: description(change.before), after: description(change.after) };
      entries[id].push(entry);
      if (change.kind === "目标") entries.tasks.push(entry);
    }
    for (const event of progress.events || []) entries.overview.push({ label: "已知事件", after: description(event) });
    for (const id of Object.keys(result)) {
      if (entries[id].length) result[id].push({ id: round.message_id, order: parseInt(round.message_id) || Number(round.turn) + 1, turn: round.turn, entries: entries[id] });
    }
  }
  for (const groups of Object.values(result)) groups.sort((a, b) => b.order - a.order);
  return result;
}
