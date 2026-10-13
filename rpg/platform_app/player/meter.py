"""Request-scoped managed identity and per physical inference call accounting."""

from __future__ import annotations

import contextvars
import functools
import json
import logging
import threading
import uuid
from contextlib import contextmanager

from fastapi import HTTPException

from platform_app.db import connect

from .wallet import cost, lock_request

active_run = contextvars.ContextVar("player_run", default=None)
call_parent = contextvars.ContextVar("player_call", default=None)
phase_var = contextvars.ContextVar("player_phase", default="reply")
MAINTENANCE = {
    "extract",
    "extractor",
    "phase_digest",
    "summary",
    "anchor",
    "acceptance",
    "memory",
    "postproc",
    "episodic",
    "world_heartbeat",
    "recorder",
    "recorder_unified",
}


def current(uid=None):
    run = active_run.get()
    return run if run and (uid is None or int(uid) == run.uid) else None


def credential_owner(uid, api_id=None):
    run = current(uid)
    if run and (
        api_id is None
        or api_id == run.profile["api_id"]
        or api_id == "AgentPlatform"
        and run.profile["api_id"] == "vertex_ai"
    ):
        return int(run.profile["credential_owner_id"])
    return uid


@contextmanager
def phase(name):
    token = phase_var.set(name)
    try:
        yield
    finally:
        phase_var.reset(token)


def value(obj, key, default=0):
    return (
        obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
    ) or default


def normalize(usage, provider):
    if not usage:
        return None
    if provider == "vertex_ai":
        inp = int(value(usage, "prompt_token_count"))
        cached = int(value(usage, "cached_content_token_count"))
        reasoning = int(value(usage, "thoughts_token_count"))
        out = int(value(usage, "candidates_token_count")) + reasoning
    elif provider == "anthropic":
        cached = int(value(usage, "cache_read_input_tokens"))
        inp = (
            int(value(usage, "input_tokens"))
            + cached
            + int(value(usage, "cache_creation_input_tokens"))
        )
        out = int(value(usage, "output_tokens"))
        reasoning = 0
    else:
        inp = int(value(usage, "prompt_tokens", value(usage, "input_tokens")))
        out = int(value(usage, "completion_tokens", value(usage, "output_tokens")))
        cached = int(
            value(
                value(usage, "prompt_tokens_details", {}),
                "cached_tokens",
                value(usage, "cached_input_tokens"),
            )
        )
        reasoning = int(
            value(
                value(usage, "completion_tokens_details", {}),
                "reasoning_tokens",
                value(usage, "reasoning_tokens"),
            )
        )
        # OpenAI completion_tokens already includes reasoning.
    return dict(
        input_tokens=max(0, inp),
        output_tokens=max(0, out),
        cached_tokens=max(0, cached),
        reasoning_tokens=max(0, reasoning),
    )


def record_call(run, *args):
    group = call_parent.get()
    if group is not None:
        group.append(args)
    else:
        run.record(*args)


def has_output(event):
    """A usage-only or reasoning-only response is a failed attempt, not a reply."""
    if isinstance(event, str):
        return bool(event.strip())
    if (
        not event
        or value(event, "thought", False)
        or value(event, "type", "") in {"thinking", "thinking_delta", "redacted_thinking"}
    ):
        return False
    if (
        value(event, "tool_calls", [])
        or value(event, "function_call", None)
        or value(event, "type", "") == "tool_use"
    ):
        return True
    for key in (
        "text",
        "partial_json",
        "content",
        "delta",
        "message",
        "content_block",
        "choices",
        "candidates",
        "parts",
    ):
        item = value(event, key, None)
        if isinstance(item, list):
            if any(has_output(part) for part in item):
                return True
        elif item is not None and has_output(item):
            return True
    return False


