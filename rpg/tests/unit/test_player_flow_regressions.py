"""Behavioral regressions for the nine player-test findings. No live saves or LLM calls."""
from __future__ import annotations

import asyncio
import copy
import json

import pytest

from rules_bridge import start_module
from rules_bridge.checks import perform_room_check, resolve_room_check
from rules_bridge.combat import enemy_attack, player_attack, start_encounter_by_id, turn_token
from rules_bridge.consume import consume_item_action
from rules_bridge.module_ops import enter_room
from rules_bridge.suggest import suggest_rule_actions
from state import DEFAULT_STATE, GameState


@pytest.fixture
def game(monkeypatch):
    game = GameState(copy.deepcopy(DEFAULT_STATE))
    start_module(game, "ash_mine")
    monkeypatch.setattr(game, "save", lambda: None)
    return game


def place(game, location):
    from rules_bridge.checks import room_definition
    from rules_bridge.module_ops import _room_snapshot
    game.data["scene"]["location_id"] = location
    game.data["scene"]["current_room"] = _room_snapshot(room_definition(game))


def test_failed_poison_check_uses_server_effects_and_syncs_log(game):
    import app
    place(game, "fissure")
    pc = game.data["player_character"]
    pc["hp"] = pc["max_hp"] = 30
    pc["abilities"]["con"] = 1
    # External seed policy is patched only here to make the failing save reproducible.
    from unittest.mock import patch
    with patch.object(app, "_coerce_rule_seed", lambda seed: seed):
        out = app._execute_rules_action(game, {"kind": "saving_throw", "check_id": "check_0",
                                               "dc": 1, "fail_damage": "0", "seed": 2})
    assert out["ok"] and not out["result"]["success"]
    assert pc["hp"] < 30 and "coughing" in pc["conditions"]
    assert game.data["dice_log"][-1]["damage_applied"] == 30 - pc["hp"]


def test_dangerous_exit_cannot_bypass_save_but_safe_exit_does_not_roll(game):
    place(game, "shaft_lift")
    pc = game.data["player_character"]
    pc["hp"] = pc["max_hp"] = 30
    pc["abilities"]["dex"] = 1
    out = enter_room(game, "rest_cavern", seed=2)
    assert out["ok"] and len(out["hazard_results"]) == 1
    assert pc["hp"] < 30 and len(game.data["dice_log"]) == 1
    place(game, "shaft_lift")
    enter_room(game, "mine_entrance")
    assert len(game.data["dice_log"]) == 1


def test_poison_route_and_disabled_trap(game):
    place(game, "fissure")
    game.data["player_character"]["hp"] = 30
    game.data["player_character"]["abilities"]["con"] = 1
    out = enter_room(game, "ash_camp", seed=2)
    assert out["hazard_results"][0]["result"]["damage_applied"] > 0
    assert "coughing" in game.data["player_character"]["conditions"]
    import app
    prompt = app._rule_results_prompt([{"action": {"kind": "move"}, "out": out}], game)
    assert "失败" in prompt and "伤害" in prompt and "coughing" in prompt
    place(game, "altar_approach")
    game.set_scene_flag("needle_trap_disabled", True)
    assert enter_room(game, "mine_heart_altar")["hazard_results"] == []


def test_poison_condition_disadvantages_next_action_then_expires(game):
    from rules_bridge.checks import perform_skill_check
    place(game, "fissure")
    game.data["player_character"]["hp"] = 30
    game.data["player_character"]["abilities"]["con"] = 1
    enter_room(game, "ash_camp", seed=2)
    assert "coughing" in game.data["player_character"]["conditions"]
    before = copy.deepcopy(game.data)
    assert not consume_item_action(game, "missing_item")["ok"]
    assert game.data == before  # A rejected action cannot spend the condition's duration.
    out = perform_skill_check(game, "stealth", 14, seed=2)
    assert out["roll"]["disadvantage"]
    assert "coughing" not in game.data["player_character"]["conditions"]
    assert not perform_skill_check(game, "stealth", 14, seed=2)["roll"]["disadvantage"]


