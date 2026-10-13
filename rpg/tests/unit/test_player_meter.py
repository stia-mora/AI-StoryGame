from types import SimpleNamespace as NS

from platform_app.player.meter import SDKProxy, Stream, active_run, normalize
from platform_app.player.wallet import DEFAULT_RATES, cost


def test_curator_thread_inherits_player_identity_credentials_and_meter(monkeypatch):
    from agents import _harness, context_agent
    from platform_app.player.meter import credential_owner, current, metered_agent, phase_var

    run = FakeRun()
    run.uid = 901
    run.profile.update(
        api_id="managed", model="managed-text", credential_owner_id=902, tools_mode="none"
    )
    observed = []

    def inference(api_id, model, system_prompt, user_prompt, user_id, **kw):
        observed.append(
            (
                current(user_id),
                credential_owner(user_id, api_id),
                phase_var.get(),
                kw.get("tool_schema"),
            )
        )
        assert (api_id, model) == ("managed", "managed-text")
        return '{"intent":"询问修炼方向"}', {"input_tokens": 103, "output_tokens": 17}

    monkeypatch.setattr(_harness, "call_agent_json", metered_agent(inference))
    monkeypatch.setattr(_harness, "resolve_api_and_model", lambda *a, **kw: ("old", "old-model"))
    token = active_run.set(run)
    try:
        result = context_agent._call_curator_via_harness(
            user_id=901,
            api_id_override=None,
            model_override=None,
            system_prompt="设定",
            user_prompt="行动",
            stop_requested=lambda: False,
        )
    finally:
        active_run.reset(token)
    assert "询问修炼方向" in result
    assert observed == [(run, 902, "curator", None)]
    assert len(run.records) == 1 and run.records[0][3]["input_tokens"] == 103


def test_provider_usage_does_not_double_bill_cache_or_reasoning():
    assert (
        normalize(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "prompt_tokens_details": {"cached_tokens": 700},
                "completion_tokens_details": {"reasoning_tokens": 300},
            },
            "openai",
        )["output_tokens"]
        == 500
    )
    a = normalize(
        {
            "input_tokens": 100,
            "output_tokens": 80,
            "cache_read_input_tokens": 50,
            "cache_creation_input_tokens": 20,
        },
        "anthropic",
    )
    assert a["input_tokens"] == 170
    v = normalize(
        {
            "prompt_token_count": 200,
            "candidates_token_count": 80,
            "thoughts_token_count": 20,
            "cached_content_token_count": 100,
        },
        "vertex_ai",
    )
    assert v["input_tokens"] == 200 and v["output_tokens"] == 100
    assert cost(1000, 500, DEFAULT_RATES) == 3_000_000
    assert normalize(None, "openai") is None


class FakeRun:
    def __init__(self):
        import threading

        self.stop = threading.Event()
        self.records = []
        self.admissions = []
        self.profile = {"max_output": 1024}

    def record(self, *args):
        self.records.append(args)

    def admit(self, *args):
        self.admissions.append(args)


def test_stream_cumulative_chunks_record_once_and_tool_loops_are_separate():
    run = FakeRun()
    for call in ["first", "second"]:
        s = Stream(
            iter(
                [
                    NS(
                        usage={"prompt_tokens": 20, "completion_tokens": 3},
                        choices=[NS(delta=NS(content="有效回复"))],
                    ),
                    NS(usage={"prompt_tokens": 20, "completion_tokens": 6}),
                ]
            ),
            run,
            "openai",
            "m",
            call,
        )
        assert len(list(s)) == 2
        s.finish()
    assert len(run.records) == 2
    assert all(record[3]["completion_tokens"] == 6 for record in run.records)
    assert all(record[4] for record in run.records)


def test_empty_attempt_is_platform_cost_before_a_successful_retry():
    run = FakeRun()
    empty = NS(
        usage={"prompt_tokens": 100, "completion_tokens": 12}, choices=[NS(delta=NS(content=""))]
    )
    valid = NS(
        usage={"prompt_tokens": 100, "completion_tokens": 30},
        choices=[NS(delta=NS(content="有效的回复。"))],
    )
    list(Stream(iter([empty]), run, "openai", "m", "failed-attempt"))
    list(Stream(iter([valid]), run, "openai", "m", "successful-attempt"))
    assert run.records[0][4:] == (False, "empty_reply")
    assert run.records[1][4] is True