class HTTPResponse:
    """Collect raw OpenAI-compatible microtask usage without reading prompts into the ledger."""

    def __init__(self, raw, run, model, cid):
        self.raw = raw
        self.run = run
        self.model = model
        self.id = cid
        self.body = b""
        self.finished = False

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def read(self, *args, **kwargs):
        chunk = self.raw.read(*args, **kwargs)
        self.body += chunk
        return chunk

    def __enter__(self):
        self.raw = self.raw.__enter__()
        return self

    def __exit__(self, typ, exc, tb):
        try:
            usage = None
            valid = False
            if not typ:
                try:
                    payload = json.loads(self.body)
                    usage = payload.get("usage")
                    message = (payload.get("choices") or [{}])[0].get("message") or {}
                    content = message.get("content") or ""
                    from core.json_parse import parse_llm_json

                    valid = (
                        bool(message.get("tool_calls"))
                        or parse_llm_json(content, allow_truncated=True) is not None
                    )
                except (ValueError, TypeError, AttributeError):
                    pass
            if not self.finished:
                self.finished = True
                record_call(
                    self.run,
                    self.id,
                    "openai",
                    self.model,
                    usage,
                    valid,
                    "provider_failure" if typ else "" if valid else "invalid_structured_reply",
                )
            return self.raw.__exit__(typ, exc, tb)
        finally:
            self.body = b""


def metered_urlopen(fn, req, **kwargs):
    run = current()
    if not run or getattr(run, "unbilled", False):
        return fn(req, **kwargs)
    payload = json.loads(req.data or b"{}")
    maximum = min(int(payload.get("max_tokens") or 1024), int(run.profile["max_output"]))
    payload["max_tokens"] = maximum
    payload["model"] = run.profile["model"]
    req.data = json.dumps(payload).encode("utf-8")
    run.admit(payload, maximum)
    cid = str(uuid.uuid4())
    try:
        raw = fn(req, **kwargs)
    except BaseException:
        record_call(run, cid, "openai", payload["model"], None, False, "provider_failure")
        raise
    return HTTPResponse(raw, run, payload["model"], cid)


