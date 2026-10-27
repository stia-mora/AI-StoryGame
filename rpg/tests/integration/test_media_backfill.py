"""Offline repair requires a server-generated name and corroborating metadata."""
# ruff: noqa: F811 -- imported pytest fixtures are injected by name.
from platform_app.db import connect
from scripts.backfill_media_ownership import audit
from tests.integration.test_authoring import creator, isolated_database  # noqa: F401


def test_backfill_reports_conflicts_and_never_reads_file_contents(creator, tmp_path):
    owner, other = creator["uid"], creator["admin"]["id"]
    images = tmp_path / "ai_images"
    avatars = tmp_path / "avatars"
    images.mkdir()
    avatars.mkdir()
    image = f"upload_{owner}_{'a' * 24}.png"
    orphan = f"upload_{owner}_{'b' * 24}.png"
    conflict = f"u{owner}_12345.png"
    unknown = "legacy.png"
    for directory, name in [(images, image), (images, orphan), (images, unknown), (avatars, conflict)]:
        (directory / name).touch()
    url = f"/api/storage/ai_images/{image}"
    with connect() as db:
        db.execute("insert into character_cards(user_id,name,slug,card_type,source,avatar_path) "
                   "values(%s,'Card',%s,'pc','user',%s)", (owner, image, url))
        db.execute("insert into user_assets(user_id,kind,storage_key,url,source) "
                   "values(%s,'avatar',%s,%s,'avatar_upload')",
                   (other, f"avatars/{conflict}", f"/api/storage/avatars/{conflict}"))
        before = {row["storage_key"]: row["status"] for row in audit(db, tmp_path)}
        assert before == {f"ai_images/{image}": "eligible", f"ai_images/{orphan}": "unresolved_no_reference",
                          f"ai_images/{unknown}": "unresolved_filename", f"avatars/{conflict}": "conflicting_owner"}
        assert db.execute("select 1 from user_assets where storage_key=%s", (f"ai_images/{image}",)).fetchone() is None
        after = {row["storage_key"]: row["status"] for row in audit(db, tmp_path, apply=True)}
        assert after[f"ai_images/{image}"] == "inserted"
        assert after[f"avatars/{conflict}"] == "conflicting_owner"
        assert db.execute("select user_id from user_assets where storage_key=%s", (f"ai_images/{image}",)).fetchone()["user_id"] == owner
        assert {row["storage_key"]: row["status"] for row in audit(db, tmp_path, apply=True)}[f"ai_images/{image}"] == "already_recorded"
