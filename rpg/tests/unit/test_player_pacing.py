import pytest

from platform_app.player.pacing import FAST_PREFIX, context, instructions


@pytest.mark.parametrize("transport", ["callback", "harness"])
@pytest.mark.parametrize("explicit_jump", [False, True])
def test_managed_fast_actions_do_not_turn_into_paid_time_confirmations(
    monkeypatch, transport, explicit_jump
):
    import copy
    import json
    from types import SimpleNamespace

    from agents import context_agent
    from platform_app.player.meter import active_run
    from state import DEFAULT_STATE, GameState

    state = GameState(copy.deepcopy(DEFAULT_STATE))
    state.update_time("觉醒日清晨", source="player_set")
    plan = json.dumps({"timeline_target": "次日清晨", "intent": "办理推荐"}, ensure_ascii=False)
    monkeypatch.setattr(context_agent, "_call_curator_via_harness", lambda **kwargs: plan)
    monkeypatch.setattr(context_agent, "resolve_content_pack", lambda *args, **kwargs: {})
    monkeypatch.setattr(context_agent, "run_providers", lambda *args: ([], []))
    monkeypatch.setattr(
        context_agent, "build_context_bundle", lambda *args, **kwargs: {"debug": {}}
    )
    message = "时间推进到次日清晨" if explicit_jump else FAST_PREFIX + "去找村长办理推荐信"
    run_token = active_run.set(SimpleNamespace(uid=3))
    try:
        result = list(
            context_agent.run_context_agent(
                state,
                message,
                user_id=3,
                llm_curator=(lambda *args: plan) if transport == "callback" else None,
            )
        )[-1]
    finally:
        active_run.reset(run_token)
    pending = state.data["world"]["timeline"].get("pending_jump")
    if explicit_jump:
        assert pending["to"] == "次日清晨"
    else:
        assert not pending
        assert result["curator_plan"]["timeline_target"] == ""


def test_old_fast_confirmation_is_cleared_only_when_no_time_change_was_requested():
    import copy

    from platform_app.player.pacing import clear_spurious_jump
    from state import DEFAULT_STATE, GameState

    state = GameState(copy.deepcopy(DEFAULT_STATE))
    state.update_time("觉醒日清晨", source="player_set")
    state.request_time_jump("觉醒日清晨", FAST_PREFIX + "去找村长办理推荐信")
    clear_spurious_jump(state)
    assert not state.data["world"]["timeline"]["pending_jump"]
    state.request_time_jump("觉醒日清晨·村长处的下一处关键抉择", FAST_PREFIX + "去找村长办理推荐信")
    clear_spurious_jump(state)
    assert not state.data["world"]["timeline"]["pending_jump"]
    state.request_time_jump("次日清晨", FAST_PREFIX + "时间推进到次日清晨")
    clear_spurious_jump(state)
    assert state.data["world"]["timeline"]["pending_jump"]["to"] == "次日清晨"


def test_stall_uses_committed_progress_not_writing_length_or_elapsed_time():
    view = {
        "status": {"location": "村长家"},
        "journey": [
            {"changes": [{"kind": "地点", "after": "村长家"}], "gains": []},
            {"changes": [{"kind": "时间", "after": "中午"}], "gains": []},
            {"changes": [], "gains": []},
        ],
    }
    assert context(view, "向村长询问") == {"quiet_turns": 2, "location": "村长家", "fast": False}
    view["journey"][-1]["gains"] = [{"kind": "物品", "text": "推荐信"}]
    assert context(view, "出发")["quiet_turns"] == 0


def test_only_explicit_fast_mode_authorizes_merging_steps():
    from types import SimpleNamespace

    view = {"status": {}, "journey": []}
    assert not context(view, "他提到快进至下一处关键抉择")["fast"]
    signal = context(view, FAST_PREFIX + "与村长办完手续后出发")
    assert signal["fast"]
    guide = instructions(SimpleNamespace(pacing=signal))
    assert "玩家已选择快进" in guide
    assert "重大风险或机缘须立即停下" in guide


@pytest.mark.parametrize(
    "managed,tasks,expects_guide",
    [
        (True, ["ops"], True),
        (False, ["ops"], False),
        (True, ["anchors"], False),
    ],
)
def test_item_recording_instructions_only_reach_managed_state_extraction(
    monkeypatch, managed, tasks, expects_guide
):
    from agents import recorder
    from platform_app.player import meter
    from platform_app.player.pacing import RECORDING_GUIDE

    seen = []
    monkeypatch.setattr(meter, "current", lambda uid: object() if managed else None)
    monkeypatch.setattr(
        recorder, "_resolve_recorder_api_and_model", lambda *args: ("stub", "model")
    )
    monkeypatch.setattr(
        recorder,
        "_call_recorder",
        lambda **kwargs: seen.append(kwargs["system_prompt"]) or ('{"ops":[]}', {}),
    )
    recorder.record_turn("老师实际交付课表；奖励还未领取。", {}, user_id=1, tasks=tasks)
    assert (RECORDING_GUIDE in seen[0]) == expects_guide
