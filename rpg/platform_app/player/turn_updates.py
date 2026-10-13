"""Known task and milestone DTOs plus a compact recorder state packet."""

import json

from .experience import attributes, status, text, values

TASK_LABELS = {"active": "进行中", "completed": "已完成", "failed": "失败", "paused": "暂缓"}


def tasks(data):
    memory = data.get("memory") or {}
    result = []
    for item in values(memory.get("tasks") or []):
        if (
            not isinstance(item, dict)
            or not item.get("name")
            or item.get("status") not in TASK_LABELS
        ):
            continue
        result.append(
            {
                "name": str(item["name"])[:120],
                "status": item["status"],
                "description": str(item.get("description") or "")[:600],
                "progress": str(item.get("progress") or "")[:300],
            }
        )
    # A long-running named task must not hide the latest committed objective.
    # Project the goal separately instead of guessing which task it advances.
    if text(memory.get("current_objective")):
        result = [task for task in result if task["name"] != "当前目标"]
        result.append(
            {
                "name": "当前目标",
                "status": "active",
                "description": text(memory["current_objective"]),
                "progress": "",
            }
        )
    return result[-40:]


def milestones(data):
    stored = (data.get("memory") or {}).get("milestones") or []
    # Older scalar writes may have left one typed node instead of a list.
    items = [stored] if isinstance(stored, dict) and stored.get("name") else values(stored)
    return [
        {"name": str(item["name"])[:120], "description": str(item.get("description") or "")[:600]}
        for item in items
        if isinstance(item, dict) and item.get("name") and item.get("status") == "completed"
    ][-30:]


def recording_packet(data):
    known = status(data)
    return json.dumps(
        {
            "character": attributes(data),
            "role": (data.get("player") or {}).get("role", ""),
            "location": known["location"],
            "time": known["time"],
            "abilities": known["abilities"],
            "resources": known["resources"],
            "inventory": known["inventory"],
            "people": known["people"],
            "tasks": tasks(data),
            "milestones": milestones(data),
        },
        ensure_ascii=False,
        default=str,
    )[:12000]


def task_changes(before, after):
    previous = {t["name"]: t for t in tasks(before)}
    changes = []
    for task in tasks(after):
        if task["name"] == "当前目标" and task["description"] == text(
            (after.get("memory") or {}).get("current_objective")
        ):
            continue  # Already emitted once as the committed objective change.
        old = previous.get(task["name"])
        if old != task:
            changes.append(
                {
                    "kind": "任务",
                    "before": f"{old['name']} · {TASK_LABELS[old['status']]} · {old['progress'] or old['description']}"
                    if old
                    else "",
                    "after": f"{task['name']} · {TASK_LABELS[task['status']]} · {task['progress'] or task['description']}",
                }
            )
    return changes


def panels(progress):
    result = set()
    for gain in [*progress["gains"], *progress["losses"]]:
        result.add("角色" if gain["kind"] in {"属性", "能力"} else "背包")
    for change in progress["changes"]:
        kind = change["kind"]
        if kind == "目标":
            result.add("任务")
        result.add(
            "任务"
            if kind == "任务"
            else "人物"
            if kind == "人物关系"
            else "角色"
            if kind in {"身份", "武魂", "魂力", "先天魂力", "魂师境界", "魂环", "伤势"}
            else "世界线"
            if kind in {"世界线", "关键节点"}
            else "局势"
        )
    if progress["events"]:
        result.add("局势")
    return [
        label for label in ["局势", "角色", "背包", "人物", "任务", "世界线"] if label in result
    ]
