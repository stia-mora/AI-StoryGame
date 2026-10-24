"""Narration-backed world changes, retained in branch snapshots independently of memory pruning."""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_PER_TURN = 12
OP_PROPERTIES = {
    "subject": {"type": "string", "description": "本段叙事原句中出现的人物、地点或势力名"},
    "subject_kind": {"type": "string", "enum": ["character", "place", "faction", "world"]},
    "field": {"type": "string", "description": "状态字段，如status/location/identity/proposal；事件用event"},
    "value": {"type": "string", "description": "正文已确认的变化；报告不得冒充已证实状态"},
    "cause": {"type": "string", "description": "正文明确给出的行动或变化原因；没有则留空"},
    "kind": {"type": "string", "enum": ["state", "event"]},
    "certainty": {"type": "string", "enum": ["confirmed", "reported"]},
    "quote": {"type": "string", "description": "从本轮GM正文逐字摘录含主体名的短证据，不能摘自ops或参考资料"},
    "diverges": {"type": "boolean", "description": "正文已明确造成原著分歧时为true；猜测或普通变化为false"},
}
RECORDING_GUIDE = """【世界事实记录，仅用于已配置全局资料的故事】
正文明确发生人物存亡、伤势、迁职、位置、地方控制或军政变化时，可另输出world_fact op。
形态：{"op":"world_fact","subject":"正文中的姓名","subject_kind":"character","field":"status","value":"实际状态",
"cause":"已叙述的原因","kind":"state","certainty":"confirmed","quote":"正文逐字短证据","diverges":false}。
事件用kind=event、field=event；同一件事的状态和事件可各一条。每回合至多12条，合并细碎记录。
subject必须出现在quote中，quote须逐字来自本轮GM叙事，不能取自候选计划、原著参考或JSON本身。
仅有消息或传闻时用certainty=reported、field=report；拟议任官、军改等用field=proposal，不能更新成实际官职。
人物明确改名时另记field=name，subject用已知旧名、value只写不超过100字符的新名；传闻不能作确证改名。
愿望、玩家尚未成功的行动、推测和未来基线不登记为既成事实。diverges仅在明确改史时为true。
不要输出turn、时间、存档、剧本或用户标识，这些由服务器从当前分支记录。
"""


class WorldFact(BaseModel):
    model_config = {"extra": "forbid", "strict": True}
    subject: str = Field(min_length=1, max_length=100)
    subject_kind: Literal["character", "place", "faction", "world"] = "character"
    field: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    value: str = Field(min_length=1, max_length=1200)
    cause: str = Field(default="", max_length=600)
    kind: Literal["state", "event"] = "state"
    certainty: Literal["confirmed", "reported"] = "confirmed"
    quote: str = Field(min_length=1, max_length=240)
    diverges: bool = False

    @field_validator("subject", "value", "quote")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("World fact text cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def semantics(self):
        if self.field == "name" and (self.certainty != "confirmed" or len(self.value) > 100):
            raise ValueError("Names must be confirmed and at most 100 characters")
        if self.kind == "event" and self.field != "event":
            raise ValueError("World events must use field=event")
        if self.certainty == "reported" and self.field != "report":
            raise ValueError("Reports cannot replace confirmed world state")
        if self.kind == "state" and self.field == "event":
            raise ValueError("Event fields must use kind=event")
        if self.diverges and (self.certainty != "confirmed" or self.field in ("report", "proposal")):
            raise ValueError("Reports and proposals cannot confirm a divergence")
        return self


def provenance(data):
    world = data.get("world") or {}
    timeline = world.get("timeline") or {}
    progress = timeline.get("anchor_chapter") or timeline.get("chapter_min") or (
        data.get("worldline") or {}).get("progress_chapter")
    return dict(turn=int(data.get("turn") or 0),
                time=str(world.get("time") or "")[:180],
                moment=str(world.get("guide_moment") or "")[:100],
                chapter=progress if type(progress) is int and progress > 0 else None)


def validate(payload, narrative):
    fact = WorldFact.model_validate(payload)
    if fact.quote not in narrative or fact.subject not in fact.quote:
        raise ValueError("World fact requires a narration quote containing its subject")
    return fact.model_dump()


def append(data, payload, *, recorded):
    """Trusted caller has checked the original narration, including before delayed approval."""
    fact = WorldFact.model_validate(payload).model_dump()
    log = data.setdefault("world_facts", [])
    row = {**fact, **recorded}
    digest = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
    row["id"] = f"wf_{digest}"
    if any(item.get("id") == row["id"] for item in log):
        return "世界事实已含此条"
    if sum(item.get("turn") == row["turn"] for item in log) >= MAX_PER_TURN:
        return "世界事实拒绝：本回合最多12条，请合并细碎变化"
    log.append(row)
    if row["diverges"]:
        worldline = data.setdefault("worldline", {})
        previous = worldline.get("divergence_turn")
        if type(previous) is not int or row["turn"] < previous:
            worldline["divergence_turn"] = row["turn"]
        chapter = row["chapter"]
        previous_chapter = worldline.get("divergence_chapter")
        if chapter is not None and (type(previous_chapter) is not int or chapter < previous_chapter):
            worldline["divergence_chapter"] = chapter
    return f"状态写入：世界事实 {row['subject']} · {row['field']}"


def record(state, payload, *, narrative):
    if not (state.data.get("world") or {}).get("guide_edition"):
        raise ValueError("World facts require an enabled story edition")
    fact = validate(payload, narrative)
    recorded = provenance(state.data)
    if state._gm_narrative_needs_pending():
        return state.add_pending_narrative_op(
            "world_fact", {"fact": fact, "recorded": recorded}, source="gm:json",
            display=f"世界事实：{fact['subject']} · {fact['field']}",
        )
    return append(state.data, fact, recorded=recorded)


def context(data, query="", *, max_chars=4000):
    """GM director context: current changes, not automatic character knowledge."""
    latest, events = {}, []
    turn = data.get("turn") or 0
    for row in data.get("world_facts") or []:
        if not isinstance(row, dict) or type(row.get("turn")) is not int or row["turn"] > turn:
            continue
        try:
            fact = WorldFact.model_validate({k: row[k] for k in WorldFact.model_fields if k in row})
        except ValueError:
            continue
        if fact.kind == "state":
            key = (fact.subject, fact.field)
            if key not in latest or row["turn"] >= latest[key]["turn"]:
                latest[key] = row
        else:
            events.append(row)
    rows = sorted(latest.values(), key=lambda r: (r["subject"] in query, r["turn"]), reverse=True)
    rows += sorted(events, key=lambda r: r["turn"], reverse=True)[:4]
    if not rows:
        return ""
    lines = ["本分支叙事记录优先于原著基线；以下全局资料不自动成为角色本人所知。报告与拟议按标记使用。"]
    used = len(lines[0])
    for row in rows:
        line = f"- {row['subject']} · {row['field']}（{row['certainty']}，第{row['turn']}回合）：{row['value']}"
        if row.get("cause"):
            line += f"；缘由：{row['cause']}"
        if used + len(line) + 1 > max_chars:
            continue
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)
