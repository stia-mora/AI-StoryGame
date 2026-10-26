"""Story comment access, pagination and persistence with real PostgreSQL; no providers."""
# ruff: noqa: F811
import uuid

import pytest
from fastapi.testclient import TestClient

import app
from platform_app import auth
from platform_app.db import connect
from tests.integration.test_player_credits import player  # noqa: F401


@pytest.fixture
def clients(player, monkeypatch):
    monkeypatch.setenv('RPG_DEPLOYMENT_MODE', 'server')
    monkeypatch.setenv('RPG_REQUIRE_AUTH', '1')
    monkeypatch.setattr('redis_bus.get_sync_client', lambda: None)
    extra = []
    people = [player['user']]
    with connect() as db:
        for role in ['user', 'admin']:
            row = db.execute('''insert into users(username,password_hash,display_name,role,email_verified)
                values(%s,'','其他玩家',%s,true) returning *''',
                ('comment_test_' + uuid.uuid4().hex, role)).fetchone()
            people.append(row)
            extra.append(row['id'])
        result = [TestClient(app.app)]
        for person in people:
            client = TestClient(app.app)
            client.cookies.set('rpg_session', auth._issue_session(db, person['id']))
            result.append(client)
    yield result
    with connect() as db:
        db.execute('delete from users where id=any(%s)', (extra,))


def path(player):
    return f"/api/player/stories/{player['story']}/comments"


def test_guests_read_plain_comments_but_cannot_write_or_delete(player, clients):
    guest, author, _, _ = clients
    url = path(player)
    assert guest.get(url).json() == {'items': [], 'next_cursor': None}
    text = '<script>alert(1)</script>\n这段剧情很有意思。'
    posted = author.post(url, json={'content': text})
    assert posted.status_code == 200
    item = posted.json()
    assert set(item) == {'id', 'author', 'content', 'created_at', 'can_delete'}
    assert item['content'] == text and item['can_delete']
    public = guest.get(url).json()['items'][0]
    assert public == {**item, 'can_delete': False}
    assert guest.post(url, json={'content': '不能匿名发布'}).status_code == 401
    assert guest.post(f"{url}/{item['id']}/delete", json={}).status_code == 401


def test_only_author_and_admin_can_delete_and_state_is_untouched(player, clients):
    guest, author, stranger, admin = clients
    url = path(player)
    with connect() as db:
        before = db.execute('select active_commit_id,state_snapshot from game_saves where id=%s', (player['sid'],)).fetchone()
    item = author.post(url, json={'content': '  很喜欢这位人物。  '}).json()
    assert item['content'] == '很喜欢这位人物。'
    assert not stranger.get(url).json()['items'][0]['can_delete']
    assert admin.get(url).json()['items'][0]['can_delete']
    delete = f"{url}/{item['id']}/delete"
    assert stranger.post(delete, json={}).status_code == 403
    assert author.post(delete, json={}).json() == {'ok': True}
    assert author.post(delete, json={}).status_code == 404
    other = stranger.post(url, json={'content': '管理员可管理公开评论'}).json()
    assert admin.post(f"{url}/{other['id']}/delete", json={}).status_code == 200
    assert not guest.get(url).json()['items']
    with connect() as db:
        after = db.execute('select active_commit_id,state_snapshot from game_saves where id=%s', (player['sid'],)).fetchone()
        assert before == after
        assert not db.execute('select id from player_requests where user_id=%s', (player['uid'],)).fetchall()


@pytest.mark.parametrize('content', ['', ' \n\t', '字' * 2001, None])
def test_rejects_empty_and_oversized_comments(player, clients, content):
    assert clients[1].post(path(player), json={'content': content}).status_code == 422


@pytest.mark.parametrize('status,enabled', [('unlisted', True), ('suspended', True), ('published', False)])
def test_non_public_stories_hide_comments_and_reject_writes(player, clients, status, enabled):
    url = path(player)
    item = clients[1].post(url, json={'content': '下架前的评论'}).json()
    with connect() as db:
        db.execute('update player_stories set status=%s where id=%s', (status, player['story']))
        db.execute('update player_model_profiles set enabled=%s where id=%s', (enabled, player['profile']['id']))
    assert clients[0].get(url).status_code == 404
    assert clients[1].post(url, json={'content': '不可发布'}).status_code == 404
    assert clients[1].post(f"{url}/{item['id']}/delete", json={}).status_code == 404


def test_cursor_pagination_is_bounded_and_no_rows_cross_stories(player, clients):
    with connect() as db:
        ids = [db.execute('insert into player_story_comments(story_id,user_id,content) values(%s,%s,%s) returning id',
                          (player['story'], player['uid'], f'第{n}条')).fetchone()['id'] for n in range(23)]
        script = db.execute("insert into scripts(owner_id,title) values(%s,'另一故事') returning id", (player['uid'],)).fetchone()['id']
        story = db.execute("insert into player_stories(script_id,profile_id,title,status) values(%s,%s,'另一故事','published') returning id",
                           (script, player['profile']['id'])).fetchone()['id']
    try:
        url = path(player)
        seen, cursor = [], None
        for _ in range(4):
            page = clients[0].get(url, params={'limit': 7, **({'before': cursor} if cursor else {})}).json()
            assert len(page['items']) <= 7
            seen += [i['id'] for i in page['items']]
            cursor = page['next_cursor']
        assert seen == sorted(ids, reverse=True) and cursor is None
        assert clients[0].get(f'/api/player/stories/{story}/comments').json()['items'] == []
        assert clients[3].post(f'/api/player/stories/{story}/comments/{ids[0]}/delete', json={}).status_code == 404
        assert clients[0].get(url, params={'limit': 100}).status_code == 422
        assert clients[0].get(url, params={'before': -1}).status_code == 422
    finally:
        with connect() as db:
            db.execute('delete from player_stories where id=%s', (story,))
            db.execute('delete from scripts where id=%s', (script,))


def test_post_limit_is_enforced_per_account(player, clients):
    for n in range(5):
        assert clients[1].post(path(player), json={'content': str(n)}).status_code == 200
    denied = clients[1].post(path(player), json={'content': '太快了'})
    assert denied.status_code == 429 and denied.headers['retry-after'] == '60'
    assert clients[2].post(path(player), json={'content': '另一位玩家不受影响'}).status_code == 200
