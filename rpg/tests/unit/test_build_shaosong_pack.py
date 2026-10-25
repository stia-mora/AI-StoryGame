import json
import zipfile

import pytest

from scripts.build_shaosong_pack import SOURCE_KEYS, build_pack
from scripts.novel_research import prepare


@pytest.fixture
def manuscript(tmp_path):
    raw = tmp_path / "source.txt"
    raw.write_text("第一卷\n" + "".join(
        f"第{i}章 标题\n" + ("范围外的第四卷情节" if i == 245 else f"正文{i}") + "\n"
        for i in range(1, 246)
    ), encoding="utf-8")
    root = tmp_path / "private"
    prepare(raw, root, "utf-8")
    research = root / "research"
    research.mkdir()
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    notes = [{
        "chapter_index": ch["chapter_index"], "status": "read_and_noted",
        "source": {k: ch[k] for k in SOURCE_KEYS}, "summary": "摘要", "time": "日期未详",
        "onstage": [], "mentioned": [], "locations": [], "changes": [], "guards": [],
    } for ch in index["sections"] if ch["kind"] == "chapter" and ch["chapter_index"] <= 244]
    (research / "chapters-001-244.json").write_text(json.dumps(notes), encoding="utf-8")
    (research / "reading-ledger.json").write_text(json.dumps({
        "reading_complete_for_current_release": True, "release_scope": {"chapter_max": 244},
    }), encoding="utf-8")
    return root, tmp_path / "draft.zip"


def test_pack_excludes_later_story_and_marks_incomplete(manuscript):
    root, output = manuscript
    result = build_pack(root, output)
    assert result["chapters"] == 244
    with zipfile.ZipFile(output) as zf:
        assert zf.testzip() is None
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["format_version"] == 2
        assert manifest["authoring_status"] == "draft"
        chapters = [json.loads(line) for line in zf.read("chapters.jsonl").splitlines()]
        assert chapters[-1]["chapter_index"] == 244
        assert "范围外的第四卷情节" not in zf.read("chapters.jsonl").decode()
        assert zf.read("character_cards.jsonl") == b""
        assert len(zf.read("chapter_facts.jsonl").splitlines()) == 244


def test_changed_source_does_not_replace_output(manuscript):
    root, output = manuscript
    output.write_bytes(b"existing draft")
    with (root / "source.utf8.txt").open("a", encoding="utf-8") as f:
        f.write("changed")
    with pytest.raises(ValueError, match="fingerprint"):
        build_pack(root, output)
    assert output.read_bytes() == b"existing draft"


def test_missing_reviewed_chapter_is_rejected(manuscript):
    root, output = manuscript
    path = root / "research" / "chapters-001-244.json"
    notes = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(notes[:-1]), encoding="utf-8")
    with pytest.raises(ValueError, match="unique and cover"):
        build_pack(root, output)
    assert not output.exists()


def test_misaligned_evidence_is_rejected(manuscript):
    root, output = manuscript
    path = root / "research" / "chapters-001-244.json"
    notes = json.loads(path.read_text(encoding="utf-8"))
    notes[0]["source"]["sha256"] = "incorrect"
    path.write_text(json.dumps(notes), encoding="utf-8")
    with pytest.raises(ValueError, match="chapter 1"):
        build_pack(root, output)
    assert not output.exists()


def write_world(root):
    first = json.loads((root / "index.json").read_text(encoding="utf-8"))["sections"]
    first = next(ch for ch in first if ch["kind"] == "chapter")
    model = {"version": 1, "edition": "test-draft", "moments": [
        {"key": "start", "order": 0, "label": "开篇", "chapter_min": 1, "chapter_max": 244},
    ], "subjects": [{"key": "test", "name": "测试人物", "kind": "character"}], "facts": [
        {"id": "test-state", "subject": "test", "kind": "state", "field": "status",
         "value": "已核对的状态", "starts_at": "start", "basis": "novel", "evidence": [
             {"source": "测试稿", "locator": "第1章", "chapter_index": 1,
              "line_start": first["line_start"], "line_end": first["line_end"],
              "chapter_sha256": first["sha256"]},
         ]},
    ]}
    path = root / "authoring" / "guide-world.json"
    path.parent.mkdir()
    path.write_text(json.dumps(model), encoding="utf-8")
    return path, model


