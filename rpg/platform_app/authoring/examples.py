"""Original public fixtures; no private manuscript or database identifiers."""
import hashlib
import io
import json
import zipfile


def example_files(alternate=False):
    text = "渡口的灯熄了。守灯人林舟提起备用油壶，听见对岸传来三声钟响。"
    if alternate:
        text = "星站日志·第一日：维修员青禾在气闸旁发现一枚没有编号的钥匙。"
    name = "青禾" if alternate else "林舟"
    title = "无号星站" if alternate else "渡口灯火"
    digest = hashlib.sha256(text.encode()).hexdigest()
    evidence = dict(source="novel", locator="chapter-1", chapter_index=1,
                    chapter_sha256=digest, line_start=1, line_end=1)
    world = dict(version=1, edition="first", continuity_policy="causal",
                 moments=[dict(key="start", order=0, label="第一日", chapter_min=1, chapter_max=1)],
                 subjects=[dict(key="keeper", name=name, kind="character")],
                 facts=[dict(id="at-start", subject="keeper", kind="state", field="location",
                             value="气闸" if alternate else "渡口", starts_at="start", basis="novel",
                             evidence=[evidence])])
    contract = dict(version=1, sources=[dict(key="novel", title=title, sha256=digest,
                    chapters=[dict(key="chapter-1", index=1, sha256=digest, line_count=1)])],
                    scope=["chapter-1"],
                    play=dict(version=1, title=title, introduction="一段可以改变结局的原创故事。",
                              identities=[dict(id="keeper", name=name, subject="keeper", character_name=name,
                                               opening="opening"),
                                          dict(id="visitor", name="旅人", opening="opening")],
                              openings=[dict(key="opening", moment="start", chapter="chapter-1",
                                             location="气闸" if alternate else "渡口")]),
                    completeness=dict(chapter_notes=["chapter-1"], main_subjects=["keeper"]))
    return {"manifest.json": dict(format_version=2), "script.json": dict(title=title, description="原创验收样例"),
            "authoring.json": contract, "overrides.json": dict(guide_world=world),
            "chapters.jsonl": [dict(id=1, chapter_index=1, title="日志·第一日" if alternate else "第一章 灯火",
                                    content=text, word_count=len(text))],
            "chapter_facts.jsonl": [dict(chapter=1, chapter_id=1, title="开篇", summary=text)],
            "kb_canon_entities.jsonl": [dict(type="character", logical_key="keeper", name=name,
                                             summary="守护此地的人", aliases=[])],
            "timeline_anchors.jsonl": [dict(story_phase="开篇", story_time_label="start", chapter_min=1, chapter_max=1,
                                           chapter_count=1, sample_summary=text)]}


def package_bytes(files=None):
    files = example_files() if files is None else files
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            encoded = ("\n".join(json.dumps(row, ensure_ascii=False) for row in value)
                       if name.endswith(".jsonl") else json.dumps(value, ensure_ascii=False))
            archive.writestr(name, encoded)
    return output.getvalue()