def test_legacy_poison_condition_acquires_duration_and_expires(game):
    from rules_bridge.checks import perform_skill_check
    game.data["player_character"]["conditions"] = ["coughing"]
    game.status_payload()
    assert game.data["player_character"]["condition_effects"]["coughing"]["duration_actions"] == 1
    assert perform_skill_check(game, "stealth", 14, seed=2)["roll"]["disadvantage"]
    assert "coughing" not in game.data["player_character"]["conditions"]


def test_defeated_player_stays_at_zero_hp_after_reload_and_cannot_restart_combat(game):
    game.data["player_character"]["hp"] = 0
    loaded = GameState(copy.deepcopy(game.data))
    assert loaded.data["player_character"]["hp"] == 0
    before = copy.deepcopy(loaded.data)
    assert not start_encounter_by_id(loaded, "ash_camp_combat")["ok"]
    assert loaded.data == before
    # Missing health in a legacy save still receives the documented default.
    legacy = copy.deepcopy(game.data)
    legacy["player_character"].pop("hp")
    assert GameState(legacy).data["player_character"]["hp"] == legacy["player_character"]["max_hp"]


def test_potion_heals_consumes_syncs_and_rejects_full_hp_and_empty_stock(game):
    pc = game.data["player_character"]
    before = copy.deepcopy(game.data)
    assert not consume_item_action(game, "healing_draught")["ok"]
    assert game.data == before
    pc["hp"] = 1
    out = consume_item_action(game, "药剂", seed=3)
    assert out["ok"] and pc["hp"] > 1 and pc["hp"] <= pc["max_hp"]
    assert out["result"]["extra"]["healed"] == pc["hp"] - 1
    assert all(i["id"] != "healing_draught" for i in pc["inventory"])
    assert all("Healing Draught" not in r for r in game.data["memory"]["resources"])
    after = copy.deepcopy(game.data)
    assert not consume_item_action(game, "healing_draught")["ok"]
    assert game.data == after


def test_attack_turn_budget_stale_request_and_automatic_enemies(game):
    place(game, "ash_camp")
    pc = game.data["player_character"]
    pc["hp"] = pc["max_hp"] = 100
    start_encounter_by_id(game, "ash_camp_combat", seed=1)
    enc = game.data["encounter"]
    assert enc["initiative_order"][enc["turn_index"]]["id"] == "player"
    token = turn_token(enc)
    log_len = len(game.data["dice_log"])
    out = player_attack(game, "ash_skulker_1", seed=2, expected_turn=token)
    assert out["ok"] and out["enemy_actions"]
    assert len(game.data["dice_log"]) > log_len + 1
    snapshot = copy.deepcopy(game.data)
    assert not player_attack(game, "ash_skulker_1", expected_turn=token)["ok"]
    assert not enemy_attack(game, "ash_skulker_1")["ok"]
    assert game.data == snapshot
    enc["turn_index"] = next(i for i, o in enumerate(enc["initiative_order"]) if o["id"] != "player")
    assert not player_attack(game, "ash_skulker_2")["ok"]


def test_combat_repairs_legacy_npc_aliases_and_defeated_presence(game):
    place(game, "ash_camp")
    game.data["player_character"]["hp"] = 100
    game.data["active_entities"] = [{"id": "ash_acolyte_1", "name": "旧教徒", "source": "room_data"}]
    start_encounter_by_id(game, "ash_camp_combat", seed=1)
    entities = game.status_payload()["active_entities"]
    assert len(entities) == 3 and len({e["id"] for e in entities}) == 3
    assert all(e["disposition"] == "hostile" for e in entities)
    foe = next(c for c in game.data["encounter"]["combatants"] if c["id"] == "ash_skulker_1")
    foe.update(hp=0, defeated=True)
    entities = game.status_payload()["active_entities"]
    assert next(e for e in entities if e["id"] == foe["id"])["status"] == "defeated"
    game.data["encounter"] = {}
    game.set_scene_flag("ash_camp_cleared", True)
    place(game, "deep_hall")
    start_encounter_by_id(game, "deep_hall_combat", seed=1)
    game.data["encounter"]["active"] = False
    place(game, "ash_camp")
    assert all(e["status"] == "defeated" for e in game.status_payload()["active_entities"])
    assert not start_encounter_by_id(game, "ash_camp_combat")["ok"]


