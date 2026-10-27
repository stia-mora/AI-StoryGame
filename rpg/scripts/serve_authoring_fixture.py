"""Loopback-only visual QA fixture, always run via check_authoring.py --serve."""
import os

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

assert conninfo_to_dict(os.environ["DATABASE_URL"])["dbname"].startswith("authoring_test_")

import app
from platform_app import auth
from platform_app.authoring import service
from platform_app.db import connect
from tests.integration.test_authoring import imported

with connect() as db:
    user = db.execute("insert into users(username,password_hash,display_name,account_mode,role,email_verified) "
                      "values('fixture_creator','test','林间作者','creator','admin',true) returning *").fetchone()
    profile = db.execute("insert into player_model_profiles(name,credential_owner_id,api_id,model,max_output) "
                         "values('验收模型（未配置真实凭据）',%s,'test','text',1024) returning id", (user["id"],)).fetchone()
    db.execute("insert into app_config(key,value) values('authoring',%s)", (Jsonb(dict(preview_profile_id=profile["id"])),))
project, _, _, revision = imported(dict(uid=user["id"], user=user))
service.review(user["id"], revision["id"], "原创短篇，作者授权用于平台公开游玩。")
service.submit(user["id"], revision["id"])
with connect() as db:
    cookie = auth._issue_session(db, user["id"])

fixture = FastAPI()


@fixture.get("/fixture/login")
def login():
    response = RedirectResponse(f"/play/authoring?project={project['id']}", 303)
    response.set_cookie("rpg_session", cookie, httponly=True, samesite="lax")
    return response


fixture.mount("/", app.app)
print("Visual QA fixture: http://127.0.0.1:17864/fixture/login", flush=True)
uvicorn.run(fixture, host="127.0.0.1", port=17864, log_level="warning")
