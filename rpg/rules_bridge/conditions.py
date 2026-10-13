"""Temporary module conditions expire after successful player rule actions.

An exploration action is one round; nested hazard saves are part of the move.
Narration retries, questions, rejected actions and automatic enemies do not tick it.
"""
from __future__ import annotations

from contextvars import ContextVar
from functools import wraps

_action_state: ContextVar = ContextVar("rules_player_action", default=None)


def add_condition(state, name: str, effect: dict | None = None) -> None:
    pc = state.data.setdefault("player_character", {})
    conditions = pc.setdefault("conditions", [])
    if name not in conditions:
        conditions.append(name)
    if effect and effect.get("duration_actions"):
        pc.setdefault("condition_effects", {})[name] = {
            **effect, "started_action": int((state.data.get("scene") or {}).get("player_action_count", 0)) + 1,
        }


def skill_disadvantage(state, skill: str) -> bool:
    from rules.dnd5e.ruleset import normalize_skill
    repair_legacy_conditions(state)
    pc = state.data.get("player_character") or {}
    return any(normalize_skill(skill) in effect.get("disadvantage_skills", [])
               for name, effect in (pc.get("condition_effects") or {}).items()
               if name in (pc.get("conditions") or []))


def repair_legacy_conditions(state) -> None:
    pc = state.data.get("player_character") or {}
    scene = state.data.get("scene") or {}
    missing = set(pc.get("conditions") or []) - set(pc.get("condition_effects") or {})
    if not missing or not scene.get("module_id"):
        return
    import modules as module_registry
    for room in module_registry.load_module(scene["module_id"]).get("rooms", []):
        for hazard in room.get("hazards", []):
            name, effect = hazard.get("condition"), hazard.get("condition_effect")
            if name in missing and effect and effect.get("duration_actions"):
                pc.setdefault("condition_effects", {})[name] = {
                    **effect, "started_action": int(scene.get("player_action_count", 0)),
                }


def player_action(fn):
    @wraps(fn)
    def execute(state, *args, **kwargs):
        nested = _action_state.get() is state
        token = _action_state.set(state)
        try:
            result = fn(state, *args, **kwargs)
        finally:
            _action_state.reset(token)
        if nested or not result.get("ok", True) or not (state.data.get("scene") or {}).get("module_id"):
            return result
        scene = state.data.setdefault("scene", {})
        count = scene["player_action_count"] = int(scene.get("player_action_count", 0)) + 1
        pc = state.data.get("player_character") or {}
        effects = pc.get("condition_effects") or {}
        expired = [name for name, effect in effects.items()
                   if int(effect.get("duration_actions") or 0) > 0
                   and count >= int(effect.get("started_action", 0)) + int(effect["duration_actions"])]
        for name in expired:
            effects.pop(name)
            pc["conditions"] = [c for c in pc.get("conditions", []) if c != name]
        if expired:
            from rules_bridge.combat import _sync_player_combatant
            _sync_player_combatant(state)
            narration = result.get("result") or result
            narration.setdefault("gm_facts", []).append(f"短期状态结束：{', '.join(expired)}。")
        return result
    return execute
