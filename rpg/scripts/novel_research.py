"""Build a lossless, local reading index; indexing never claims a book was read.

python -m scripts.novel_research prepare SOURCE OUTPUT --encoding gb18030
python -m scripts.novel_research read OUTPUT --first 1 --last 3
Output includes private manuscript text and must remain outside version control.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

HEADING = re.compile(r"^第[零〇一二三四五六七八九十百千万两0-9]+(?P<kind>[卷章回])(?:\s.*)?$")
PARATEXT = re.compile(r"(?P<supplement>番外\d+)|(?P<author_note>完本感言)|(?P<distribution_notice>={10,})")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build_index(raw: bytes, encoding: str) -> tuple[str, dict]:
    text = raw.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines(keepends=True)
    sections = []
    offset = 0
    volume = ""
    volume_index = 0
    chapter_in_volume = 0
    chapter_index = 0
    for line_number, line in enumerate(lines, 1):
        title = line.strip()
        match = HEADING.fullmatch(title)
        paratext = PARATEXT.fullmatch(title)
        kind = None
        if match:
            kind = "volume" if match["kind"] == "卷" else "chapter"
        elif paratext:
            kind = paratext.lastgroup
        if kind:
            if kind == "distribution_notice" and sections and sections[-1]["kind"] == kind:
                offset += len(line)
                continue
            if kind == "volume":
                volume = title
                volume_index += 1
                chapter_in_volume = 0
            elif kind == "chapter":
                chapter_index += 1
                chapter_in_volume += 1
            sections.append({
                "kind": kind,
                "title": title,
                "volume": volume,
                "volume_index": volume_index,
                "chapter_index": chapter_index if kind == "chapter" else None,
                "chapter_in_volume": chapter_in_volume if kind == "chapter" else None,
                "char_start": offset,
                "line_start": line_number,
            })
        offset += len(line)
    if not any(section["kind"] == "chapter" for section in sections):
        raise ValueError("No chapter headings recognized")
    if sections[0]["char_start"]:
        sections.insert(0, {
            "kind": "preface", "title": "书前资料", "char_start": 0, "line_start": 1,
        })
    for index, section in enumerate(sections):
        following = sections[index + 1] if index + 1 < len(sections) else None
        section["char_end"] = following["char_start"] if following else len(text)
        section["line_end"] = following["line_start"] - 1 if following else len(lines)
        content = text[section["char_start"]:section["char_end"]]
        section["sha256"] = sha256(content.encode("utf-8"))
    counts = Counter(section.get("volume", "") for section in sections if section["kind"] == "chapter")
    return text, {
        "format_version": 1,
        "source_sha256": sha256(raw),
        "source_bytes": len(raw),
        "encoding": encoding,
        "normalized_sha256": sha256(text.encode("utf-8")),
        "characters": len(text),
        "lines": len(lines),
        "chapter_count": chapter_index,
        "supplement_count": sum(section["kind"] == "supplement" for section in sections),
        "volumes": dict(counts),
        "sections": sections,
    }


def prepare(source: Path, output: Path, encoding: str) -> dict:
    text, index = build_index(source.read_bytes(), encoding)
    output.mkdir(parents=True, exist_ok=True)
    index_path = output / "index.json"
    if index_path.exists():
        existing = json.loads(index_path.read_text(encoding="utf-8"))
        if existing["source_sha256"] != index["source_sha256"]:
            raise ValueError("Source changed; use a separate directory to preserve reading references")
    # Keep these two generated files separate from hand-written notes and ledgers.
    (output / "source.utf8.txt").write_bytes(text.encode("utf-8"))
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: value for key, value in index.items() if key != "sections"}


def read_chapters(output: Path, first: int, last: int) -> str:
    index = json.loads((output / "index.json").read_text(encoding="utf-8"))
    raw = (output / "source.utf8.txt").read_bytes()
    if sha256(raw) != index["normalized_sha256"]:
        raise ValueError("Indexed manuscript changed; rebuild the index before reading")
    if not 1 <= first <= last <= index["chapter_count"]:
        raise ValueError("Chapter range is outside the indexed manuscript")
    text = raw.decode("utf-8")
    chunks = []
    for section in index["sections"]:
        number = section.get("chapter_index")
        if number is None or not first <= number <= last:
            continue
        chunks.append(f"\n=== global chapter {number} | {section['volume']} | {section['title']} ===\n")
        content = text[section["char_start"]:section["char_end"]]
        chunks.extend(
            f"L{line_number}: {line}"
            for line_number, line in enumerate(content.splitlines(keepends=True), section["line_start"])
        )
    return "".join(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("source", type=Path)
    prep.add_argument("output", type=Path)
    prep.add_argument("--encoding", default="utf-8")
    read = sub.add_parser("read")
    read.add_argument("output", type=Path)
    read.add_argument("--first", type=int, required=True)
    read.add_argument("--last", type=int, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        print(json.dumps(prepare(args.source, args.output, args.encoding), ensure_ascii=False, indent=2))
    else:
        print(read_chapters(args.output, args.first, args.last))


if __name__ == "__main__":
    main()
