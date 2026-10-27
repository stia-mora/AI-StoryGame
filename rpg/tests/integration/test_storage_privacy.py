"""Private files remain private across current and legacy image URLs."""
# ruff: noqa: F811 -- imported pytest fixtures are injected by name.
import uuid

import pytest
from fastapi.testclient import TestClient

import app
from platform_app import auth, storage
from platform_app.assets_registry import register_asset
from platform_app.db import connect
from tests.integration.test_authoring import creator, isolated_database  # noqa: F401


def test_image_ownership_public_cards_and_subscribed_scripts(creator, monkeypatch):
    owner, viewer = creator["user"], creator["admin"]
    name = f"private_{uuid.uuid4().hex}.png"
    key, url = storage.store_bytes(b"private image", kind="ai_images", filename=name)
    legacy = f"/api/images/file/{name}"
    register_asset(user_id=owner["id"], kind="card_image", storage_key=key, url=url)
    monkeypatch.setattr(auth, "user_from_token", lambda token: {"owner": owner, "viewer": viewer}.get(token))
    client = TestClient(app.app)
    client.cookies.set("rpg_session", "owner")
    assert client.get(url).content == b"private image"
    assert client.get(legacy).content == b"private image"
    client.cookies.set("rpg_session", "viewer")
    assert client.get(url).status_code == 404
    assert client.get(legacy).status_code == 404

    # An attacker cannot publish somebody else's private image by referencing it.
    with connect() as db:
        db.execute("insert into character_cards(user_id,name,card_type,source,slug,avatar_path,is_public) "
                   "values(%s,'Other','pc','user',%s,%s,true)", (viewer["id"], uuid.uuid4().hex, url))
        db.execute("update users set avatar_url=%s where id=%s", (url, viewer["id"]))
    assert client.get(url).status_code == 404

    with connect() as db:
        card = db.execute("insert into character_cards(user_id,name,card_type,source,slug,avatar_path,is_public) "
                          "values(%s,'Public','pc','user',%s,%s,true) returning id",
                          (owner["id"], uuid.uuid4().hex, legacy)).fetchone()
    assert client.get(url).content == b"private image"
    assert client.get(legacy).content == b"private image"
    with connect() as db:
        db.execute("update character_cards set is_public=false where id=%s", (card["id"],))
        script = db.execute("insert into scripts(owner_id,title,cover_image_url) values(%s,'Shared',%s) returning id",
                            (owner["id"], url)).fetchone()
    assert client.get(url).status_code == 404
    with connect() as db:
        db.execute("insert into user_script_subscriptions(user_id,script_id) values(%s,%s)", (viewer["id"], script["id"]))
    assert client.get(url).content == b"private image"


def test_legacy_generated_image_without_registry_and_avatar_alias(creator, monkeypatch):
    owner, viewer = creator["user"], creator["admin"]
    name = f"old_{uuid.uuid4().hex}.png"
    _, url = storage.store_bytes(b"generated", kind="ai_images", filename=name)
    legacy = f"/api/images/file/{name}"
    avatar_name = f"u{owner['id']}_123456.png"
    avatar_key, avatar_url = storage.store_bytes(b"avatar", kind="avatars", filename=avatar_name)
    register_asset(user_id=owner["id"], kind="avatar", storage_key=avatar_key, url=avatar_url)
    # Migration 72 could have backfilled an attacker-controlled avatar URL.
    forged_asset = register_asset(user_id=viewer["id"], kind="avatar", storage_key=avatar_key, url=avatar_url)
    with connect() as db:
        db.execute("insert into ai_images(user_id,kind,status,url) values(%s,'chat','done',%s)", (owner["id"], legacy))
    monkeypatch.setattr(auth, "user_from_token", lambda token: {"owner": owner, "viewer": viewer}.get(token))
    client = TestClient(app.app)
    client.cookies.set("rpg_session", "viewer")
    assert client.get(url).status_code == 404
    assert client.get(legacy).status_code == 404
    assert client.get(avatar_url).status_code == 404
    assert client.get(f"/api/profile/avatar/file/{avatar_name}").status_code == 404
    assert client.get(f"/api/library/asset/{forged_asset}/download").status_code == 404
    assert client.post(f"/api/library/asset/{forged_asset}/delete", json={"confirm": True}).status_code == 404
    client.cookies.set("rpg_session", "owner")
    assert client.get(url).content == b"generated"
    assert client.get(legacy).content == b"generated"
    assert client.get(avatar_url).content == b"avatar"
    with connect() as db:
        db.execute("update users set avatar_url=%s where id=%s", (f"/api/profile/avatar/file/{avatar_name}", owner["id"]))
    client.cookies.set("rpg_session", "viewer")
    assert client.get(avatar_url).content == b"avatar"
    assert client.get(f"/api/profile/avatar/file/{avatar_name}").content == b"avatar"


