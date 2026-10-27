"""Audit legacy media ownership; use --apply to insert only corroborated owners.

This scans filenames and database metadata only, never opens media content.
Review the JSON report and preserve a database backup before applying it.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from platform_app.db import connect
from platform_app.storage import PLATFORM_DATA_ROOT

PATTERNS = {
    "avatars": re.compile(r"u([1-9][0-9]*)_[0-9]+\.(?:png|jpg|jpeg|webp)"),
    "ai_images": re.compile(r"(?:ai|upload|card)_([1-9][0-9]*)_[0-9a-f]{24}\.(?:png|jpg|jpeg|webp)"),
}


def audit(db, root: Path, *, apply: bool = False) -> list[dict]:
    report = []
    for kind, pattern in PATTERNS.items():
        directory = root / kind
        if not directory.is_dir() or directory.is_symlink():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_symlink() or not path.is_file():
                continue
            key = f"{kind}/{path.name}"
            urls = [f"/api/storage/{key}"]
            urls.append(("/api/images/file/" if kind == "ai_images" else "/api/profile/avatar/file/") + path.name)
            registered = {int(row["user_id"]) for row in db.execute(
                "select user_id from user_assets where storage_key=%s", (key,),
            ).fetchall()}
            generated = {int(row["user_id"]) for row in db.execute(
                "select user_id from ai_images where url=any(%s)", (urls,),
            ).fetchall()}
            claims = registered | generated
            match = pattern.fullmatch(path.name)
            owner = int(match.group(1)) if match else None
            item = {"storage_key": key, "filename_owner": owner, "existing_owners": sorted(claims)}
            if owner is None:
                item["status"] = "unresolved_filename"
            elif claims - {owner}:
                item["status"] = "conflicting_owner"
            elif not db.execute("select 1 from users where id=%s", (owner,)).fetchone():
                item["status"] = "missing_user"
            elif owner in registered:
                item["status"] = "already_recorded"
            else:
                # References are only corroboration, never the sole source of an owner.
                reference = db.execute("""
                    select 1 where exists (select 1 from users where id=%s and avatar_url=any(%s))
                      or exists (select 1 from scripts where owner_id=%s and cover_image_url=any(%s))
                      or exists (select 1 from character_cards c left join scripts s on s.id=c.script_id
                                 where (c.user_id=%s or s.owner_id=%s) and c.avatar_path=any(%s))
                      or exists (select 1 from card_persona_images i join character_cards c on c.id=i.card_id
                                 left join scripts s on s.id=c.script_id
                                 where (c.user_id=%s or s.owner_id=%s) and i.image_url=any(%s))
                """, (owner, urls, owner, urls, owner, owner, urls, owner, owner, urls)).fetchone()
                if not reference and owner not in generated:
                    item["status"] = "unresolved_no_reference"
                elif not apply:
                    item["status"] = "eligible"
                else:
                    db.execute("""insert into user_assets(user_id,kind,storage_key,url,source)
                                  values(%s,%s,%s,%s,'ownership_backfill')
                                  on conflict(user_id,storage_key) do nothing""",
                               (owner, "avatar" if kind == "avatars" else "card_image", key, urls[0]))
                    item["status"] = "inserted"
            report.append(item)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="insert corroborated records (default: report only)")
    args = parser.parse_args()
    with connect() as db:
        result = audit(db, PLATFORM_DATA_ROOT, apply=args.apply)
    print(json.dumps({"applied": args.apply, "items": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
