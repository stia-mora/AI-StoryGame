"""Player-visible choices and changes derived from committed state, never future canon."""

from __future__ import annotations

import re

PLAYER_GUIDE = """
【玩家入口交互规则，优先于通用选择频率】
每次开场或回合回复都必须提供恰好四个不同的、符合当前现场的下一步行动。
使用 question op 的 options 数组或正文末尾四项编号列表。选项是建议，不替玩家行动。
四项分别体现推进、探索、交流或成长、谨慎或不同策略；用具体人物、地点和动作，避免空泛。
从开场后的第一次选择就执行：每项点明正文已公开的人物或地点、要做的事和眼下可知的条件或代价，让玩家点击前能判断路线差异。
禁止用「推进主线」「探索周围」「与人交流」「稳妥准备」这类通用话术替代现场行动；不把后续才能知道的结果当作承诺。
每个建议授权一段有结果的完整行动，合并日常手续与安全行程，停在下一关键抉择；不要把伸手、排队、问一条细节、走到门口拆成付费回合。
出现可争夺的已知机缘时，明确提供争取与放弃/让给他人的选择，并说明眼下可知的代价。
不得把原著未来情报、隐藏身份或未接触的机缘写进选项。玩家仍能自由输入其他行动。
本轮真正发生的地点、目标、关系、资源和能力变化须通过现有状态工具或 JSON ops 写回。
仅提及、预测或尝试不等于获得；不授予未经剧情确认的物品或能力。
"""


class PlayerTextGuard:
    """Hold bare JSON across chunks until state operations can be safely stripped."""

    def __init__(self):
        self.pending = ""
        self.stack = []
        self.quoted = False
        self.escaped = False

    @staticmethod
    def visible(text):
        from state import strip_json_state_ops

        return strip_json_state_ops(text)

    def feed(self, chunk):
        out = []
        for char in chunk:
            if not self.pending:
                if char in "{[":
                    self.pending = char
                    self.stack = [char]
                else:
                    out.append(char)
                continue
            self.pending += char
            if self.quoted:
                if self.escaped:
                    self.escaped = False
                elif char == "\\":
                    self.escaped = True
                elif char == '"':
                    self.quoted = False
            elif char == '"':
                self.quoted = True
            elif char in "{[":
                self.stack.append(char)
            elif char in "}]":
                self.stack.pop()
                if not self.stack:
                    out.append(self.visible(self.pending))
                    self.pending = ""
        return "".join(out)

    def flush(self):
        result = self.visible(self.pending) if self.pending else ""
        self.pending = ""
        self.stack = []
        self.quoted = self.escaped = False
        return result