def test_native_tool_call_and_anthropic_text_are_valid_stream_outputs():
    from platform_app.player.meter import has_output

    assert has_output(NS(choices=[NS(delta=NS(tool_calls=[NS(function=NS(name="查询现场"))]))]))
    assert has_output(
        NS(candidates=[NS(content=NS(parts=[NS(function_call=NS(name="查询现场"))]))])
    )
    assert not has_output(
        NS(candidates=[NS(content=NS(parts=[NS(thought=True, text="只有推理")]))])
    )
    run = FakeRun()
    raw = NS(
        text_stream=iter(["有效", "回复"]),
        get_final_message=lambda: NS(usage={"input_tokens": 100, "output_tokens": 10}, content=[]),
    )
    assert list(Stream(raw, run, "anthropic", "m", "text").text_stream) == ["有效", "回复"]
    assert run.records[0][4] is True


def test_failed_stream_never_billable_even_if_it_returned_usage():
    import pytest

    run = FakeRun()

    def chunks():
        yield NS(usage={"prompt_tokens": 20, "completion_tokens": 4})
        raise RuntimeError("upstream")

    with pytest.raises(RuntimeError):
        list(Stream(chunks(), run, "openai", "m", "call"))
    assert run.records[0][4] is False


def test_sdk_proxy_caps_output_and_checks_each_physical_call():
    run = FakeRun()
    seen = []

    def create(**kw):
        seen.append(kw)
        return NS(
            usage={"prompt_tokens": 20, "completion_tokens": 4},
            choices=[NS(message=NS(content="有效回复"))],
        )

    proxy = SDKProxy(NS(chat=NS(completions=NS(create=create))), "openai", "model")
    token = active_run.set(run)
    try:
        proxy.chat.completions.create(max_tokens=8000)
        proxy.chat.completions.create(max_tokens=20)
    finally:
        active_run.reset(token)
    assert seen[0]["max_tokens"] == 1024
    assert len(run.records) == len(run.admissions) == 2


def test_harness_records_each_physical_retry_without_double_counting():
    import io
    import json
    import urllib.request

    from platform_app.player.meter import metered_agent, metered_urlopen

    run = FakeRun()
    run.uid = 1
    run.profile.update(api_id="test", model="managed")

    @metered_agent
    def task(api_id, model, system_prompt, user_prompt, user_id, **kwargs):
        req = urllib.request.Request(
            "https://example.test/chat/completions", data=b'{"model":"other","max_tokens":5000}'
        )

        def failed(*args, **kw):
            raise RuntimeError("failed attempt")

        try:
            metered_urlopen(failed, req)
        except RuntimeError:
            pass
        payload = {
            "usage": {"prompt_tokens": 40, "completion_tokens": 8},
            "choices": [{"message": {"content": '{"ok":true}'}}],
        }
        with metered_urlopen(
            lambda *a, **kw: io.BytesIO(json.dumps(payload).encode()), req
        ) as response:
            json.loads(response.read())
        return '{"ok":true}', {"input_tokens": 40, "output_tokens": 8}

    token = active_run.set(run)
    try:
        task("other", "other", "system", "action", 1)
    finally:
        active_run.reset(token)
    assert len(run.records) == 2
    assert run.records[0][4] is False and run.records[1][4] is True
    assert run.records[1][2] == "managed"


def test_sdk_structured_invalid_reply_is_platform_cost():
    from platform_app.player.meter import metered_agent

    run = FakeRun()
    run.uid = 1
    run.profile.update(api_id="anthropic", model="managed")
    proxy = SDKProxy(
        NS(
            messages=NS(
                create=lambda **kw: NS(
                    usage={"input_tokens": 40, "output_tokens": 8},
                    content=[NS(type="text", text="unparseable reply")],
                )
            )
        ),
        "anthropic",
        "model",
    )

    @metered_agent
    def task(api_id, model, system_prompt, user_prompt, user_id, **kwargs):
        proxy.messages.create(model=model, max_tokens=kwargs["max_tokens"])
        return "unparseable reply", {"input_tokens": 40, "output_tokens": 8}

    token = active_run.set(run)
    try:
        task("other", "other", "system", "action", 1)
    finally:
        active_run.reset(token)
    assert len(run.records) == 1 and run.records[0][4] is False
    assert run.records[0][5] == "invalid_structured_reply"
