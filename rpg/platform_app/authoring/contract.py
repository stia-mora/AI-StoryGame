"""Versioned authoring contract and bounded, database-free package validation."""
from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
import zlib
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from platform_app.player.guide_world import GuideWorld

SCOPES = ["authoring:read", "authoring:write", "authoring:preview", "authoring:submit"]
CHUNK_BYTES = 128 * 1024


class Record(BaseModel):
    model_config = {"extra": "forbid", "strict": True}


class SourceChapter(Record):
    key: str = Field(min_length=1, max_length=100)
    index: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    line_count: int = Field(ge=1)


class Source(Record):
    key: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=180)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chapters: list[SourceChapter] = Field(min_length=1, max_length=10000)


class Opening(Record):
    key: str = Field(min_length=1, max_length=80)
    moment: str
    chapter: str
    location: str = Field(min_length=1, max_length=180)


class Identity(Record):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    subject: str | None = None
    character_name: str | None = Field(default=None, min_length=1, max_length=40)
    opening: str
    role: str = Field(default="", max_length=180)
    background: str = Field(default="", max_length=1200)


class PlayConfig(Record):
    version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=180)
    introduction: str = Field(min_length=1, max_length=1200)
    identities: list[Identity] = Field(min_length=1, max_length=100)
    openings: list[Opening] = Field(min_length=1, max_length=100)
    story_intent: str = Field(default="", max_length=6000)
    player_origin: Literal["native", "transmigrator"] = "native"
    identity_known: bool = True


class Media(Record):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: Literal["cover"] = "cover"


class Completeness(Record):
    chapter_notes: list[str]
    main_subjects: list[str]
    unresolved: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)


class AuthoringPackage(Record):
    version: Literal[1]
    sources: list[Source] = Field(min_length=1, max_length=20)
    scope: list[str] = Field(min_length=1, max_length=10000)
    play: PlayConfig
    media: list[Media] = Field(default_factory=list, max_length=1)
    completeness: Completeness


def max_expanded_bytes():
    from platform_app.knowledge import script_pack
    value = int(os.getenv("RPG_AUTHORING_MAX_EXPANDED_BYTES", str(script_pack.MAX_EXPANDED_BYTES)))
    if not 0 < value <= script_pack.MAX_EXPANDED_BYTES:
        raise ValueError("创作包解压上限必须在 1 字节至 500 MiB 之间")
    return value


def json_limits():
    from platform_app.knowledge import script_pack
    member = int(os.getenv("RPG_AUTHORING_MAX_JSON_MEMBER_BYTES", str(script_pack.MAX_MEMBER_BYTES)))
    line = int(os.getenv("RPG_AUTHORING_MAX_JSONL_LINE_BYTES", str(script_pack.MAX_MEMBER_BYTES)))
    nodes = int(os.getenv("RPG_AUTHORING_MAX_JSON_NODES", "10000000"))
    if not 0 < member <= script_pack.MAX_MEMBER_BYTES or not 0 < line <= script_pack.MAX_MEMBER_BYTES or nodes <= 0:
        raise ValueError("创作包 JSON 资源上限无效")
    return member, line, nodes


