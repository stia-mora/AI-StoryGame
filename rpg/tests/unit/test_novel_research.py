import json

import pytest

from scripts.novel_research import build_index, prepare, read_chapters


def test_sections_cover_every_character_and_keep_volume_local_numbering():
    original = "绍宋\r\n作者资料\r\n第一卷\r\n第一章 起\r\n甲。\r\n第二卷\r\n第一章 终\r\n乙。\r\n附记。"
    raw = original.encode("gb18030")
    text, index = build_index(raw, "gb18030")
    assert "".join(text[s["char_start"]:s["char_end"]] for s in index["sections"]) == text
    assert text == original.replace("\r\n", "\n")
    assert index["volumes"] == {"第一卷": 1, "第二卷": 1}
    chapters = [s for s in index["sections"] if s["kind"] == "chapter"]
    assert [s["chapter_index"] for s in chapters] == [1, 2]
    assert [s["chapter_in_volume"] for s in chapters] == [1, 1]
    assert [(s["line_start"], s["line_end"]) for s in chapters] == [(4, 5), (7, 9)]


def test_reading_is_bounded_and_rejects_modified_source(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("第一卷\n第一章 起\n甲。\n第二章 终\n乙。", encoding="utf-8")
    output = tmp_path / "local"
    prepare(source, output, "utf-8")
    selection = read_chapters(output, 2, 2)
    assert "L4: 第二章 终" in selection
    assert "乙。" in selection and "甲。" not in selection
    with pytest.raises(ValueError, match="range"):
        read_chapters(output, 1, 3)
    (output / "source.utf8.txt").write_text("edited", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        read_chapters(output, 1, 1)


def test_prepare_preserves_notes_and_refuses_another_edition(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("第一章 起\n甲。", encoding="utf-8")
    output = tmp_path / "local"
    prepare(source, output, "utf-8")
    notes = output / "reading-notes.md"
    notes.write_text("精读笔记", encoding="utf-8")
    prepare(source, output, "utf-8")
    original_index = (output / "index.json").read_bytes()
    source.write_text("第一章 起\n另一个版本。", encoding="utf-8")
    with pytest.raises(ValueError, match="Source changed"):
        prepare(source, output, "utf-8")
    assert (output / "index.json").read_bytes() == original_index
    assert notes.read_text(encoding="utf-8") == "精读笔记"
    assert "reviewed" not in json.loads(original_index)


def test_invalid_encoding_and_unrecognized_headings_do_not_silently_drop_text():
    with pytest.raises(UnicodeDecodeError):
        build_index("第一章 起\n甲。".encode("gb18030"), "utf-8")
    with pytest.raises(ValueError, match="No chapter"):
        build_index("只有简介".encode(), "utf-8")


def test_supplements_and_author_notes_are_separate_from_the_last_chapter():
    text, index = build_index(
        "第一章 终\n结局。\n完本感言\n感言。\n番外1\n旁支一。\n番外2\n旁支二。\n============\n下载广告\n============".encode(),
        "utf-8",
    )
    assert index["chapter_count"] == 1
    assert index["supplement_count"] == 2
    assert [s["kind"] for s in index["sections"]] == [
        "chapter", "author_note", "supplement", "supplement", "distribution_notice",
    ]
    chapter = index["sections"][0]
    assert "感言" not in text[chapter["char_start"]:chapter["char_end"]]
    assert "".join(text[s["char_start"]:s["char_end"]] for s in index["sections"]) == text
