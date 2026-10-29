"""Authenticated creator tools over official MCP Streamable HTTP."""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit

from fastapi import HTTPException
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent
from pydantic import AnyHttpUrl

from . import oauth, service
from .contract import get_contract


class Verifier:
    async def verify_token(self, token):
        try:
            user = await asyncio.to_thread(oauth.verify_bearer, token, "authoring:read")
        except HTTPException:
            return None
        return AccessToken(token=token, client_id="creator-agent", subject=str(user["user"]["id"]),
            scopes=user["scopes"], resource=oauth.resource(), expires_at=user.get("expires_at"),
            claims=dict(uid=user["user"]["id"], credential=user["credential"]))


server = MCPServer("Story Between Authoring", version="1.0.0", token_verifier=Verifier(),
    instructions="先获取编制规范和原创样例。草稿归授权账号，上架需作者复核与管理员审批。",
    auth=AuthSettings(issuer_url=AnyHttpUrl(oauth.federation.official_base()),
        resource_server_url=AnyHttpUrl(oauth.resource()), required_scopes=["authoring:read"], validate_token_resource=True))


def principal(scope):
    token = get_access_token()
    if token is None or scope not in token.scopes:
        raise HTTPException(403, "缺少权限 " + scope)
    return dict(id=int(token.subject), _credential=token.claims["credential"])


def result(value, error=False):
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False, default=str))],
                          structured_content=value, is_error=error)


async def call(scope, function, **kwargs):
    try:
        user = principal("authoring:" + scope)
        if function is service.import_draft:
            kwargs["credential"] = user["_credential"]
        return result(await asyncio.to_thread(function, user["id"], **kwargs))
    except (HTTPException, ValueError, TypeError, KeyError) as exc:
        return result(dict(code=f"E_{exc.status_code}" if isinstance(exc, HTTPException) else "E_INPUT",
                           message=str(exc.detail if isinstance(exc, HTTPException) else exc)[:500]), True)


@server.tool()
async def authoring_get_contract(section: str = "summary") -> CallToolResult:
    """获取规范；section=summary/schemas/example，样例包含原创完整包的各文件。"""
    principal("authoring:read")
    return result(get_contract(section))


@server.tool()
async def authoring_create_project(project_key: str, title: str) -> CallToolResult:
    """幂等创建本人的私人项目；同账号相同project_key返回原项目。"""
    return await call("write", service.create_project, project_key=project_key, title=title)


@server.tool()
async def authoring_begin_upload(project_id: str, size: int, sha256: str) -> CallToolResult:
    """申请专属ZIP上传引用，最多50MiB，支持HTTP或128KiB MCP分片。"""
    return await call("write", service.begin_upload, project_id=project_id, size=size, sha256=sha256)


@server.tool()
async def authoring_upload_chunk(upload_id: str, part: int, data: str) -> CallToolResult:
    """Base64分片，part从0连续编号，每片解码后最多128KiB；相同分片可重试。"""
    return await call("write", service.upload_chunk, upload_id=upload_id, part=part, data=data)


@server.tool()
async def authoring_complete_upload(upload_id: str) -> CallToolResult:
    """验证大小和SHA256并锁定上传内容，重复完成安全。"""
    return await call("write", service.complete_upload, upload_id=upload_id)


@server.tool()
async def authoring_validate_package(upload_id: str) -> CallToolResult:
    """只校验不导入，返回字段路径、阻断错误、警告、缺项和检查覆盖。"""
    return await call("write", service.validate_package, upload_id=upload_id)


@server.tool()
async def authoring_import_draft(project_id: str, upload_id: str, expected_version: int) -> CallToolResult:
    """导入不可变私人版本并返回job_id；相同内容复用，过期版本或并行修订返回冲突。"""
    return await call("write", service.import_draft, project_id=project_id, upload_id=upload_id, expected_version=expected_version)


@server.tool()
async def authoring_get_job(job_id: str) -> CallToolResult:
    """读取本人导入或试玩任务状态、结果与错误；断线后可恢复查询。"""
    return await call("read", service.get_job, job_id=job_id)


@server.tool()
async def authoring_get_draft(project_id: str, version: int | None = None) -> CallToolResult:
    """读取本人版本、校验、待办、提交状态与已有试玩存档；指定版本时返回对应版本的浏览器复核链接。"""
    return await call("read", service.get_draft, project_id=project_id, version=version)


@server.tool()
async def authoring_preview(mode: str, data: dict) -> CallToolResult:
    """create需revision_id/identity_id/request_id(UUID)/name；quote需revision_id/save_id/kind(opening|turn|guide)/message；execute另需quote_id/request_id/cap_micro，使用专用试玩余额。"""
    try:
        user = principal("authoring:preview")
        from .api import preview_action
        return result(await preview_action(user, dict(data, mode=mode)))
    except (HTTPException, ValueError, TypeError, KeyError) as exc:
        return result(dict(code=f"E_{exc.status_code}" if isinstance(exc, HTTPException) else "E_INPUT",
                           message=str(exc.detail if isinstance(exc, HTTPException) else exc)[:500]), True)


@server.tool()
async def authoring_submit(revision_id: int) -> CallToolResult:
    """将已由作者在网页复核的指定版本送入待审；不直接公开或上架。"""
    return await call("submit", service.submit, revision_id=revision_id)


base = urlsplit(oauth.federation.official_base())
http_app = server.streamable_http_app(streamable_http_path="/authoring", stateless_http=True,
    transport_security=TransportSecuritySettings(allowed_hosts=[base.netloc, "127.0.0.1:*", "localhost:*", "testserver"],
        allowed_origins=[f"{base.scheme}://{base.netloc}", "http://127.0.0.1:*", "http://localhost:*"]))