def test_curated_world_is_validated_and_included_without_marking_story_complete(manuscript):
    root, output = manuscript
    write_world(root)
    result = build_pack(root, output)
    assert result["guide_subjects"] == result["guide_facts"] == 1
    with zipfile.ZipFile(output) as zf:
        assert json.loads(zf.read("overrides.json"))["guide_world"]["facts"][0]["value"] == "已核对的状态"
        assert json.loads(zf.read("manifest.json"))["authoring_status"] == "draft"


@pytest.mark.parametrize('corrupt', [False, True])
def test_scene_conditions_round_trip_and_unreviewed_evidence_never_replaces_pack(manuscript, corrupt):
    root, output = manuscript
    path, model = write_world(root)
    model['moments'].append(dict(key='end', order=1, label='场景结束边界'))
    evidence = dict(model['facts'][0]['evidence'][0])
    if corrupt:
        evidence['chapter_sha256'] = '0'*64
    model['beats'] = [dict(key='opening', title='开场条件', starts_at='start', ends_at='end',
                          subjects=['test'], pressure='先核实际状态。', evidence=[evidence],
                          conditions=[dict(key='status', label='人员状态', fact_ids=['test-state'],
                                           recheck='改变后重估。')], choices=['可核实后行动。'])]
    path.write_text(json.dumps(model), encoding='utf-8')
    output.write_bytes(b'previous draft')
    if corrupt:
        with pytest.raises(ValueError, match='Guide evidence'):
            build_pack(root, output)
        assert output.read_bytes() == b'previous draft'
    else:
        from platform_app.player.guide_world import GuideWorld

        build_pack(root, output)
        with zipfile.ZipFile(output) as zf:
            packed = json.loads(zf.read('overrides.json'))['guide_world']
        assert GuideWorld.model_validate(packed).beats == GuideWorld.model_validate(model).beats


def test_timeline_exports_only_selectable_moments_and_does_not_use_later_chapter_results(manuscript):
    root, output = manuscript
    path, model = write_world(root)
    model["moments"][0]["chapter_max"] = 1
    model["moments"].extend([
        {"key": "later", "order": 1, "label": "同章稍后", "chapter_min": 1, "chapter_max": 1},
        {"key": "history", "order": 2, "label": "另一条历史的时间"},
        {"key": "end", "order": 3, "label": "非开局的排他结束边界"},
    ])
    model["facts"].extend([
        {**model["facts"][0], "id": "later-event", "kind": "event",
         "value": "稍后发生的结果", "starts_at": "later"},
        {**model["facts"][0], "id": "history-event", "kind": "event", "basis": "history",
         "value": "另一历史结果", "starts_at": "start"},
    ])
    path.write_text(json.dumps(model), encoding="utf-8")
    result = build_pack(root, output)
    assert result["timeline_anchors"] == 2
    with zipfile.ZipFile(output) as zf:
        anchors = [json.loads(line) for line in zf.read("timeline_anchors.jsonl").splitlines()]
    assert [a["story_time_label"] for a in anchors] == ["开篇", "同章稍后"]
    assert anchors[0]["sample_summary"] == "开篇"
    assert anchors[1]["sample_summary"] == "稍后发生的结果"
    assert all(a["story_phase"] == "第一卷" and a["chapter_min"] == a["chapter_max"] == 1 for a in anchors)
    from platform_app.player.guide_world import bind_initial
    for anchor, expected in zip(anchors, ("start", "later"), strict=True):
        snapshot = {"world": {"time": anchor["story_time_label"]}, "worldline": {"progress_chapter": 1}}
        bind_initial(model, snapshot)
        assert snapshot["world"]["guide_moment"] == expected


@pytest.mark.parametrize("change", ["chapter", "hash", "line", "moment"])
def test_invalid_curated_evidence_preserves_existing_pack(manuscript, change):
    root, output = manuscript
    path, model = write_world(root)
    evidence = model["facts"][0]["evidence"][0]
    if change == "chapter":
        evidence["chapter_index"] = 245
    elif change == "hash":
        evidence["chapter_sha256"] = "0" * 64
    elif change == "line":
        evidence["line_end"] += 100
    else:
        model["moments"][0]["chapter_max"] = 245
    path.write_text(json.dumps(model), encoding="utf-8")
    output.write_bytes(b"previous draft")
    with pytest.raises(ValueError, match="Guide"):
        build_pack(root, output)
    assert output.read_bytes() == b"previous draft"
