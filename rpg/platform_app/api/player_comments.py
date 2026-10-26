"""Public story discussions, isolated from saves, prompts and player billing."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from core.request_limits import rate_allowed
from platform_app.db import connect

from ._deps import current_user
from .player import require_player

router = APIRouter(prefix='/api/player/stories')


class Comment(BaseModel):
    content: str = Field(min_length=1, max_length=2000)

    @field_validator('content')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('评论不能为空')
        return value.strip()


def _published(db, story_id):
    row = db.execute('''select p.id from player_stories p
        join player_model_profiles m on m.id=p.profile_id
        where p.id=%s and p.status='published' and m.enabled''', (story_id,)).fetchone()
    if not row:
        raise HTTPException(404, '故事暂未上架')


def _item(row, author, can_delete):
    return dict(id=row['id'], author=author, content=row['content'],
                created_at=row['created_at'].isoformat(), can_delete=bool(can_delete))


@router.get('/{story_id}/comments')
def list_comments(story_id: int, before: int | None = Query(default=None, ge=1),
                  limit: int = Query(default=20, ge=1, le=50), user=Depends(current_user)):
    with connect() as db:
        _published(db, story_id)
        rows = db.execute('''select c.id,c.content,c.created_at,c.user_id,
            coalesce(nullif(u.display_name,''),u.username) as author
            from player_story_comments c join users u on u.id=c.user_id
            where c.story_id=%s and (%s::bigint is null or c.id<%s)
            order by c.id desc limit %s''', (story_id, before, before, limit + 1)).fetchall()
    items = [_item(r, r['author'], user and (user['id']==r['user_id'] or user.get('role')=='admin'))
             for r in rows[:limit]]
    return dict(items=items, next_cursor=items[-1]['id'] if len(rows)>limit else None)


@router.post('/{story_id}/comments')
def post_comment(story_id: int, body: Comment, user=Depends(require_player)):
    with connect() as db:
        _published(db, story_id)
        if not rate_allowed(f"story-comment:{user['id']}", 5):
            raise HTTPException(429, '评论过于频繁，请稍后再试', headers={'Retry-After': '60'})
        row = db.execute('''insert into player_story_comments(story_id,user_id,content)
            values(%s,%s,%s) returning id,content,created_at''',
            (story_id, user['id'], body.content)).fetchone()
    return _item(row, user.get('display_name') or user['username'], True)


@router.post('/{story_id}/comments/{comment_id}/delete')
def delete_comment(story_id: int, comment_id: int, user=Depends(require_player)):
    with connect() as db:
        _published(db, story_id)
        row = db.execute('''select user_id from player_story_comments
            where id=%s and story_id=%s for update''', (comment_id, story_id)).fetchone()
        if not row:
            raise HTTPException(404, '评论不存在或已删除')
        if row['user_id'] != user['id'] and user.get('role') != 'admin':
            raise HTTPException(403, '只能删除自己的评论')
        db.execute('delete from player_story_comments where id=%s', (comment_id,))
    return {'ok': True}
