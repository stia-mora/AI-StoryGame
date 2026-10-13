"""Load a private local player catalog config. Never commit private config/source text.

Usage: python -m scripts.player_catalog --config /private/catalog.json --admin-id ID
Config: {"profile": {"api_id": "...", "model": "..."}, "stories": [{...}]}.
The same validation/audit functions as the administration UI are used.
"""

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from platform_app.api.admin.player import profile, story
from platform_app.db import connect, init_db


class Body:
    def __init__(self, data):
        self.data = data

    async def json(self):
        return self.data


async def run(args):
    init_db()
    with connect() as db:
        admin = db.execute(
            "select * from users where id=%s and role='admin'", (args.admin_id,)
        ).fetchone()
    if not admin:
        raise ValueError("Administrator account required")
    config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    selected = await profile(Body(config["profile"]), admin)
    for item in config["stories"]:
        result = await story(Body({**item, "profile_id": selected["id"]}), admin)
        print(f"Catalog entry {result['id']} configured ({result['status']})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--admin-id", required=True, type=int)
    asyncio.run(run(parser.parse_args()))