def test_forked_source_registration_cannot_download_or_delete_original(creator, monkeypatch):
    owner, viewer = creator["user"], creator["admin"]
    key, url = storage.store_bytes(b"private source", kind=f"scripts/user_{owner['id']}", filename="novel.txt")
    forged_asset = register_asset(user_id=viewer["id"], kind="script_txt", storage_key=key, url=url, source="script_import")
    own_key, own_url = storage.store_bytes(b"own source", kind=f"scripts/user_{viewer['id']}", filename="own.txt")
    own_asset = register_asset(user_id=viewer["id"], kind="script_txt", storage_key=own_key, url=own_url, source="script_import")
    monkeypatch.setattr(auth, "user_from_token", lambda token: viewer if token == "viewer" else None)
    client = TestClient(app.app)
    client.cookies.set("rpg_session", "viewer")
    assert client.get(f"/api/library/asset/{forged_asset}/download").status_code == 404
    assert client.post(f"/api/library/asset/{forged_asset}/delete", json={"confirm": True}).status_code == 404
    assert storage.resolve_path(key).read_bytes() == b"private source"
    assert client.get(f"/api/library/asset/{own_asset}/download").content == b"own source"


def test_public_card_history_requires_original_asset_owner(creator, monkeypatch):
    owner, viewer = creator["user"], creator["admin"]
    key, url = storage.store_bytes(b"history", kind="ai_images", filename=f"{uuid.uuid4().hex}.png")
    register_asset(user_id=owner["id"], kind="card_image", storage_key=key, url=url)
    with connect() as db:
        attacker_card = db.execute("insert into character_cards(user_id,name,slug,card_type,source,is_public) "
                                   "values(%s,'Other',%s,'pc','user',true) returning id",
                                   (viewer["id"], uuid.uuid4().hex)).fetchone()
        db.execute("insert into card_persona_images(card_id,image_url,source,status) values(%s,%s,'manual','done')",
                   (attacker_card["id"], url))
    monkeypatch.setattr(auth, "user_from_token", lambda token: viewer if token == "viewer" else None)
    client = TestClient(app.app)
    client.cookies.set("rpg_session", "viewer")
    assert client.get(url).status_code == 404
    with connect() as db:
        public_card = db.execute("insert into character_cards(user_id,name,slug,card_type,source,is_public) "
                                 "values(%s,'Public',%s,'pc','user',true) returning id",
                                 (owner["id"], uuid.uuid4().hex)).fetchone()
        db.execute("insert into card_persona_images(card_id,image_url,source,status) values(%s,%s,'manual','done')",
                   (public_card["id"], url))
    assert client.get(url).content == b"history"
    with connect() as db:
        db.execute("update character_cards set is_public=false where id=%s", (public_card["id"],))
    assert client.get(url).status_code == 404


def test_card_png_export_does_not_read_another_users_private_image(creator, monkeypatch):
    from platform_app import tavern_cards

    owner, viewer = creator["user"], creator["admin"]
    name = f"private_{uuid.uuid4().hex}.png"
    key, url = storage.store_bytes(tavern_cards.PNG_SIGNATURE + b"private bytes", kind="ai_images", filename=name)
    register_asset(user_id=owner["id"], kind="card_image", storage_key=key, url=url)
    with connect() as db:
        card = db.execute("insert into character_cards(user_id,name,card_type,source,slug,avatar_path) "
                          "values(%s,'Other','pc','user',%s,%s) returning id",
                          (viewer["id"], uuid.uuid4().hex, url)).fetchone()
    monkeypatch.setattr(auth, "user_from_token", lambda token: viewer if token == "viewer" else None)
    captured = []
    monkeypatch.setattr(tavern_cards, "write_png_card", lambda v2, template_png: captured.append(template_png) or b"output")
    client = TestClient(app.app)
    client.cookies.set("rpg_session", "viewer")
    assert client.get(f"/api/me/character-cards/{card['id']}/export-png").status_code == 200
    assert captured == [None]
    own_name = f"own_{uuid.uuid4().hex}.png"
    own_bytes = tavern_cards.PNG_SIGNATURE + b"own bytes"
    own_key, own_url = storage.store_bytes(own_bytes, kind="ai_images", filename=own_name)
    register_asset(user_id=viewer["id"], kind="card_image", storage_key=own_key, url=own_url)
    with connect() as db:
        db.execute("update character_cards set avatar_path=%s where id=%s", (own_url, card["id"]))
    assert client.get(f"/api/me/character-cards/{card['id']}/export-png").status_code == 200
    assert captured[-1] == own_bytes


