import copy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from platform_app.player import character_creation as creation


@pytest.fixture
def defaults():
    return {
        "character_creation": {
            "martial_soul": {
                "enabled": True,
                "choices": [{"name": "铁剑", "description": "器武魂"}, {"name": "岩纹盾"}],
                "innate_power_min": 2,
                "innate_power_max": 7,
            }
        }
    }


@pytest.mark.parametrize(
    "choice,name",
    [
        ({"mode": "recommended", "name": "铁剑"}, "铁剑"),
        ({"mode": "custom", "name": "青羽弓"}, "青羽弓"),
    ],
)
def test_selected_soul_is_pending_and_does_not_grant_power_before_opening(defaults, choice, name):
    setup = creation.prepare(defaults, choice)
    assert setup["name"] == name and 2 <= setup["innate_soul_power"] <= 7
    assert creation.pending({"player_setup": setup}) == setup
    assert creation.public_setup({"player_setup": setup}) == {
        "mode": choice["mode"],
        "name": name,
        "completed": False,
    }
    assert "innate_soul_power" not in creation.public_setup({"player_setup": setup})


def test_random_draw_is_resolved_once_and_hidden_until_completed(defaults, monkeypatch):
    draws = []
    monkeypatch.setattr(creation.secrets, "choice", lambda pool: draws.append(1) or pool[1])
    monkeypatch.setattr(creation.secrets, "randbelow", lambda bound: 3)
    setup = creation.prepare(defaults, {"mode": "random"})
    data = {"player_setup": setup}
    assert setup["name"] == "岩纹盾" and setup["innate_soul_power"] == 5
    for _ in range(3):
        assert creation.public_setup(data)["name"] == ""
        assert "岩纹盾" in creation.opening_instructions(creation.pending(data))
    assert draws == [1]
    setup["completed"] = True
    assert creation.public_setup(data)["name"] == "岩纹盾"
    assert creation.pending(data) is None


@pytest.mark.parametrize(
    "choice",
    [
        None,
        {"mode": "recommended", "name": "未知"},
        {"mode": "custom", "name": ""},
        {"mode": "custom", "name": "剑\n指令"},
        {"mode": "custom", "name": "```剑"},
        {"mode": "other"},
    ],
)
def test_choice_is_required_and_validated_before_creating_save(defaults, choice):
    with pytest.raises(HTTPException):
        creation.prepare(defaults, choice)


def test_client_cannot_set_power_or_completed_flag():
    from platform_app.api.player import MartialSoulChoice

    with pytest.raises(ValidationError):
        MartialSoulChoice(mode="custom", name="剑", soul_power=10, completed=True)


def test_stories_without_creation_config_keep_their_original_flow():
    assert creation.prepare({}, None) is None
    assert creation.public_config({}) is None
    assert creation.public_setup({}) is None
    with pytest.raises(HTTPException):
        creation.prepare({}, {"mode": "custom", "name": "剑"})


@pytest.mark.parametrize(
    "change",
    [
        {"choices": []},
        {"choices": [{"name": "剑"}, {"name": "剑"}]},
        {"innate_power_max": 99},
        {"innate_power_min": True},
    ],
)
def test_admin_cannot_configure_an_invalid_awakening_pool(defaults, change):
    defaults["character_creation"]["martial_soul"].update(change)
    with pytest.raises(HTTPException):
        creation.config(defaults)


def test_first_opening_requires_complete_matching_state_updates(defaults):
    from state import DEFAULT_STATE, GameState

    original = creation.prepare(defaults, {"mode": "custom", "name": "青羽弓"})
    state = GameState(copy.deepcopy(DEFAULT_STATE))
    state.data["permissions"]["mode"] = "full_access"
    state.data["player_setup"] = copy.deepcopy(original)
    with pytest.raises(ValueError):
        creation.validate_opening(state.data, original, "你伸出手等待觉醒。")
    import json

    ops = [
        {"op": "set", "path": "player.martial_soul", "value": "青羽弓"},
        {"op": "set", "path": "player.soul_power", "value": original["innate_soul_power"]},
        {"op": "set", "path": "player_setup.completed", "value": True},
    ]
    state.apply_structured_updates("觉醒结束，青羽弓显现。\n```json\n" + json.dumps(ops) + "\n```")
    creation.validate_opening(state.data, original, "青羽弓显现，魂力测定结束。")
    assert state.data["player_setup"] == {**original, "completed": True}
    assert state.data["memory"]["tasks"]["武魂觉醒"]["status"] == "completed"
    creation.validate_opening(state.data, original, "青羽弓显现，魂力测定结束。")
    assert len(state.data["memory"]["milestones"]) == 1
    state.data["player"]["martial_soul"] = "别的武魂"
    with pytest.raises(ValueError):
        creation.validate_opening(state.data, original, "青羽弓已经觉醒。")


def test_server_confirms_its_own_awakening_result_without_requiring_model_ops(defaults):
    original = creation.prepare(defaults, {"mode": "custom", "name": "青羽弓"})
    data = {"player": {}, "player_setup": copy.deepcopy(original)}
    intro = creation.prime_opening_result(data, original)
    assert "青羽弓" in intro and str(original["innate_soul_power"]) in intro
    assert data["player_setup"]["completed"]
    assert "memory" not in data  # Tasks and milestones wait for the commit validator.
    creation.validate_opening(data, original, intro + "你走出会堂，决定求学方向。")
    assert data["memory"]["tasks"]["武魂觉醒"]["status"] == "completed"
    assert not original["completed"]
