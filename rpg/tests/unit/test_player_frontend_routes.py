"""Player entry routing against temporary HTML shells; no database or lifespan."""
import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Mount

import app
from routes.core import index


@pytest.fixture
def frontend(tmp_path):
    (tmp_path / "index.html").write_text("<html>official website</html>", encoding="utf-8")
    (tmp_path / "Player.html").write_text("<html>player shell</html>", encoding="utf-8")
    (tmp_path / "Platform.html").write_text("<html>creator shell</html>", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("mode", ["local", "server"])
def test_homepage_uses_official_website_in_all_deployment_modes(frontend, monkeypatch, mode):
    monkeypatch.setenv("RPG_DEPLOYMENT_MODE", mode)
    monkeypatch.setattr(app, "_FRONTEND_DIR", frontend)
    monkeypatch.setattr(app, "_FRONTEND_HAS_DIST", True)
    web = FastAPI()
    web.add_api_route("/", index)
    with TestClient(web) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.text == "<html>official website</html>"
    assert response.headers["Cache-Control"] == "no-cache, must-revalidate"


@pytest.mark.parametrize("path", ["/", "/index.html"])
def test_static_homepage_keeps_the_official_website_separate_from_play(frontend, path):
    web = Starlette(routes=[Mount("/", app=app._SPAStaticFiles(directory=str(frontend), html=True))])
    with TestClient(web) as client:
        response = client.get(path)
    assert response.text == "<html>official website</html>"
    assert response.headers["Cache-Control"] == "no-cache, must-revalidate"


@pytest.mark.parametrize("path", ["/play", "/play/login", "/play/register", "/play/saves/42"])
def test_player_deep_links_use_player_shell(frontend, path):
    web = Starlette(routes=[Mount("/", app=app._SPAStaticFiles(directory=str(frontend), html=True))])
    with TestClient(web) as client:
        response = client.get(path)
    assert response.status_code == 200
    assert response.text == "<html>player shell</html>"


@pytest.mark.parametrize("path", ["play\\login", "play\\register", "play\\saves\\42"])
def test_windows_static_paths_use_player_shell_on_any_host(frontend, path):
    static = app._SPAStaticFiles(directory=str(frontend), html=True)
    response = asyncio.run(static.get_response(path, {"type": "http", "method": "GET", "headers": []}))
    assert Path(response.path).name == "Player.html"


@pytest.mark.parametrize("path", ["/Platform.html", "/settings"])
def test_creator_addresses_remain_accessible(frontend, path):
    web = Starlette(routes=[Mount("/", app=app._SPAStaticFiles(directory=str(frontend), html=True))])
    with TestClient(web) as client:
        assert client.get(path).text == "<html>creator shell</html>"


@pytest.mark.parametrize("path", ["/assets/missing.js", "/api/missing"])
def test_missing_resources_do_not_receive_an_html_shell(frontend, path):
    web = Starlette(routes=[Mount("/", app=app._SPAStaticFiles(directory=str(frontend), html=True))])
    with TestClient(web) as client:
        assert client.get(path).status_code == 404
