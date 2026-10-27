"""Loopback-only visual QA fixture, always run via check_authoring.py --serve."""
import os
import uuid

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

assert conninfo_to_dict(os.environ["DATABASE_URL"])["dbname"].startswith("authoring_test_")

import app
from platform_app import auth
from platform_app.authoring import preview, service
from platform_app.db import connect, init_db
from tests.integration.test_authoring import imported

init_db()
with connect() as db:
    user = db.execute("insert into users(username,password_hash,display_name,account_mode,role,email_verified) "
                      "values('fixture_creator','test','林间作者','creator','admin',true) returning *").fetchone()
    profile = db.execute("insert into player_model_profiles(name,credential_owner_id,api_id,model,max_output) "
                         "values('验收模型（未配置真实凭据）',%s,'test','text',1024) returning id", (user["id"],)).fetchone()
    db.execute("insert into app_config(key,value) values('authoring',%s)", (Jsonb(dict(preview_profile_id=profile["id"])),))
project, _, _, revision = imported(dict(uid=user["id"], user=user))
service.review(user["id"], revision["id"], "原创短篇，作者授权用于平台公开游玩。")
service.submit(user["id"], revision["id"])
if os.environ.get("AUTHORING_FIXTURE_MANY_SAVES") == "1":
    first = preview.create(user["id"], revision["id"], "keeper", str(uuid.uuid4()))
    with connect() as db:
        db.execute("""insert into game_saves(user_id,script_id,title,state_path,state_snapshot,
                    player_story_id,player_story_snapshot,authoring_revision_id,updated_at)
            select g.user_id,g.script_id,'存档' || n,g.state_path,
                   jsonb_set(g.state_snapshot,'{player,name}',to_jsonb('角色' || n)),
                   g.player_story_id,g.player_story_snapshot,g.authoring_revision_id,now() - n * interval '1 second'
            from game_saves g cross join generate_series(1,50) n where g.id=%s""", (first["save_id"],))
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