@pytest.mark.parametrize("text", [
    "刚才的调查检定已成功，请告诉我发现什么，暂时不移动", "不要攻击，也不要喝药剂",
    "调查成功了吗？", "如何使用短弓？", "观察会不会触发检定？", "这是不是反射光？",
    "我可以攻击他？", "攻击有什么后果？", "调查成功了没？", "我并没有攻击他",
])
def test_review_questions_and_negations_never_execute(game, text):
    import app
    assert suggest_rule_actions(text, game) == []
    assert app._chat_rule_candidates(game, text, [{"kind": "attack"}]) == []


def test_mixed_negation_retains_only_requested_action(game):
    import app
    actions = app._chat_rule_candidates(game, "不要攻击，我调查脚印", [{"kind": "attack"}])
    assert [a["kind"] for a in actions] == ["skill_check"]


def test_hidden_fact_only_unlocks_on_success_and_never_becomes_dice_reason(game):
    place(game, "rest_cavern")
    pc = game.data["player_character"]
    pc["abilities"]["int"] = 1
    check = resolve_room_check(game, {"check_id": "check_0"})
    out = perform_room_check(game, check, seed=2)
    assert not out["result"]["success"]
    assert "草图" not in json.dumps(game.status_payload(), ensure_ascii=False)
    pc["abilities"]["int"] = 40
    out = perform_room_check(game, check, seed=2)
    assert out["result"]["success"] and "草图" in "".join(out["result"]["gm_facts"])
    assert game.data["scene"]["flags"]["journal_secret"]
    assert "草图" not in game.data["dice_log"][-1]["reason"]


def test_branch_gm_anchor_and_delete_round_with_opening_and_receipts():
    from platform_app.branches.tree_ops import message_fork_turn
    assert [message_fork_turn(i, 1) for i in range(5)] == [0, 0, 1, 1, 2]
    assert [message_fork_turn(i, 0) for i in range(4)] == [0, 1, 1, 2]
    history = [{"role": r} for r in ["assistant", "user", "assistant", "assistant", "user", "assistant"]]
    assert message_fork_turn(5, 1, history, 2) == 2
    assert message_fork_turn(4, 1, history, 2) == 1
    assert message_fork_turn(5, 1, history, 2, delete_round=True) == 1


def test_text_model_capability_guard_keeps_image_roles_separate(monkeypatch):
    import model_registry
    from core import llm_backend as backend
    catalog = {"apis": [{"id": "test", "models": [
        {"real_name": "image-only", "capabilities": ["image_gen"]},
        {"real_name": "text-model", "capabilities": ["text", "streaming"]},
        {"real_name": "embedding-only", "capabilities": ["embedding"]},
    ]}]}
    monkeypatch.setattr(model_registry, "load_catalog_for_user", lambda uid: catalog)
    monkeypatch.setattr(backend, "first_user_model", lambda uid, api_id=None: ("test", "text-model"))
    assert backend.resolve_text_model(1, "test", "image-only") == ("test", "text-model")
    assert not backend.supports_text_model(1, "test", "embedding-only")
    assert backend.supports_text_model(1, "test", "text-model")


