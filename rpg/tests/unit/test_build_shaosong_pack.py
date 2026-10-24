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