def test_cloned_card_copies_only_authorized_images_and_survives_unpublish(creator, monkeypatch):
    from platform_app import user_cards

    owner, viewer = creator["user"], creator["admin"]
    with connect() as db:
        victim = db.execute("insert into users(username,password_hash,display_name,account_mode) values(%s,'test','Victim','creator') returning id",
                            ("victim_" + uuid.uuid4().hex,)).fetchone()
    images = []
    for uid, content in [(owner["id"], b"avatar"), (owner["id"], b"history"), (victim["id"], b"secret")]:
        key, url = storage.store_bytes(content, kind="ai_images", filename=f"upload_{uid}_{uuid.uuid4().hex[:24]}.png")
        register_asset(user_id=uid, kind="card_image", storage_key=key, url=url)
        images.append(url)
    with connect() as db:
        card = db.execute("insert into character_cards(user_id,name,slug,card_type,source,is_public,avatar_path) "
                          "values(%s,'Public',%s,'pc','user',true,%s) returning id",
                          (owner["id"], uuid.uuid4().hex, images[0])).fetchone()
        for url in images[1:]:
            db.execute("insert into card_persona_images(card_id,image_url,source,status) values(%s,%s,'manual','done')",
                       (card["id"], url))
    clone = user_cards.clone_public_card(viewer["id"], card["id"])
    with connect() as db:
        db.execute("update character_cards set is_public=false where id=%s", (card["id"],))
        avatar = db.execute("select avatar_path from character_cards where id=%s", (clone["card_id"],)).fetchone()["avatar_path"]
        history = db.execute("select image_url from card_persona_images where card_id=%s", (clone["card_id"],)).fetchall()
        assert len(history) == 1
        assert avatar != images[0] and history[0]["image_url"] != images[1]
        assert db.execute("select count(*) n from user_assets where user_id=%s and source='cloned_card'", (viewer["id"],)).fetchone()["n"] == 2
    monkeypatch.setattr(auth, "user_from_token", lambda token: viewer if token == "viewer" else None)
    client = TestClient(app.app)
    client.cookies.set("rpg_session", "viewer")
    assert client.get(avatar).content == b"avatar"
    assert client.get(history[0]["image_url"]).content == b"history"
    assert client.get(images[2]).status_code == 404


def test_clone_copy_failure_rolls_back_records_and_removes_new_file(creator, monkeypatch):
    from platform_app import user_cards

    owner, viewer = creator["user"], creator["admin"]
    urls = []
    for content in (b"one", b"two"):
        key, url = storage.store_bytes(content, kind="ai_images", filename=f"{uuid.uuid4().hex}.png")
        register_asset(user_id=owner["id"], kind="card_image", storage_key=key, url=url)
        urls.append(url)
    with connect() as db:
        card = db.execute("insert into character_cards(user_id,name,slug,card_type,source,is_public,avatar_path) "
                          "values(%s,'Public',%s,'pc','user',true,%s) returning id",
                          (owner["id"], uuid.uuid4().hex, urls[0])).fetchone()
        db.execute("insert into card_persona_images(card_id,image_url,source,status) values(%s,%s,'manual','done')",
                   (card["id"], urls[1]))
    stored = []
    original = storage.store_bytes

    def fail_second(data, *, kind, filename):
        if stored:
            raise OSError("disk unavailable")
        result = original(data, kind=kind, filename=filename)
        stored.append(result[0])
        return result

    monkeypatch.setattr(storage, "store_bytes", fail_second)
    with pytest.raises(OSError):
        user_cards.clone_public_card(viewer["id"], card["id"])
    assert stored and not storage.resolve_path(stored[0]).exists()
    with connect() as db:
        assert db.execute("select count(*) n from user_assets where user_id=%s and source='cloned_card'", (viewer["id"],)).fetchone()["n"] == 0
        assert db.execute("select clone_count from character_cards where id=%s", (card["id"],)).fetchone()["clone_count"] == 0