@pytest.mark.parametrize("failure_phase", ["context", "gm"])
def test_failed_gm_retry_reuses_rules_after_reloading_checkpoint(game, monkeypatch, failure_phase):
    import app
    import chat_pipeline
    from routes.game.chat import api_chat
    from schemas.game import ChatRequest
    game.data["player_character"]["hp"] = 1
    current = [game]
    saved = []
    monkeypatch.setattr(app, "_ensure_loaded", lambda *a, **k: current[0])
    monkeypatch.setattr(app, "_get_gm", lambda *a: type("GM", (), {"api_id": "stub"})())
    monkeypatch.setattr(app, "_get_sub_gm", app._get_gm)
    monkeypatch.setattr(app, "_payload_sse", lambda *a: current[0].status_payload())
    monkeypatch.setattr(app, "_resolve_persist_target", lambda *a: (None, None))
    monkeypatch.setattr(app, "_persist_runtime_checkpoint", lambda state, user: saved.append(copy.deepcopy(state.data)))
    monkeypatch.setattr(app, "_is_set_parser_enabled", lambda *a: False)
    monkeypatch.setattr(app, "_active_script_id", lambda *a: None)
    monkeypatch.setattr(app.platform_branches, "record_runtime_turn", lambda *a, **k: {})
    monkeypatch.setattr(app, "_build_usage_payload", lambda *a, **k: None)
    original_context = chat_pipeline.run_context_phase
    context_calls = []
    async def context(ctx, **kwargs):
        if ctx.resume_action:
            async for event in original_context(ctx, **kwargs):
                yield event
            return
        context_calls.append(ctx)
        if failure_phase == "context" and len(context_calls) == 1:
            raise ConnectionError("synthetic pre-rules failure")
        ctx.bundle = {"prompt": "test", "debug": {}}
        ctx.agent_result = {"steps": [], "curator_plan": {}}
        yield "agent", {"phase": "context", "status": "done"}
    attempts = []
    async def gm(ctx, **kwargs):
        attempts.append(ctx)
        if failure_phase == "gm" and len(attempts) == 1:
            raise ConnectionError("synthetic stream failure")
        ctx.response = "药剂使伤口闭合。"
        yield "token", {"text": ctx.response}
    monkeypatch.setattr(chat_pipeline, "run_context_phase", context)
    monkeypatch.setattr(chat_pipeline, "run_gm_phase", gm)
    async def request(retry=False, message="喝一瓶药剂", action_id="test-action", action_turn=0):
        response = await api_chat(ChatRequest(message=message, action_id=action_id,
                                              action_turn=action_turn, retry=retry), None)
        if response.status_code != 200:
            return response
        return "".join([chunk async for chunk in response.body_iterator])
    first = asyncio.run(request())
    assert "event: error" in first
    snapshot = saved[-1] if saved else game.data
    settled_hp = snapshot["player_character"]["hp"]
    assert settled_hp > 1 if failure_phase == "gm" else settled_hp == 1
    # Simulate process restart / reload: only the persisted snapshot survives.
    current[0] = GameState(copy.deepcopy(snapshot))
    monkeypatch.setattr(current[0], "save", lambda: None)
    second = asyncio.run(request(True))
    assert "event: error" not in second
    if failure_phase == "gm":
        assert current[0].data["player_character"]["hp"] == settled_hp
    else:
        assert current[0].data["player_character"]["hp"] > 1
    assert len(current[0].data["dice_log"]) == 1
    assert current[0].data["turn"] == 1
    assert len(context_calls) == (1 if failure_phase == "gm" else 2)
    assert "消耗" in attempts[-1].bundle["prompt"]
    expected_attempts = len(attempts)
    third = asyncio.run(request(True))
    assert '"replayed": true' in third and len(attempts) == expected_attempts
    assert current[0].data["turn"] == 1 and len(current[0].data["dice_log"]) == 1
    # A delayed retry remains invalid after a later round replaces the cached response.
    fourth = asyncio.run(request(message="不要攻击，先回顾刚才的经过", action_id="next-action", action_turn=1))
    assert "event: error" not in fourth and current[0].data["turn"] == 2
    after = copy.deepcopy(current[0].data)
    assert asyncio.run(request(True)).status_code == 409
    assert asyncio.run(request(True, action_id="unknown-old-action")).status_code == 409
    assert current[0].data == after


def test_interrupted_narration_keeps_settlement_pending_without_committing_turn(game, monkeypatch):
    import app
    game.data["pending_action"] = {"id": "interrupted", "message": "调查入口", "base_turn": 0}
    monkeypatch.setattr(app, "_persist_runtime_checkpoint", lambda *a, **k: None)
    monkeypatch.setattr(app.platform_branches, "record_runtime_turn",
                        lambda *a, **k: pytest.fail("Interrupted settlement must not commit a second round"))
    app._persist_chat_turn(None, game, "调查入口", "只生成了一半",
                          persist_user_id=None, active_save_id=None, interrupted=True)
    assert game.data["turn"] == 0
    assert game.data["pending_action"]["partial"] == "只生成了一半"
    assert not game.data["history"] or game.data["history"][-1].get("content") != "只生成了一半"
