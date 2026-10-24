"""Read-only, time-scoped world queries for the player's global-view assistant.

Curated facts live in the bound script's overrides.guide_world. Story moments are
ordered independently of reveal chapters: flashbacks are not future events.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

from . import catalog

MAX_QUERIES = 4
MAX_RESULT_CHARS = 6000
TOOL_HELP = {
    "get_current_time": "查存档当前时间、资料覆盖与分歧情况。",
    "get_timeline": "查已发生事件；本轮许可未来时可查原著后续。query可筛人名地名。",
    "get_character": "查人物当期身份、位置、性格、关系、说话方式和存亡。query为姓名、已知别称或对象key；重名看candidates。",
    "get_situation": "查地方、势力和天下局势。query可为空或为名称。",
    "get_history": "查真实历史对照，不能覆盖小说或本存档事实。",
    "get_evidence": "按fact_id查某条已允许资料的出处，不读取整本原文。",
}


class Record(BaseModel):
    model_config = {"extra": "forbid", "strict": True}


class Moment(Record):
    key: str = Field(min_length=1, max_length=100)
    order: int = Field(ge=0)
    label: str = Field(min_length=1, max_length=180)
    chapter_min: int | None = Field(default=None, ge=1)
    chapter_max: int | None = Field(default=None, ge=1)
    aliases: list[str] = Field(default_factory=list, max_length=20)


class Subject(Record):
    key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["character", "place", "faction", "world"]
    # Permanent spelling variants only. Acquired titles belong in dated facts.
    aliases: list[str] = Field(default_factory=list, max_length=30)


class Evidence(Record):
    source: str = Field(min_length=1, max_length=180)
    locator: str = Field(min_length=1, max_length=240)
    quote: str = Field(default="", max_length=240)
    url: str = Field(default="", max_length=500)
    chapter_index: int | None = Field(default=None, ge=1)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    chapter_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def line_interval(self):
        if ((self.line_start is None) != (self.line_end is None)
                or (self.line_start is not None and self.line_start > self.line_end)):
            raise ValueError("Invalid evidence line interval")
        return self


class Fact(Record):
    id: str = Field(min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=100)
    kind: Literal["state", "event", "history"]
    field: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=1200)
    starts_at: str
    ends_at: str | None = None  # Exclusive; omitted means no recorded end.
    basis: Literal["novel", "history"]
    certainty: Literal["confirmed", "reported", "inferred", "disputed"] = "confirmed"
    evidence: list[Evidence] = Field(min_length=1, max_length=4)


class GuideWorld(Record):
    version: Literal[1]
    edition: str = Field(min_length=1, max_length=100)
    moments: list[Moment] = Field(min_length=1, max_length=2000)
    subjects: list[Subject] = Field(max_length=5000)
    facts: list[Fact] = Field(max_length=50000)

    @model_validator(mode="after")
    def references(self):
        moments = {m.key: m for m in self.moments}
        subjects = {s.key for s in self.subjects}
        if (len(moments) != len(self.moments)
                or len({m.order for m in self.moments}) != len(self.moments)
                or len(subjects) != len(self.subjects)
                or len({f.id for f in self.facts}) != len(self.facts)):
            raise ValueError("World identifiers and moment orders must be unique")
        if any((m.chapter_min is None) != (m.chapter_max is None)
               or (m.chapter_min is not None and m.chapter_min > m.chapter_max)
               for m in self.moments):
            raise ValueError("Invalid chapter interval")
        for fact in self.facts:
            if fact.subject not in subjects or fact.starts_at not in moments:
                raise ValueError("Unknown fact subject or moment")
            if fact.ends_at is not None and (
                fact.ends_at not in moments
                or moments[fact.ends_at].order <= moments[fact.starts_at].order
            ):
                raise ValueError("Invalid fact validity interval")
            if fact.field in ("name", "alias") and (fact.kind != "state" or fact.basis != "novel"
                                          or fact.certainty != "confirmed"
                                          or not fact.value.strip() or len(fact.value) > 100):
                raise ValueError("Dated names and aliases must be confirmed short novel states")
        return self


class Query(Record):
    tool: Literal["get_current_time", "get_timeline", "get_character", "get_situation",
                  "get_history", "get_evidence"]
    query: str = Field(default="", max_length=100)
    fact_id: str = Field(default="", max_length=120)
    at: str = Field(default="", max_length=180)
    limit: int = Field(default=8, ge=1, le=12)


def knowledge_version(model):
    validated = GuideWorld.model_validate(model)
    return hashlib.sha256(validated.model_dump_json().encode()).hexdigest()


class WorldQueries:
    def __init__(self, model, state, *, script_id, save_id, allow_future=False, worldline=None):
        self.model = GuideWorld.model_validate(model)
        self.state = copy.deepcopy(state)
        self.script_id, self.save_id = script_id, save_id
        self.allow_future = allow_future is True
        self.moments = {m.key: m for m in self.model.moments}
        self.fact_orders = {f.id: self.moments[f.starts_at].order for f in self.model.facts}
        self.subjects = {s.key: s for s in self.model.subjects}
        self.worldline = copy.deepcopy(worldline or {})
        # Branch snapshots outrank session-wide estimates after a checkout.
        self.worldline.update(state.get("worldline") or {})
        timeline = (state.get("world") or {}).get("timeline") or {}
        chapter = timeline.get("anchor_chapter") or timeline.get("chapter_min")
        if type(chapter) is int and chapter >= 1:
            self.worldline["progress_chapter"] = chapter
        divergence = self.worldline.get("divergence_chapter")
        self.divergence_order = min((m.order for m in self.model.moments
                                     if type(divergence) is int and m.chapter_max is not None
                                     and m.chapter_max >= divergence), default=None)
        self.current = self._current_moment()
        self.name_facts = {}
        self.alias_facts = {}
        for fact in self.model.facts:
            if fact.field == "name":
                self.name_facts.setdefault(fact.subject, []).append(fact)
            elif fact.field == "alias":
                self.alias_facts.setdefault(fact.subject, []).append(fact)
        self.version = knowledge_version(self.model)
        self.recorded = {}
        from state.world_facts import WorldFact
        visible_subjects = {f.subject for f in self.model.facts if self._visible(f)}
        candidates = {}
        for subject in self.subjects.values():
            for name in (subject.key, *self.known_names(subject)):
                candidates.setdefault(name, {})[subject.key] = subject
        aliases = {}
        for name, choices in candidates.items():
            known = [s for s in choices.values() if s.key in visible_subjects]
            eligible = known or list(choices.values())
            aliases[name] = eligible[0] if len(eligible) == 1 else None
        for record in self.state.get("world_facts") or []:
            if (not isinstance(record, dict) or type(record.get("turn")) is not int
                    or record["turn"] > (self.state.get("turn") or 0)
                    or not isinstance(record.get("id"), str)):
                continue
            try:
                fact = WorldFact.model_validate({k: record[k] for k in WorldFact.model_fields if k in record})
            except ValueError:
                continue
            if fact.subject in aliases:
                subject = aliases[fact.subject]
                if subject is None:  # A name shared by several people is not a stable identity.
                    continue
            else:
                key = "save:" + hashlib.sha256(fact.subject.encode()).hexdigest()[:24]
                subject = Subject(key=key, name=fact.subject, kind=fact.subject_kind)
                self.subjects[key] = aliases[fact.subject] = subject
            self.recorded.setdefault(subject.key, []).append({**record, **fact.model_dump()})
            if fact.field == "name" and fact.certainty == "confirmed":
                aliases[fact.value] = subject if aliases.get(fact.value, subject) == subject else None

    def _recorded_names(self, subject, target):
        rows = []
        for record in getattr(self, "recorded", {}).get(subject.key, []):
            if record["field"] != "name" or record["certainty"] != "confirmed":
                continue
            if target is not self.current:
                moment = self._moment(record.get("moment") or record.get("time"))
                if target is None or moment is None or moment.order > target.order:
                    continue
            rows.append(record)
        return sorted(rows, key=lambda row: row["turn"])

    def known_names(self, subject):
        """Former names stay searchable once known; future names cannot identify a person."""
        facts = self.name_facts.get(subject.key, [])
        visible = [f for f in facts if self._visible(f)]
        names = [subject.name, *subject.aliases] if not facts or visible else []
        names += [f.value for f in visible]
        names += [f.value for f in self.alias_facts.get(subject.key, []) if self._visible(f)]
        names += [row["value"] for row in self._recorded_names(subject, self.current)]
        return list(dict.fromkeys(names))

    def display_name(self, subject, target):
        records = self._recorded_names(subject, target)
        if records:
            return records[-1]["value"]
        names = {f.value for f in self.name_facts.get(subject.key, []) if target is not None
                 and self.moments[f.starts_at].order <= target.order
                 and (f.ends_at is None or target.order < self.moments[f.ends_at].order)}
        # A sobriquet can be known before the primary name is revealed. Keep
        # that label until the dated name is known, without treating it as a rename.
        if not names and target is not None and self.name_facts.get(subject.key) and not any(
                self.moments[f.starts_at].order <= target.order for f in self.name_facts[subject.key]):
            aliases = [f for f in self.alias_facts.get(subject.key, [])
                       if self.moments[f.starts_at].order <= target.order]
            if aliases:
                return min(aliases, key=lambda f: self.moments[f.starts_at].order).value
        return next(iter(names)) if len(names) == 1 else subject.name

    def _moment(self, label):
        matches = [m for m in self.model.moments if label in (m.key, m.label, *m.aliases)]
        return matches[0] if len(matches) == 1 else None

    def _current_moment(self):
        world = self.state.get("world") or {}
        for label in (world.get("guide_moment"), world.get("time"),
                      (world.get("timeline") or {}).get("current_label")):
            if isinstance(label, str) and label and (moment := self._moment(label)):
                return moment
        progress = self.worldline.get("progress_chapter")
        if type(progress) is int and progress >= 1:
            matches = [m for m in self.model.moments
                       if m.chapter_min is not None and m.chapter_min <= progress <= m.chapter_max]
            # Several scenes can share a chapter. Never assume the latest scene.
            return min(matches, key=lambda m: m.order) if matches else None
        return None

    def clock(self):
        time = (self.state.get("world") or {}).get("time")
        progress = self.worldline.get("progress_chapter")
        divergence = self.worldline.get("divergence_chapter")
        return dict(
            time=time[:180] if isinstance(time, str) and time else "尚未记录",
            moment=self.current.label if self.current else None,
            moment_key=self.current.key if self.current else None,
            progress_chapter=progress if type(progress) is int else None,
            divergence_chapter=divergence if type(divergence) is int else None,
            divergence_turn=self.worldline.get("divergence_turn"),
            edition=self.model.edition, knowledge_version=self.version,
            future_allowed=self.allow_future,
            knowledge_scope="全局资料，不自动成为角色本人所知",
        )

    def _visible(self, fact):
        return self.allow_future or (
            self.current is not None
            and self.moments[fact.starts_at].order <= self.current.order
        )

    def _row(self, fact, target):
        subject = self.subjects[fact.subject]
        # A completed event before the split stays past fact; current states may have changed.
        at = self.moments[fact.starts_at] if fact.kind == "event" else target
        branched = (self.divergence_order is not None and at is not None
                    and at.order >= self.divergence_order)
        divergence_turn = self.worldline.get("divergence_turn")
        if self.divergence_order is None and type(divergence_turn) is int:
            branched = (target is self.current and divergence_turn <= (self.state.get("turn") or 0))
        return dict(
            id=fact.id, subject=self.display_name(subject, target), subject_key=subject.key, field=fact.field,
            value=fact.value, basis=fact.basis, certainty=fact.certainty,
            applicability=("historical_reference" if fact.basis == "history" else
                           "baseline_after_divergence" if branched else "baseline"),
            time=self.moments[fact.starts_at].label,
            future=bool(self.current and self.moments[fact.starts_at].order > self.current.order),
            evidence=[e.model_dump() for e in fact.evidence],
        )

    def _recorded_rows(self, subject=None, target=None):
        rows = []
        keys = [subject.key] if subject else self.recorded
        for key in keys:
            resolved = self.subjects[key]
            for record in self.recorded.get(key, []):
                if target is not self.current:
                    recorded = self._moment(record.get("moment") or record.get("time"))
                    if recorded is None or target is None or recorded.order > target.order:
                        continue
                rows.append(dict(
                    id=record["id"], subject=self.display_name(resolved, target), subject_key=resolved.key,
                    field=record["field"], value=record["value"], kind=record["kind"],
                    basis="save", certainty=record["certainty"], applicability="current_save",
                    future=False, turn=record["turn"], cause=record.get("cause", ""),
                    time=record.get("time") or "未记录准确发生时间",
                    evidence=[{"source": "本存档叙事", "locator": f"第{record['turn']}回合",
                               "quote": record["quote"]}],
                ))
        return rows

    def _live_rows(self, subject, target):
        """Only committed runtime facts, not pending ops, hypotheses or private prompts."""
        rows = [row for row in self._recorded_rows(subject, target) if row["kind"] == "state"]
        if target is not self.current:
            return sorted(rows, key=lambda r: r["turn"])
        turn = self.state.get("turn") or 0
        for item in (self.state.get("memory") or {}).get("items") or []:
            if (not isinstance(item, dict) or item.get("kind") != "runtime_fact"
                    or item.get("status") != "active"
                    or type(item.get("turn")) is not int or item["turn"] > turn):
                continue
            guide = item.get("guide")
            if (not isinstance(guide, dict) or guide.get("subject") != subject.key
                    or guide.get("kind") == "event"):
                continue
            field, value = guide.get("field"), guide.get("value")
            if not isinstance(field, str) or not isinstance(value, str) or not value.strip():
                continue
            rows.append(dict(id=f"save:{item.get('id', item['turn'])}:{field[:80]}",
                             subject=self.display_name(subject, target), subject_key=subject.key, field=field[:80],
                             value=value[:1200], basis="save", certainty="confirmed",
                             applicability="current_save", future=False, turn=item["turn"],
                             cause=str(guide.get("cause") or item.get("text") or "")[:600],
                             evidence=[{"source": "本存档", "locator": f"第{item['turn']}回合"}]))
        for entity in self.state.get("active_entities") or []:
            if not isinstance(entity, dict) or entity.get("name") not in self.known_names(subject):
                continue
            for key, field in (("role", "identity"), ("status", "status"), ("location", "location")):
                value = entity.get(key)
                # A last-seen location is not necessarily their current location.
                if key == "location" and entity.get("last_seen_turn") != turn:
                    continue
                if isinstance(value, str) and value.strip():
                    rows.append(dict(id=f"save:entity:{subject.key}:{field}", subject=self.display_name(subject, target),
                                     subject_key=subject.key, field=field, value=value[:1200],
                                     basis="save", certainty="reported", applicability="current_save",
                                     future=False, evidence=[{"source": "本存档人物记录",
                                                             "locator": "当前分支快照"}]))
        return sorted(rows, key=lambda r: (r.get("turn", turn), r["id"].startswith("wf_")))

    def _save_events(self):
        rows = []
        turn = self.state.get("turn") or 0
        events = (self.state.get("world") or {}).get("known_events") or []
        for index, event in enumerate(events):
            value = event if isinstance(event, str) else (
                event.get("text") or event.get("description") or event.get("name")
                if isinstance(event, dict) else None
            )
            if not isinstance(value, str) or not value.strip():
                continue
            rows.append(dict(id=f"save:event:{index}", subject="本存档事件", subject_key="",
                             field="event", value=value[:1200], basis="save", certainty="reported",
                             applicability="current_save", future=False, time="未记录准确发生时间",
                             evidence=[{"source": "本存档", "locator": "当前分支已知事件"}]))
        for item in (self.state.get("memory") or {}).get("items") or []:
            if (not isinstance(item, dict) or item.get("kind") != "runtime_fact"
                    or item.get("status") != "active" or type(item.get("turn")) is not int
                    or item["turn"] > turn):
                continue
            guide = item.get("guide")
            if not isinstance(guide, dict) or guide.get("kind") != "event":
                continue
            subject = self.subjects.get(guide.get("subject"))
            value = guide.get("value")
            if subject is None or not isinstance(value, str) or not value.strip():
                continue
            rows.append(dict(id=f"save:memory:{item.get('id', item['turn'])}", subject=self.display_name(subject, self.current),
                             subject_key=subject.key, field="event", value=value[:1200], basis="save",
                             certainty="confirmed", applicability="current_save", future=False,
                             turn=item["turn"], time=f"存档第{item['turn']}回合",
                             cause=str(guide.get("cause") or item.get("text") or "")[:600],
                             evidence=[{"source": "本存档", "locator": f"第{item['turn']}回合"}]))
        rows.extend(row for row in self._recorded_rows(target=self.current) if row["kind"] == "event")
        return sorted(rows, key=lambda r: r.get("turn", 0))

    def query(self, request):
        args = Query.model_validate(request)  # No model-controlled script, save, or future switch.
        result = {"tool": args.tool, "as_of": self.clock(), "facts": []}
        if args.tool == "get_current_time":
            return result
        target = self._moment(args.at) if args.at else self.current
        if args.at and target is None:
            return {**result, "unavailable": "资料中没有这个确定时点"}
        if target is not None and (self.current is None or target.order > self.current.order):
            if not self.allow_future:
                return {**result, "unavailable": "未来资料需要本轮明确许可"}
        if target is None and not self.allow_future:
            result["notice"] = "无法确定当前时点，仅查询已记录的存档事实"
        if args.tool == "get_evidence":
            facts = [f for f in self.model.facts if f.id == args.fact_id and self._visible(f)]
        else:
            matches = {s.key for s in self.subjects.values()
                       if args.query in (s.key, *self.known_names(s))}
            if args.tool == "get_character":
                matches = {k for k in matches if self.subjects[k].kind == "character"}
                if len(matches) > 1:
                    known = {f.subject for f in self.model.facts if self._visible(f)} | self.recorded.keys()
                    matches = {k for k in matches if k in known}
                if len(matches) != 1:
                    return {**result, "unavailable": "未找到唯一人物，请使用姓名或对象key消除重名",
                            "candidates": [dict(key=k, name=self.display_name(self.subjects[k], target))
                                           for k in sorted(matches)]}
            facts = [f for f in self.model.facts if self._visible(f)]
            if args.tool in ("get_character", "get_situation"):
                facts = [f for f in facts if f.kind == "state"
                         and (not args.query or f.subject in matches)
                         and (args.tool == "get_character"
                              or self.subjects[f.subject].kind != "character")
                         and target is not None
                         and self.moments[f.starts_at].order <= target.order
                         and (f.ends_at is None or target.order < self.moments[f.ends_at].order)]
            else:
                facts = [f for f in facts if (
                    f.kind == "event" if args.tool == "get_timeline" else f.basis == "history"
                ) and (
                    not args.query or f.subject in matches
                    or args.query in f.value or args.query in self.subjects[f.subject].name
                ) and (not args.at or self.moments[f.starts_at].order <= target.order)]
        facts.sort(key=lambda f: self.moments[f.starts_at].order)
        rows = [self._row(f, target) for f in facts]
        if args.tool == "get_evidence":
            rows.extend(row for row in self._recorded_rows(target=target) if row["id"] == args.fact_id)
        if args.tool in ("get_character", "get_situation"):
            # Prefer novel over history per subject/field; report same-rank conflicts.
            slots = {}
            for row in rows:
                key = (row["subject_key"], row["field"])
                slot = slots.setdefault(key, [])
                if slot and slot[0]["basis"] == "novel" and row["basis"] == "history":
                    continue
                if slot and slot[0]["basis"] == "history" and row["basis"] == "novel":
                    slot.clear()
                slot.append(row)
            if target is self.current or (target and self.current and target.order < self.current.order):
                for subject in self.subjects.values():
                    if (args.query and subject.key not in matches) or (
                        args.tool == "get_situation" and subject.kind == "character"
                    ):
                        continue
                    for row in self._live_rows(subject, target):
                        key = (row["subject_key"], row["field"])
                        # Explicit structured runtime facts outrank a lightweight entity record.
                        if row["certainty"] == "reported" and any(
                            r["basis"] == "save" and r["certainty"] == "confirmed"
                            for r in slots.get(key, [])
                        ):
                            continue
                        slots[key] = [row]
            for slot in slots.values():
                if len({row["value"] for row in slot}) > 1:
                    for row in slot:
                        row["conflict"] = True
            rows = [row for slot in slots.values() for row in slot]
            fields = ["status", "identity", "location", "situation", "personality", "motivation", "speech_style"]
            # Within equally important fields, keep recent changes inside the result cap.
            rows.sort(key=lambda r: (r["basis"] != "save",
                                    fields.index(r["field"]) if r["field"] in fields else len(fields),
                                    -self.fact_orders.get(r["id"], 0)))
        elif args.tool == "get_timeline" and target is self.current:
            # Undated save events remain undated; never backfill them into a past query.
            rows.extend(row for row in self._save_events() if not args.query
                        or row["subject_key"] in matches or args.query in row["value"])
        elif args.tool == "get_timeline" and target:
            rows.extend(row for row in self._recorded_rows(target=target)
                        if row["kind"] == "event" and (not args.query
                        or row["subject_key"] in matches or args.query in row["value"]))
        total = len(rows)
        if args.tool in ("get_timeline", "get_history"):
            rows = rows[-args.limit:]
        result["facts"] = rows[:args.limit]
        result["truncated"] = total > args.limit
        while result["facts"] and len(json.dumps(result, ensure_ascii=False)) > MAX_RESULT_CHARS:
            result["facts"].pop()
            result["truncated"] = True
        return result


def bind_initial(model, snapshot, *, default_opening=False):
    """Bind a newly created save before its root commit and KB seed are written."""
    try:
        world = WorldQueries(model, snapshot, script_id=0, save_id=0)
    except ValueError as exc:
        raise HTTPException(503, "故事的世界资料尚未配置完整") from exc
    moment = world.current
    if moment is None and default_opening:
        chapter_moments = [m for m in world.model.moments if m.chapter_min is not None]
        moment = min(chapter_moments, key=lambda m: (m.chapter_min, m.order), default=None)
    target = snapshot.setdefault("world", {})
    target["guide_edition"] = world.model.edition
    if moment is not None:
        target["guide_moment"] = moment.key
        if not target.get("time"):
            target["time"] = moment.label
            target.setdefault("timeline", {})["current_label"] = moment.label
        progress = snapshot.setdefault("worldline", {})
        if moment.chapter_min is not None and not progress.get("progress_chapter"):
            progress["progress_chapter"] = moment.chapter_min


def load(uid, sid, *, allow_future=False):
    """Scope every query to an owned player save and its bound script, loaded once."""
    from platform_app.db import connect

    save = catalog.player_save(uid, sid)
    with connect() as db:
        row = db.execute("select data from script_overrides where script_id=%s",
                         (save["script_id"],)).fetchone()
        session = db.execute("select worldline from game_sessions where save_id=%s",
                             (sid,)).fetchone()
    overrides = (row or {}).get("data") or {}
    if not isinstance(overrides, dict):
        raise HTTPException(503, "故事的世界资料尚未配置完整")
    model = overrides.get("guide_world")
    if model is None:
        return None
    if not isinstance(model, dict):
        raise HTTPException(503, "故事的世界资料尚未配置完整")
    state = save.get("state_snapshot") or {}
    edition = (state.get("world") or {}).get("guide_edition")
    if edition and edition != model.get("edition"):
        raise HTTPException(409, "存档引用的世界资料版本不可用")
    try:
        return WorldQueries(model, state, script_id=save["script_id"], save_id=sid,
                            allow_future=allow_future, worldline=(session or {}).get("worldline"))
    except ValueError as exc:
        raise HTTPException(503, "故事的世界资料尚未配置完整") from exc
