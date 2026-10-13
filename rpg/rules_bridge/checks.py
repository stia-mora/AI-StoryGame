"""checks.py — 技能检定、豁免检定、陷阱检定。"""
from __future__ import annotations

import modules as module_registry
from rules import RulesEngine, get_engine
from rules_bridge.conditions import add_condition, player_action, skill_disadvantage


def room_definition(state, room_id: str | None = None) -> dict:
    scene = state.data.get("scene") or {}
    module_id = scene.get("module_id")
    if not module_id:
        return {}
    location = room_id or scene.get("location_id")
    return next((r for r in module_registry.load_module(module_id).get("rooms", [])
                 if r.get("id") == location), {})


def check_id(check: dict, index: int) -> str:
    return str(check.get("id") or f"check_{index}")


def resolve_room_check(state, action: dict) -> dict | None:
    """Resolve public IDs (and legacy skill/ability buttons) against module data."""
    room = room_definition(state)
    requested = action.get("check_id")
    for index, check in enumerate(room.get("checks") or []):
        if requested:
            matches = check_id(check, index) == requested
        else:
            matches = (check.get("kind") == action.get("kind") and
                       (check.get("skill") or check.get("ability")) ==
                       (action.get("skill") or action.get("ability")))
        if matches:
            return dict(check)
    return None


def perform_room_check(state, check: dict, seed: int | None = None) -> dict:
    """Only the module defines DC, unlocks and failure effects; facts unlock on success."""
    flags = (state.data.get("scene") or {}).get("flags") or {}
    required = check.get("requires_flag")
    if required and not flags.get(required):
        return {"ok": False, "error": "需要先发现相关线索"}
    room = room_definition(state)
    reason = check.get("label") or f"{room.get('name', '当前场景')} · {check.get('skill') or check.get('ability')}检定"
    if check.get("kind") == "saving_throw":
        hazard = next((h for h in room.get("hazards", [])
                       if h.get("id") == check.get("hazard_id")), {})
        result = perform_saving_throw(
            state, ability=check["ability"], dc=check["dc"], seed=seed, reason=reason,
            fail_damage_expr=check.get("fail_damage") or hazard.get("damage"),
            fail_condition=check.get("fail_condition") or hazard.get("condition"),
            condition_effect=check.get("condition_effect") or hazard.get("condition_effect"),
        )
    else:
        result = perform_skill_check(
            state, skill=check["skill"], dc=check["dc"], seed=seed, reason=reason,
            sets_flag=check.get("sets_flag") or check.get("reveals"),
        )
    if result.get("success") and check.get("fact"):
        result.setdefault("gm_facts", []).append(check["fact"])
        state.data.setdefault("scene", {}).setdefault("unlocked_facts", {})[
            check.get("reveals") or check.get("id") or reason] = check["fact"]
    return {"ok": True, "result": result}


@player_action
def perform_skill_check(
    state,
    skill: str,
    dc: int,
    advantage: bool = False,
    disadvantage: bool = False,
    seed: int | None = None,
    reason: str = "",
    sets_flag: str | None = None,
) -> dict:
    """对玩家角色执行技能检定，写入 dice_log 与 scene.flags。"""
    engine = get_engine()
    pc = state.data.get("player_character") or {}
    result = engine.skill_check(pc, skill, int(dc),
                                advantage=advantage, disadvantage=disadvantage or skill_disadvantage(state, skill),
                                seed=seed, actor_name=pc.get("name"), reason=reason)
    state.append_dice_log(RulesEngine.make_dice_log_entry(result, reason=reason))
    if result.success and sets_flag:
        state.set_scene_flag(sets_flag, True)
    if not result.success:
        scene = state.data.get("scene") or {}
        for hazard in (scene.get("current_room") or {}).get("hazards", []) or []:
            trigger = hazard.get("trigger_flag")
            if trigger:
                state.set_scene_flag(str(trigger), True)
                result.gm_facts.append(
                    f"检定失败触发场景风险：{hazard.get('description') or trigger}"
                )
    return result.to_dict()


@player_action
def perform_saving_throw(
    state,
    ability: str,
    dc: int,
    advantage: bool = False,
    disadvantage: bool = False,
    seed: int | None = None,
    reason: str = "",
    fail_damage_expr: str | None = None,
    fail_condition: str | None = None,
    condition_effect: dict | None = None,
) -> dict:
    from rules_bridge.combat import _sync_player_combatant
    engine = get_engine()
    pc = state.data.get("player_character") or {}
    result = engine.saving_throw(pc, ability, int(dc),
                                 advantage=advantage, disadvantage=disadvantage,
                                 seed=seed, actor_name=pc.get("name"), reason=reason)
    out: dict = result.to_dict()
    if not result.success:
        if fail_damage_expr:
            damage = engine.damage_roll(fail_damage_expr, seed=(seed + 1) if isinstance(seed, int) else None)
            dmg_amount = int(damage.get("total", 0))
            actual = state.damage_player(dmg_amount, reason=reason or "saving_throw_fail")
            _sync_player_combatant(state)
            out["damage"] = damage
            out["damage_applied"] = actual
            out["gm_facts"].append(
                f"{pc.get('name','玩家')} 受到 {actual} 点伤害（HP {state.data['player_character'].get('hp')}/"
                f"{state.data['player_character'].get('max_hp')}）。"
            )
        if fail_condition:
            conds = state.data.setdefault("player_character", {}).setdefault("conditions", [])
            if fail_condition not in conds:
                out["gm_facts"].append(f"{pc.get('name','玩家')} 获得状态：{fail_condition}。")
            add_condition(state, fail_condition, condition_effect)
            _sync_player_combatant(state)
    entry = RulesEngine.make_dice_log_entry(result, reason=reason)
    if out.get("damage"):
        entry["damage"] = out["damage"]
        entry["damage_applied"] = out["damage_applied"]
    state.append_dice_log(entry)
    return out


def trap_check(state, room_id: str, trap_id: str, seed: int | None = None) -> dict:
    """对房间内某个 hazard/陷阱解析掷豁免。"""
    get_engine()
    scene = state.data.get("scene") or {}
    if room_id != scene.get("location_id"):
        return {"ok": False, "error": "只能处理当前房间的危险"}
    module_id = scene.get("module_id")
    if not module_id:
        return {"ok": False, "error": "未加载模组"}
    bundle = module_registry.load_module(module_id)
    room = next((r for r in (bundle.get("rooms") or []) if r.get("id") == room_id), None)
    if not room:
        return {"ok": False, "error": f"未知房间：{room_id}"}
    hazard = next((h for h in (room.get("hazards") or []) if h.get("id") == trap_id), None)
    if not hazard:
        return {"ok": False, "error": f"房间无此陷阱：{trap_id}"}
    save = hazard.get("save") or {}
    ability = save.get("ability", "dex")
    dc = int(save.get("dc", 10))
    damage_expr = hazard.get("damage")
    return {
        "ok": True,
        "result": perform_saving_throw(
            state, ability=ability, dc=dc, seed=seed,
            reason=f"trap:{trap_id}",
            fail_damage_expr=damage_expr,
            fail_condition=hazard.get("condition"),
            condition_effect=hazard.get("condition_effect"),
        ),
    }
