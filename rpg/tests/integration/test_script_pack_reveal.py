"""A private story pack must retain entity reveal gates through import and export."""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from tests.helpers import make_client, register_user


def _pack(card_chapter, entry_chapter):
    card = dict(name="时间门测试人物", identity="仅在指定章节可见", enabled=True)
    entry = dict(title="时间门测试条目", content="仅在指定章节可见", enabled=True)
    if card_chapter is not None:
        card["first_revealed_chapter"] = card_chapter
    if entry_chapter is not None:
        entry["first_revealed_chapter"] = entry_chapter
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({"format_version": 2}))
        zf.writestr("script.json", json.dumps({"title": "时间门导入测试"}))
        zf.writestr("character_cards.jsonl", json.dumps(card))
        zf.writestr("worldbook.jsonl", json.dumps(entry))
    return buffer.getvalue()


@pytest.fixture
def owner():
    from platform_app.db import connect

    client = make_client()
    account = register_user(client)
    with connect() as db:
        uid = int(db.execute("select id from users where username=%s",
                             (account["username"],)).fetchone()["id"])
    try:
        yield uid
    finally:
        with connect() as db:
            db.execute("delete from users where id=%s", (uid,))


@pytest.mark.parametrize("card_chapter,entry_chapter", [(7, 9), (None, None)])
def test_pack_round_trip_preserves_actual_entity_search_visibility(owner, card_chapter, entry_chapter):
    from platform_app.db import connect
    from platform_app.knowledge._search import _search_entities
    from platform_app.knowledge.script_pack import export_script_pack, import_script_pack

    first = import_script_pack(_pack(card_chapter, entry_chapter), owner)
    assert first["ok"] and not first["warnings"], first
    exported, _ = export_script_pack(first["script_id"], owner)
    with zipfile.ZipFile(io.BytesIO(exported)) as zf:
        card = json.loads(zf.read("character_cards.jsonl").splitlines()[0])
        entry = json.loads(zf.read("worldbook.jsonl").splitlines()[0])
    assert card["first_revealed_chapter"] == (card_chapter or 0)
    assert entry["first_revealed_chapter"] == (entry_chapter or 0)
    second = import_script_pack(exported, owner)
    assert second["ok"] and not second["warnings"], second
    for sid in (first["script_id"], second["script_id"]):
        with connect() as db:
            for chapter in (1, 7, 9):
                result = _search_entities(db, sid, "时间门", chapter_max=chapter)
                assert bool(result["cards"]) == (chapter >= (card_chapter or 0)), (sid, chapter, result)
                assert bool(result["worldbook"]) == (chapter >= (entry_chapter or 0)), (sid, chapter, result)
