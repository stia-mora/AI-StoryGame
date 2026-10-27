"""Run checks against a disposable PostgreSQL database, never the user's database."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def main():
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    source = os.environ["DATABASE_URL"]
    name = "authoring_test_" + uuid.uuid4().hex[:16]
    options = conninfo_to_dict(source)
    options["dbname"] = name
    clients = "--clients" in sys.argv
    serve = "--serve" in sys.argv
    private_pack = "--private-pack" in sys.argv
    live_model = "--live-model" in sys.argv
    arguments = [arg for arg in sys.argv[1:] if arg not in ("--clients", "--serve", "--private-pack", "--live-model")]
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
        try:
            with tempfile.TemporaryDirectory(prefix="authoring-check-") as directory:
                env = dict(os.environ, DATABASE_URL=make_conninfo(**options), RPG_REQUIRE_AUTH="1",
                           RPG_FEDERATION_PROVIDER="1", RPG_SKIP_AUTO_MIGRATE="0", RPG_ENV="dev",
                           PUBLIC_BASE_URL="http://127.0.0.1:17864", RPG_DATA_ROOT=directory,
                           RPG_MASTER_KEY="authoring-tests-only-master-key-32-characters")
                if clients:
                    env["AUTHORING_CLIENT_CHECKS"] = "1"
                if private_pack:
                    env["AUTHORING_PRIVATE_PACK"] = str(root.parent / "manuscript/shaosong/authoring/shaosong-yaoshan.playtest.pack.zip")
                if live_model:
                    # Read source configuration only; all saves and charges use the disposable DB.
                    env["AUTHORING_SOURCE_DATABASE_URL"] = source
                    master = os.environ.get("RPG_MASTER_KEY", "")
                    fallback = root / "platform_data/master.key"
                    env["AUTHORING_SOURCE_MASTER_KEY"] = master or (fallback.read_text().strip() if fallback.is_file() else "")
                if serve:
                    env["RPG_CORS_ORIGINS"] = "http://127.0.0.1:17864"
                command = [sys.executable, "-m", "pytest", *arguments] if arguments else [
                    sys.executable, "-m", "pytest", "tests/unit/test_authoring_contract.py",
                    "tests/integration/test_authoring.py", "tests/integration/test_authoring_http.py",
                    "tests/integration/test_authoring_regressions.py", "tests/integration/test_authoring_clients.py", "-q"]
                initialized = subprocess.call([sys.executable, "-c", "from platform_app.db import init_db; init_db()"], cwd=root, env=env)
                if initialized:
                    return initialized
                if serve:
                    return subprocess.call([sys.executable, "-m", "scripts.serve_authoring_fixture"], cwd=root, env=env)
                return subprocess.call(command, cwd=root, env=env)
        finally:
            # The name is generated above and cannot refer to an existing user database.
            admin.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(name)))


if __name__ == "__main__":
    raise SystemExit(main())