def text(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        name = value.get("name") or value.get("label") or value.get("text") or ""
        detail = (
            value.get("description")
            or value.get("relationship")
            or value.get("status")
            or value.get("value")
            or ""
        )
        return " · ".join(str(v) for v in (name, detail) if v not in ("", None))
    return ""


def values(items):
    if isinstance(items, dict):
        return [
            {"name": k, **v} if isinstance(v, dict) else {"name": k, "value": v}
            for k, v in items.items()
        ]
    return items if isinstance(items, list) else [items] if items else []


def status(data):
    player = data.get("player") or {}
    pc = data.get("player_character") or {}
    memory = data.get("memory") or {}
    world = data.get("world") or {}
    return dict(
        location=player.get("current_location")
        or world.get("location")
        or data.get("location")
        or "",
        time=world.get("time") or "",
        objective=memory.get("current_objective") or memory.get("main_quest") or "",
        inventory=values(pc.get("inventory") or player.get("inventory") or []),
        abilities=values(
            player.get("abilities")
            or memory.get("abilities")
            or pc.get("features")
            or player.get("skills")
            or []
        ),
        resources=values(player.get("resources") or memory.get("resources") or []),
        people=values(
            data.get("relationships")
            or player.get("relationships")
            or memory.get("relationships")
            or []
        ),
    )


def attributes(data):
    """Display known character stats only; never pass arbitrary private memory keys."""
    pc = data.get("player_character") or {}
    player = data.get("player") or {}
    labels = {
        "level": "等级",
        "hp": "生命",
        "max_hp": "生命上限",
        "ac": "防御",
        "soul_power": "魂力",
        "innate_soul_power": "先天魂力",
        "martial_soul": "武魂",
        "soul_rank": "魂师境界",
        "soul_rings": "魂环",
        "injury": "伤势",
        "strength": "力量",
        "dexterity": "敏捷",
        "constitution": "体质",
        "intelligence": "智力",
        "wisdom": "感知",
        "charisma": "魅力",
    }
    initialized = pc.get("name") or pc.get("class_name") or int(pc.get("level") or 0) > 0
    sources = [player] + ([pc, pc.get("ability_scores") or {}] if initialized else [])
    result = []
    for key, label in labels.items():
        value = next(
            (s[key] for s in sources if isinstance(s, dict) and key in s and s[key] is not None),
            None,
        )
        if isinstance(value, list):
            value = "、".join(text(item) for item in value if text(item))
        if isinstance(value, (str, int, float)) and value != "":
            result.append({"name": label, "value": value})
    return result


def narration_choices(narration):
    """Read a final four-action list, rather than reusing an earlier round's buttons."""
    numbered = list(
        re.finditer(r"(?m)^\s*(?:[-*]\s+)?(?:\*\*)?([1-4A-D])[.、)）:：]\s*(.+)$", narration)
    )
    if len(numbered) < 4:
        return []
    final = numbered[-4:]
    labels = [m.group(1) for m in final]
    if labels not in (["1", "2", "3", "4"], ["A", "B", "C", "D"]):
        return []
    # Treat only a short closing list as actions; an enumerated passage in the story is prose.
    if len(narration[final[-1].end() :].strip()) > 160:
        return []
    result = [re.sub(r"[*_`]+", "", m.group(2)).strip()[:240] for m in final]
    return result if len(set(result)) == 4 and all(result) else []


def choices(data, existing=None, narration=""):
    turn = int(data.get("turn") or 0)
    questions = [
        q
        for q in (data.get("permissions") or {}).get("pending_questions") or []
        if int(q.get("turn", turn)) >= turn
    ]
    stored = data.get("structured_options") or []
    if int(data.get("options_turn", 0)) != turn:
        stored = []
    raw = narration_choices(narration) or (
        existing
        if existing is not None
        else (questions[-1].get("options") if questions else []) or stored or []
    )
    result = []
    for item in raw:
        action = text(item)
        if action and action not in result:
            result.append(action[:240])
    current = status(data)
    place = text(current["location"])
    known = next((text(item).split(" · ")[0] for item in current["people"] if text(item)), "")
    objective = text(current["objective"])
    # Missing model options must not turn into four interchangeable template buttons.
    # Offer only actions grounded in facts we can name; free input remains available.
    fallback = []
    if objective:
        where = f"在{place}，" if place else ""
        fallback.append(f"{where}着手「{objective[:100]}」，完成可行的普通步骤，遇到重大代价先停下决定")
    if place:
        fallback.append(f"留在{place}查证可见线索，弄清这里的情况后再决定去向")
    if known:
        subject = f"「{objective[:80]}」的可行路线与条件" if objective else f"{place or '当前局势'}的情况"
        fallback.append(f"向{known}询问{subject}，听取答复后再决定")
    resource = next((text(item) for item in current["resources"] + current["inventory"] if text(item)), "")
    if resource:
        fallback.append(f"检查随身的「{resource[:80]}」，确认状况和用途，再安排下一步")
    ability = next((text(item) for item in current["abilities"] if text(item)), "")
    if ability and place:
        fallback.append(f"在{place}安全练习已掌握的「{ability[:80]}」，确认运用情况后再行动")
    for item in fallback:
        if len(result) >= 4:
            break
        if item not in result:
            result.append(item)
    return result[:4]


def ensure_choices(data, narration="", question_turn=None):
    # The legacy pipeline increments turn on persistence, after applying question ops.
    # Normalize newly created questions to that committed turn; the API already removed
    # the previous round's GM suggestions before starting this action.
    current_turn = int(data.get("turn") or 0)
    if question_turn is not None:
        for question in (data.get("permissions") or {}).get("pending_questions") or []:
            if int(question.get("turn", current_turn)) >= question_turn:
                question["turn"] = current_turn
    data["structured_options"] = choices(data, narration=narration)
    data["options_turn"] = int(data.get("turn") or 0)
    return data["structured_options"]


def collection_changes(before, after, label):
    def indexed(items):
        result = {}
        for item in items:
            key = (
                (item.get("name") or item.get("id") or item.get("label") or item.get("text"))
                if isinstance(item, dict)
                else text(item)
            )
            if key:
                result[str(key)] = item
        return result

    old = indexed(before)
    new = indexed(after)
    gains = []
    losses = []
    for key, item in new.items():
        if key not in old:
            gains.append({"kind": label, "text": text(item)})
        elif isinstance(item, dict) and isinstance(old[key], dict):
            amount = item.get("quantity", item.get("count", item.get("value")))
            previous = old[key].get("quantity", old[key].get("count", old[key].get("value")))
            if (
                isinstance(amount, (int, float))
                and isinstance(previous, (int, float))
                and amount != previous
            ):
                target = gains if amount > previous else losses
                target.append(
                    {
                        "kind": label,
                        "text": f"{key} {'+' if amount > previous else ''}{amount - previous:g}",
                    }
                )
            elif item != old[key]:
                gains.append({"kind": label, "text": text(item)})
    for key, item in old.items():
        if key not in new:
            losses.append({"kind": label, "text": text(item)})
    return gains, losses


def progress(before, after, narration, action=""):
    from .turn_updates import milestones as known_milestones
    from .turn_updates import panels, task_changes

    old = status(before)
    new = status(after)
    gains = []
    losses = []
    changes = []
    changes.extend(task_changes(before, after))
    old_role = (before.get("player") or {}).get("role")
    new_role = (after.get("player") or {}).get("role")
    if new_role and old_role != new_role:
        changes.append({"kind": "身份", "before": old_role or "", "after": new_role})
    previous_milestones = {item["name"] for item in known_milestones(before)}
    for item in known_milestones(after):
        if item["name"] not in previous_milestones:
            changes.append({"kind": "关键节点", "before": "", "after": text(item)})
    old_attributes = {item["name"]: item["value"] for item in attributes(before)}
    for item in attributes(after):
        if item["name"] not in old_attributes:
            gains.append({"kind": "属性", "text": f"{item['name']}：{item['value']}"})
        elif old_attributes[item["name"]] != item["value"]:
            changes.append(
                {
                    "kind": item["name"],
                    "before": str(old_attributes[item["name"]]),
                    "after": str(item["value"]),
                }
            )
    for key, label in [("inventory", "物品"), ("abilities", "能力"), ("resources", "资源")]:
        got, used = collection_changes(old[key], new[key], label)
        gains += got
        losses += used
    for key, label in [("location", "地点"), ("time", "时间"), ("objective", "目标")]:
        if text(new[key]) and new[key] != old[key]:
            changes.append({"kind": label, "before": text(old[key]), "after": text(new[key])})
    relation_gains, _ = collection_changes(old["people"], new["people"], "人物关系")
    for item in relation_gains:
        changes.append({"kind": "人物关系", "before": "", "after": item["text"]})
    old_wl = before.get("worldline") or {}
    new_wl = after.get("worldline") or {}
    if new_wl.get("divergence_chapter") is not None and new_wl.get(
        "divergence_chapter"
    ) != old_wl.get("divergence_chapter"):
        changes.append({"kind": "世界线", "before": "", "after": "你的行动已形成新的剧情分支"})
    projection = new_wl.get("last_projection") or {}
    if (
        projection != old_wl.get("last_projection")
        and projection.get("validated")
        and projection.get("text")
    ):
        changes.append({"kind": "局势推演", "before": "", "after": str(projection["text"])[:360]})
    previous_events = {text(i) for i in (before.get("world") or {}).get("known_events") or []}
    events = [
        text(i)
        for i in (after.get("world") or {}).get("known_events") or []
        if text(i) and text(i) not in previous_events
    ]
    visible = re.sub(r"[#*_`]+", "", narration).strip()
    sentences = re.split(r"(?<=[。！？])\s*", visible.replace("\n", " "))
    summary = "".join(sentences[:2])[:180]
    milestones = (
        [f"{c['kind']}：{c['after']}" for c in changes if c["kind"] != "时间"]
        + [f"获得：{g['text']}" for g in gains]
        + [f"消耗：{g['text']}" for g in losses]
    )
    if milestones:
        summary = "；".join(milestones)[:180]
    result = dict(
        summary=summary,
        action=action[:240],
        events=events[-4:],
        gains=gains[:12],
        losses=losses[:8],
        changes=changes[:12],
    )
    result["panels"] = panels(result)
    return result


def snapshot_sql(column):
    """Column is an internal SQL identifier, not user input. Select only display state."""
    stats = ",".join(f"'{key}',{column}->'player'->'{key}'" for key in (
        "level", "hp", "max_hp", "ac", "strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"))
    return f"""jsonb_build_object(
      'location',{column}->'location',
      'player',jsonb_build_object('name',{column}->'player'->'name','current_location',{column}->'player'->'current_location','role',{column}->'player'->'role','inventory',{column}->'player'->'inventory','abilities',{column}->'player'->'abilities','skills',{column}->'player'->'skills','resources',{column}->'player'->'resources','relationships',{column}->'player'->'relationships','martial_soul',{column}->'player'->'martial_soul','soul_power',{column}->'player'->'soul_power','innate_soul_power',{column}->'player'->'innate_soul_power','soul_rank',{column}->'player'->'soul_rank','soul_rings',{column}->'player'->'soul_rings','injury',{column}->'player'->'injury',{stats}),
      'player_character',jsonb_build_object('name',{column}->'player_character'->'name','class',{column}->'player_character'->'class','class_name',{column}->'player_character'->'class_name','level',{column}->'player_character'->'level','hp',{column}->'player_character'->'hp','max_hp',{column}->'player_character'->'max_hp','ac',{column}->'player_character'->'ac','ability_scores',{column}->'player_character'->'ability_scores','inventory',{column}->'player_character'->'inventory','features',{column}->'player_character'->'features'),
      'world',jsonb_build_object('time',{column}->'world'->'time','location',{column}->'world'->'location','known_events',{column}->'world'->'known_events'),
      'memory',jsonb_build_object('current_objective',{column}->'memory'->'current_objective','main_quest',{column}->'memory'->'main_quest','abilities',{column}->'memory'->'abilities','resources',{column}->'memory'->'resources','relationships',{column}->'memory'->'relationships','tasks',{column}->'memory'->'tasks','milestones',{column}->'memory'->'milestones'),
      'relationships',{column}->'relationships',
      'worldline',jsonb_build_object('divergence_chapter',{column}->'worldline'->'divergence_chapter','last_projection',{column}->'worldline'->'last_projection'))"""