class Run:
    def __init__(self, req):
        self.uid = int(req["user_id"])
        self.save_id = int(req["save_id"])
        self.id = str(req["id"])
        self.kind = req["kind"]
        self.profile = req["profile"]
        self.rates = req["rates"]
        self.cap = int(req["cap_micro"])
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.spent = 0
        self.recorded = set()
        self.gm = None
        self.partial = False
        self.receipt = None
        self.committing = False

    def admit(self, prompts, max_output):
        if phase_var.get() in MAINTENANCE:
            return
        if self.stop.is_set():
            raise HTTPException(409, "生成已停止")
        with connect() as db:
            lock_request(db, self.uid, self.id, self.save_id)
            service = db.execute(
                """select p.status,m.enabled from player_stories p join game_saves s on s.player_story_id=p.id
                                 join player_model_profiles m on m.id=%s where s.id=%s""",
                (self.profile["id"], self.save_id),
            ).fetchone()
            if not service or service["status"] == "suspended" or not service["enabled"]:
                raise HTTPException(503, "故事服务已停用")
        estimate = max(1, len(json.dumps(prompts, ensure_ascii=False, default=str)) // 2)
        with self.lock:
            if self.spent + cost(estimate, max_output, self.rates) > self.cap:
                raise HTTPException(402, "本轮预算已用尽，已保存内容可继续阅读")

    def record(self, call_id, provider, model, usage, success=True, reason=""):
        normalized = normalize(usage, provider)
        phase_name = phase_var.get()
        billable = bool(success and normalized and phase_name not in MAINTENANCE)
        if not normalized:
            reason = reason or "missing_usage"
            logging.getLogger(__name__).warning(
                "Player provider omitted usage request=%s call=%s", self.id, call_id
            )
        if phase_name in MAINTENANCE:
            reason = "platform_maintenance"
        n = normalized or dict(input_tokens=0, output_tokens=0, cached_tokens=0, reasoning_tokens=0)
        with self.lock:
            if call_id in self.recorded:
                return
            with connect() as db:
                db.execute(
                    """insert into player_llm_calls(id,request_id,phase,provider,model,input_tokens,output_tokens,cached_tokens,reasoning_tokens,billable,reason)
                              values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(id) do nothing""",
                    (
                        call_id,
                        self.id,
                        phase_name,
                        provider,
                        model,
                        n["input_tokens"],
                        n["output_tokens"],
                        n["cached_tokens"],
                        n["reasoning_tokens"],
                        billable,
                        reason,
                    ),
                )
            if billable:
                self.spent += cost(n["input_tokens"], n["output_tokens"], self.rates)
            self.recorded.add(call_id)


class Stream:
    def __init__(self, raw, run, provider, model, call_id):
        self.raw = raw
        self.run = run
        self.provider = provider
        self.model = model
        self.id = call_id
        self.usage = None
        self.finished = False
        self.failed = False
        self.has_output = False

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def observe(self, event):
        self.has_output = self.has_output or has_output(event)
        usage = value(event, "usage", None) or value(event, "usage_metadata", None)
        msg = value(event, "message", None)
        if msg:
            usage = value(msg, "usage", None) or usage
        if usage:
            if self.provider == "anthropic":
                old = self.usage or {}
                if hasattr(usage, "model_dump"):
                    usage = usage.model_dump(exclude_none=True)
                self.usage = {**old, **(usage if isinstance(usage, dict) else {})}
            else:
                self.usage = usage

    def finish(self):
        if not self.finished:
            self.finished = True
            record_call(
                self.run,
                self.id,
                self.provider,
                self.model,
                self.usage,
                not self.failed and self.has_output,
                "provider_failure" if self.failed else "" if self.has_output else "empty_reply",
            )

    def __iter__(self):
        try:
            for event in self.raw:
                self.observe(event)
                if self.run.stop.is_set() and phase_var.get() not in MAINTENANCE:
                    break
                yield event
        except GeneratorExit:
            raise
        except BaseException:
            self.failed = True
            raise
        finally:
            self.finish()

    def __enter__(self):
        self.raw = self.raw.__enter__()
        return self

    def __exit__(self, typ, exc, tb):
        self.failed = bool(typ)
        try:
            return self.raw.__exit__(typ, exc, tb)
        finally:
            self.finish()

    @property
    def text_stream(self):
        try:
            for text in self.raw.text_stream:
                self.has_output = self.has_output or has_output(text)
                if self.run.stop.is_set() and phase_var.get() not in MAINTENANCE:
                    break
                yield text
        except GeneratorExit:
            raise
        except BaseException:
            self.failed = True
            raise
        finally:
            try:
                self.observe(self.raw.get_final_message())
            except Exception:
                pass
            self.finish()

    def get_final_message(self):
        msg = self.raw.get_final_message()
        self.observe(msg)
        self.finish()
        return msg

    def close(self):
        try:
            self.raw.close()
        finally:
            self.finish()


class SDKProxy:
    """Wrap only inference methods. Metadata/catalog/cache operations stay platform costs."""

    def __init__(self, raw, provider, model, path=""):
        self.raw = raw
        self.provider = provider
        self.model = model
        self.path = path

    def __getattr__(self, name):
        attr = getattr(self.raw, name)
        path = (self.path + "." + name).lstrip(".")
        if path in {"chat", "chat.completions", "messages", "models"}:
            return SDKProxy(attr, self.provider, self.model, path)
        if path not in {
            "chat.completions.create",
            "messages.create",
            "messages.stream",
            "models.generate_content",
            "models.generate_content_stream",
        }:
            return attr

        def invoke(*args, **kw):
            run = current()
            if not run or getattr(run, "unbilled", False):
                return attr(*args, **kw)
            maximum = min(
                int(
                    kw.get("max_tokens")
                    or kw.get("max_completion_tokens")
                    or run.profile["max_output"]
                ),
                int(run.profile["max_output"]),
            )
            if "max_tokens" in kw:
                kw["max_tokens"] = maximum
            if "max_completion_tokens" in kw:
                kw["max_completion_tokens"] = maximum
            config = kw.get("config")
            if isinstance(config, dict):
                config["max_output_tokens"] = min(
                    int(config.get("max_output_tokens") or maximum), maximum
                )
            elif config is not None and hasattr(config, "max_output_tokens"):
                config.max_output_tokens = maximum
            run.admit(kw, maximum)
            cid = str(uuid.uuid4())
            call_model = kw.get("model") or self.model
            try:
                response = attr(*args, **kw)
            except BaseException:
                record_call(run, cid, self.provider, call_model, None, False, "provider_failure")
                raise
            if kw.get("stream") or name in {"stream", "generate_content_stream"}:
                return Stream(response, run, self.provider, call_model, cid)
            record_call(
                run,
                cid,
                self.provider,
                call_model,
                value(response, "usage", None) or value(response, "usage_metadata", None),
                has_output(response),
                "" if has_output(response) else "empty_reply",
            )
            return response

        return invoke


def wrap_sdk(client, provider, model):
    return SDKProxy(client, provider, model) if client is not None else None


def metered_agent(fn):
    @functools.wraps(fn)
    def invoke(api_id, model, system_prompt, user_prompt, user_id, **kw):
        run = current(user_id)
        if not run:
            return fn(api_id, model, system_prompt, user_prompt, user_id, **kw)
        api_id = run.profile["api_id"]
        model = run.profile["model"]
        if run.profile.get("tools_mode") == "none":
            kw["tool_schema"] = None
        if getattr(run, "unbilled", False):
            return fn(api_id, model, system_prompt, user_prompt, user_id, **kw)
        kw["max_tokens"] = min(int(kw.get("max_tokens") or 1024), int(run.profile["max_output"]))
        agent_phase = (
            phase_var.get()
            if phase_var.get() == "postproc"
            else kw.get("agent_kind") or phase_var.get()
        )
        with phase(agent_phase):
            run.admit([system_prompt, user_prompt], kw["max_tokens"])
            cid = str(uuid.uuid4())
            group = []
            token = call_parent.set(group)
            try:
                result = fn(api_id, model, system_prompt, user_prompt, user_id, **kw)
                text, usage = result
                from core.json_parse import parse_llm_json

                valid = parse_llm_json(text, allow_truncated=True) is not None
                # Harness usage is already normalized; do not add cache/reasoning twice.
                if api_id == "vertex_ai" and usage:
                    usage = {
                        **usage,
                        "output_tokens": int(usage.get("output_tokens") or 0)
                        + int(usage.get("reasoning_tokens") or 0),
                    }
                if group:
                    for call in group:
                        physical_id, provider, call_model, physical_usage, success, *reason = call
                        run.record(
                            physical_id,
                            provider,
                            call_model,
                            physical_usage,
                            success and valid,
                            (reason[0] if reason else "")
                            or ("" if valid else "invalid_structured_reply"),
                        )
                else:
                    run.record(
                        cid,
                        "normalized",
                        model,
                        usage,
                        valid,
                        "invalid_structured_reply" if not valid else "",
                    )
                return result
            except BaseException:
                if group:
                    for call in group:
                        run.record(*call[:4], False, "provider_failure")
                else:
                    run.record(cid, "normalized", model, None, False, "provider_failure")
                raise
            finally:
                call_parent.reset(token)

    return invoke


@contextmanager
def maintenance_context(uid, save_id):
    """Internal worker scope. Obtains managed credentials, never a player billing request."""
    from types import SimpleNamespace

    from .catalog import player_save, story

    try:
        save = player_save(int(uid), int(save_id))
        selected = story(save["player_story_id"])
    except HTTPException:
        yield None
        return
    service = SimpleNamespace(
        uid=int(uid), save_id=int(save_id), profile=selected["profile"], unbilled=True, gm=None
    )
    token = active_run.set(service)
    try:
        with phase("postproc"):
            yield service
    finally:
        active_run.reset(token)