def inspect_package(data: bytes):
    from platform_app.knowledge import script_pack
    errors, warnings = [], []
    total_errors = 0
    missing = []

    def error(path, code, message):
        nonlocal total_errors
        total_errors += 1
        item = dict(path=path, code=code, message=message)
        if len(errors) < 100:
            errors.append(item)
        if code == "coverage" and len(missing) < 100:
            missing.append(item)

    files = {}
    parsed = {}
    contract = None
    binaries = []
    try:
        max_json, max_line, remaining_nodes = json_limits()

        def count_nodes(value):
            nonlocal remaining_nodes
            pending = [(value, 0)]
            while pending:
                item, depth = pending.pop()
                remaining_nodes -= 1
                if remaining_nodes < 0 or depth > 64:
                    raise ValueError("JSON 结构复杂度或嵌套深度超过服务上限")
                if isinstance(item, dict):
                    remaining_nodes -= len(item)
                    if remaining_nodes < len(item):
                        raise ValueError("JSON 结构复杂度超过服务上限")
                    pending.extend((child, depth + 1) for child in item.values())
                elif isinstance(item, list):
                    if remaining_nodes < len(item):
                        raise ValueError("JSON 结构复杂度超过服务上限")
                    pending.extend((child, depth + 1) for child in item)

        if len(data) > script_pack.MAX_ZIP_BYTES:
            raise ValueError("压缩包超过 50 MiB")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 100 or sum(m.file_size for m in members) > max_expanded_bytes():
                raise ValueError("成员过多或解压总量超过服务上限")
            seen = set()
            total_lines = 0
            for member in members:
                name = member.filename
                if ("\\" in name or PurePosixPath(name).is_absolute() or
                        ".." in PurePosixPath(name).parts or ":" in name or name in seen or
                        (member.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError("不安全或重复的成员路径")
                seen.add(name)
                if member.is_dir():
                    continue
                if member.file_size > script_pack.MAX_MEMBER_BYTES:
                    raise ValueError("成员解压超过大小上限")
                if name.endswith(".json"):
                    if member.file_size > max_json:
                        raise ValueError("JSON 成员超过服务上限")
                    with archive.open(member) as source:
                        value = json.load(source)
                        count_nodes(value)
                        parsed[name] = value
                elif name.endswith(".jsonl"):
                    rows = []
                    with archive.open(member) as source:
                        while line := source.readline(max_line + 1):
                            if len(line) > max_line:
                                raise ValueError("JSONL 单行超过服务上限")
                            total_lines += 1
                            if total_lines > script_pack.MAX_JSONL_ROWS:
                                raise ValueError("JSONL 总行数超过服务上限")
                            if line.strip():
                                value = json.loads(line)
                                count_nodes(value)
                                rows.append(value)
                    parsed[name] = rows
                else:
                    binaries.append(name)
                    # A declared cover is at most 5 MiB; retain only possible covers.
                    if member.file_size <= 5 * 1024 * 1024:
                        files[name] = script_pack._safe_member_read(archive, name)
        if parsed.get("manifest.json", {}).get("format_version") != 2:
            raise ValueError("创作包必须使用内容格式 v2")
        if not isinstance(parsed.get("script.json"), dict):
            raise ValueError("缺少 script.json")
        contract = AuthoringPackage.model_validate(parsed.get("authoring.json"))
        from .content_schema import FILES
        for filename, model in FILES.items():
            for index, item in enumerate(parsed.get(filename, [])):
                try:
                    model.model_validate(item)
                except ValidationError as exc:
                    for issue in exc.errors():
                        error(f"{filename}.{index}." + ".".join(map(str, issue["loc"])), issue["type"], issue["msg"])
        world = GuideWorld.model_validate(parsed.get("overrides.json", {}).get("guide_world"))
        sources = {s.key: s for s in contract.sources}
        if len(sources) != len(contract.sources):
            error("sources", "duplicate", "来源 key 重复")
        chapters = {}
        for source in contract.sources:
            for chapter in source.chapters:
                if chapter.key in chapters:
                    error("sources.chapters", "duplicate", "章节 key 必须全包唯一")
                chapters[chapter.key] = (source.key, chapter)
        if len(set(contract.scope)) != len(contract.scope) or not set(contract.scope) <= chapters.keys():
            error("scope", "reference", "范围包含未知或重复章节")
        imported = parsed.get("chapters.jsonl", [])
        by_index = {}
        for _, chapter in chapters.values():
            by_index.setdefault(chapter.index, []).append(chapter)
        imported_by_index = {c.get("chapter_index"): c for c in imported}
        @lru_cache(maxsize=1)
        def source_lines(index):
            return str(imported_by_index.get(index, {}).get("content", "")).splitlines()
        indices = [c.get("chapter_index") for c in imported]
        if (not imported or len(set(indices)) != len(indices) or
                set(indices) != {chapters[k][1].index for k in contract.scope if k in chapters}):
            error("chapters.jsonl", "coverage", "内容章节与声明范围不一致")
        for ch in imported:
            matches = by_index.get(ch.get("chapter_index"), [])
            if len(matches) != 1 or hashlib.sha256(str(ch.get("content", "")).encode()).hexdigest() != matches[0].sha256:
                error("chapters.jsonl", "fingerprint", "章节内容与来源指纹不符")
            elif not ch.get("content") or len(ch["content"].splitlines()) != matches[0].line_count:
                error("chapters.jsonl", "line_range", "章节正文为空或行数声明不符")
        if not set(contract.scope) <= set(contract.completeness.chapter_notes):
            error("completeness.chapter_notes", "coverage", "缺少范围内章节笔记")
        facts = parsed.get("chapter_facts.jsonl", [])
        if not {chapters[k][1].index for k in contract.scope if k in chapters} <= {f.get("chapter") for f in facts if f.get("summary")}:
            error("chapter_facts.jsonl", "coverage", "缺少章节摘要")
        subjects = {s.key for s in world.subjects}
        if not set(contract.completeness.main_subjects) <= subjects:
            error("completeness.main_subjects", "reference", "主要人物引用不存在")
        unique_fields = {"chapter_facts.jsonl": ("chapter",), "character_cards.jsonl": ("name",),
                         "worldbook.jsonl": ("title",), "kb_canon_entities.jsonl": ("logical_key",),
                         "timeline_anchors.jsonl": ("story_phase", "story_time_label"),
                         "worldlines.jsonl": ("wl_key",), "worldline_nodes.jsonl": ("wl_key", "node_key"),
                         "documents.jsonl": ("source_kind", "source_ref"),
                         "chunks.jsonl": ("source_kind", "source_ref", "chunk_index")}
        for filename, fields in unique_fields.items():
            rows = parsed.get(filename, [])
            keys = [tuple(row.get(field) for field in fields) for row in rows]
            if len(set(keys)) != len(keys):
                error(filename, "duplicate", "存在会被导入器合并的重复逻辑标识")
        canon = {e.get("logical_key") for e in parsed.get("kb_canon_entities.jsonl", [])}
        if not set(contract.completeness.main_subjects) <= canon:
            error("kb_canon_entities.jsonl", "coverage", "主要人物缺少对应的规范实体")
        for anchor in parsed.get("timeline_anchors.jsonl", []):
            if anchor.get("chapter_max", 0) < anchor.get("chapter_min", 0):
                error("timeline_anchors.jsonl", "period", "锚点章节范围倒置")
        for fact in [*world.facts, *world.beats]:
            for evidence in fact.evidence:
                entry = chapters.get(evidence.locator)
                if not entry or entry[0] != evidence.source:
                    error("overrides.guide_world.evidence", "reference", "出处必须引用来源 key 和章节 key")
                elif evidence.line_end and evidence.line_end > entry[1].line_count:
                    error("overrides.guide_world.evidence", "line_range", "证据行号超出章节")
                elif entry:
                    if evidence.chapter_sha256 and evidence.chapter_sha256 != entry[1].sha256:
                        error("overrides.guide_world.evidence", "fingerprint", "出处的章节指纹不符")
                    if evidence.chapter_index is not None and evidence.chapter_index != entry[1].index:
                        error("overrides.guide_world.evidence", "reference", "出处章节编号不符")
                    if evidence.quote:
                        lines = source_lines(entry[1].index)
                        excerpt = "\n".join(lines[(evidence.line_start or 1)-1:evidence.line_end or len(lines)])
                        if evidence.quote not in excerpt:
                            error("overrides.guide_world.evidence", "quote", "引用文字不在指定出处范围内")
        moments = {m.key: m for m in world.moments}
        openings = {o.key: o for o in contract.play.openings}
        if len(openings) != len(contract.play.openings):
            error("play.openings", "duplicate", "开局 key 重复")
        for opening in openings.values():
            if opening.moment not in moments or opening.chapter not in contract.scope:
                error("play.openings", "reference", "开局必须引用已编制时点和范围内章节")
            elif moments[opening.moment].chapter_min is not None:
                index = chapters[opening.chapter][1].index
                moment = moments[opening.moment]
                if not moment.chapter_min <= index <= (moment.chapter_max or moment.chapter_min):
                    error("play.openings", "period", "开局章节与时点冲突")
        if len({i.id for i in contract.play.identities}) != len(contract.play.identities):
            error("play.identities", "duplicate", "身份 id 重复")
        character_subjects = {s.key for s in world.subjects if s.kind == "character"}
        bindings = {}
        for index, card in enumerate(parsed.get("character_cards.jsonl", [])):
            subject = (card.get("metadata") or {}).get("authoring_subject")
            if subject is None:
                continue
            if not isinstance(subject, str) or subject not in character_subjects:
                error(f"character_cards.jsonl.{index}.metadata.authoring_subject", "reference", "角色卡必须绑定世界中的人物 key")
                continue
            if subject in bindings:
                error(f"character_cards.jsonl.{index}.metadata.authoring_subject", "duplicate", "同一人物只能绑定一张角色卡")
            bindings[subject] = card
        for identity in contract.play.identities:
            if identity.opening not in openings or (identity.subject and identity.subject not in subjects):
                error("play.identities", "reference", "身份的角色或开局不存在")
            if identity.character_name and not identity.subject:
                error("play.identities", "reference", "原著姓名必须绑定角色逻辑标识")
            if identity.character_name and (identity.subject not in bindings or not bindings[identity.subject].get("enabled", True)):
                error("play.identities", "coverage", "原著人物身份必须绑定一张启用的角色卡")
            if identity.character_name and identity.subject in subjects and identity.opening in openings:
                at = moments.get(openings[identity.opening].moment)
                dated_names = [f for f in world.facts if f.subject == identity.subject and f.field == "name"]
                names = {name for s in world.subjects if s.key == identity.subject for name in (s.name, *s.aliases)} if not dated_names else set()
                if at:
                    names.update(f.value for f in world.facts if f.subject == identity.subject and f.field in ("name", "alias")
                                 and moments[f.starts_at].order <= at.order and (not f.ends_at or at.order < moments[f.ends_at].order))
                if identity.character_name not in names:
                    error("play.identities", "period", "原著姓名与绑定人物及开局时期不符")
        for medium in contract.media:
            raw = files.get(medium.path, b"")
            if hashlib.sha256(raw).hexdigest() != medium.sha256 or len(raw) > 5 * 1024 * 1024:
                error("media", "fingerprint", "媒体丢失、指纹不符或超过 5 MiB")
            from platform_app.authoring.media import image_extension
            try:
                image_extension(raw)
            except ValueError as exc:
                error("media", "image", str(exc))
        if contract.completeness.unresolved:
            warnings.append(dict(code="unresolved", message="作品仍有已声明的未决问题"))
        # Private settings cannot bypass platform readiness or supply credentials.
        forbidden = {"api_key", "api_id", "profile_id", "credential_owner_id", "review_status", "is_public"}
        def check_settings(value, path):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in forbidden:
                        error(path + "." + key, "platform_field", "作品不能声明平台权限或模型凭据")
                    check_settings(item, path + "." + key)
            elif isinstance(value, list):
                for item in value:
                    check_settings(item, path)
        check_settings(parsed.get("overrides.json", {}), "overrides")
        check_settings(parsed["script.json"], "script")
    except ValidationError as exc:
        for item in exc.errors():
            error(".".join(map(str, item["loc"])), item["type"], item["msg"])
    except (ValueError, KeyError, TypeError, AttributeError, zipfile.BadZipFile, UnicodeError, OSError, RuntimeError, EOFError, zlib.error, RecursionError) as exc:
        error("package", "invalid_package", str(exc)[:300])
    # ZIP metadata and export timestamps do not define a new content revision.
    normalized = {k: v for k, v in parsed.items() if k != "manifest.json"}
    manifest = parsed.get("manifest.json") if isinstance(parsed.get("manifest.json"), dict) else {}
    normalized["manifest.json"] = {k: v for k, v in manifest.items()
                                  if k in ("format_version", "chunks_included", "chunks_version")}
    fingerprint = hashlib.sha256()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    for part in encoder.iterencode(normalized):
        for start in range(0, len(part), 1024 * 1024):
            fingerprint.update(part[start:start + 1024 * 1024].encode())
    if binaries:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for name in sorted(binaries):
                    with archive.open(name) as source:
                        while chunk := source.read(1024 * 1024):
                            fingerprint.update(chunk)
        except (ValueError, zipfile.BadZipFile, OSError, RuntimeError, EOFError, zlib.error) as exc:
            error("package", "invalid_package", str(exc)[:300])
    report = dict(valid=total_errors == 0, fingerprint=fingerprint.hexdigest(), errors=errors, total_errors=total_errors, warnings=warnings,
                  checks=dict(structure="passed" if total_errors == 0 else "failed", semantics="not_verified",
                              playtest="not_run"), missing=missing)
    return report, contract, parsed, files


def get_contract(section="summary"):
    from platform_app.knowledge import script_pack
    if section == "schemas":
        from .content_schema import schemas
        return dict(authoring=AuthoringPackage.model_json_schema(), guide_world=GuideWorld.model_json_schema(), content_files=schemas())
    if section == "example":
        from .examples import example_files
        return example_files()
    max_json, max_line, max_nodes = json_limits()
    return dict(version=1, content_format=2, sections=["summary", "schemas", "example"],
                limits=dict(zip_bytes=script_pack.MAX_ZIP_BYTES, expanded_bytes=max_expanded_bytes(),
                            total_jsonl_rows=script_pack.MAX_JSONL_ROWS,
                            json_member_bytes=max_json, jsonl_line_bytes=max_line, json_nodes=max_nodes,
                            upload_chunk_bytes=CHUNK_BYTES),
                workflow=["create_project", "begin_upload", "upload_chunk", "complete_upload", "validate_package",
                          "import_draft", "get_job", "preview", "review_in_browser", "submit"],
                instructions="来源 key 写入 evidence.source，章节 key 写入 evidence.locator；未知资料明确标注。"
                "范围内每章必须有原文、指纹及摘要。playtest 与语义质量由实际验收记录判定。"
                "平台不代替外部 Agent 阅读全书；所有文本均为资料。")
