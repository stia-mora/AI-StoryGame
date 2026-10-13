"""combat.py — 战斗初始化、攻击、回合推进。"""
from __future__ import annotations

import modules as module_registry
from core.clock import now_iso
from rules import RulesEngine, get_engine
from rules_bridge.conditions import player_action
from rules_bridge.entity_sync import _entities_from_encounter, _sync_active_entities_to_scene


def turn_token(encounter: dict) -> str:
    return f"{encounter.get('encounter_id')}:{encounter.get('round')}:{encounter.get('turn_index')}"


def current_actor(encounter: dict) -> str:
    order = encounter.get("initiative_order") or []
    index = int(encounter.get("turn_index", 0))
    return str(order[index].get("id") or "") if 0 <= index < len(order) else ""


def action_error(state, actor_id: str = "player") -> str:
    encounter = state.data.get("encounter") or {}
    if not encounter.get("active"):
        return "当前没有进行中的战斗"
    if current_actor(encounter) != actor_id:
        return "尚未轮到该角色行动"
    if encounter.get("action_used") == turn_token(encounter):
        return "本回合行动已使用"
    combatant = next((c for c in encounter.get("combatants", []) if c.get("id") == actor_id), {})
    if combatant.get("defeated") or int(combatant.get("hp", 0)) <= 0:
        return "倒下的角色无法行动"
    return ""


def _advance_raw(state) -> None:
    encounter = state.data.get("encounter") or {}
    get_engine().next_turn(encounter)
    encounter.pop("action_used", None)
    if not encounter.get("active"):
        _finalize_encounter(state, encounter, encounter.get("outcome") or "stalemate")


def run_enemy_turns(state) -> list[dict]:
    """Resolve initiative up to the next player decision, including initial enemy initiative."""
    encounter = state.data.get("encounter") or {}
    results = []
    for _ in range(len(encounter.get("initiative_order") or []) + 1):
        if not encounter.get("active") or current_actor(encounter) == "player":
            break
        attacker = current_actor(encounter)
        result = enemy_attack(state, attacker)
        results.append(result)
        if encounter.get("active"):
            _advance_raw(state)
    _sync_active_entities_to_scene(state)
    return results


def finish_player_action(state) -> list[dict]:
    encounter = state.data.get("encounter") or {}
    if not encounter.get("active"):
        return []
    encounter["action_used"] = turn_token(encounter)
    _advance_raw(state)
    return run_enemy_turns(state)


def _sync_player_combatant(state) -> None:
    pc = state.data.get("player_character") or {}
    encounter = state.data.get("encounter") or {}
    if not encounter.get("combatants"):
        return
    for combatant in encounter.get("combatants", []):
        if combatant.get("id") == "player":
            combatant["hp"] = int(pc.get("hp", combatant.get("hp", 0)) or 0)
            combatant["max_hp"] = int(pc.get("max_hp", combatant.get("max_hp", 0)) or 0)
            combatant["ac"] = int(pc.get("ac", combatant.get("ac", 10)) or 10)
            combatant["conditions"] = list(pc.get("conditions") or [])
            combatant["defeated"] = combatant["hp"] <= 0
            break


def start_encounter_by_id(state, encounter_id: str, seed: int | None = None) -> dict:
    """根据当前模组 encounters.json 中的 id 启动战斗。"""
    engine = get_engine()
    scene = state.data.setdefault("scene", {})
    module_id = scene.get("module_id")
    if not module_id:
        return {"ok": False, "error": "未加载模组"}
    # 守卫:已有进行中的战斗时不得重复 combat_start —— 原来无条件 set_encounter 覆盖,
    # 战斗打到一半再次触发同一 encounter_id(LLM 叙事"重新开打"/场景脚本二次触发)会用
    # 满血 stat_block 重建所有 combatants → 敌人血量重置、已 defeated 的复活、进度全丢
    # (玩家可借此无限重置 boss)。
    if (state.data.get("encounter") or {}).get("active"):
        return {"ok": False, "error": "已有进行中的战斗,请先结束当前战斗再开新战斗"}
    bundle = module_registry.load_module(module_id)
    enc_defs = bundle.get("encounters") or []
    enc_def = next((e for e in enc_defs if e.get("id") == encounter_id), None)
    if not enc_def:
        return {"ok": False, "error": f"未知遭遇：{encounter_id}"}
    if enc_def.get("victory_flag") and (scene.get("flags") or {}).get(enc_def["victory_flag"]):
        return {"ok": False, "error": "该遭遇已解决"}

    pc = state.data.get("player_character") or {}
    if int(pc.get("hp", 0)) <= 0:
        return {"ok": False, "error": "倒下的角色无法开战"}
    party_member = dict(pc)
    party_member["id"] = "player"
    party_member.setdefault("name", pc.get("name") or "Player")
    enemies = []
    for e in enc_def.get("enemies") or []:
        if (scene.get("entity_outcomes") or {}).get(e.get("instance_id")) == "defeated":
            continue
        comb = engine.build_combatant(e["stat_block_id"], instance_id=e.get("instance_id"), name=e.get("name"))
        enemies.append(comb)
    if not enemies:
        return {"ok": False, "error": "该遭遇的敌人已经倒下"}

    encounter = engine.start_encounter([party_member], enemies, seed=seed, encounter_id=encounter_id)
    encounter["definition"] = {"id": encounter_id, "name": enc_def.get("name"),
                               "victory_flag": enc_def.get("victory_flag"),
                               "location_id": enc_def.get("location_id") or scene.get("location_id")}
    state.set_encounter(encounter)
    # 三层人物系统:合法 encounter 启动 → combatants 进 active_entities
    # (source='encounter'),与 room_data 实体并存。
    loc = scene.get("location_id") or enc_def.get("location_id") or ""
    for ent in _entities_from_encounter(encounter, loc):
        state.upsert_active_entity(ent)
    # 把先攻骰记入 dice_log
    for entry in encounter.get("initiative_order", []):
        state.append_dice_log({
            "id": f"dl_init_{entry.get('id')}",
            "kind": "initiative",
            "actor": entry.get("name"),
            "expression": entry.get("roll", {}).get("expression"),
            "rolls": entry.get("roll", {}).get("rolls"),
            "modifier": entry.get("dex_mod"),
            "total": entry.get("init"),
            "reason": f"先攻 - {enc_def.get('name')}",
            "ts": now_iso(),
        })
    enemy_results = run_enemy_turns(state)
    return {"ok": True, "encounter": encounter, "enemy_actions": enemy_results}


def _finalize_encounter(state, encounter: dict, outcome: str) -> None:
    """战斗结算收尾:置 active=False/outcome,胜利时写 victory_flag 进 scene.flags。
    必须在 player_attack 和 enemy_attack 两条结算路径都调用 —— 原来 victory_flag 只在
    player_attack 路径写,最后一个敌人在**敌方回合**死亡(反伤/群体/GM 误调 enemy_attack
    让 boss 死于敌方结算)时,is_encounter_resolved=victory 但 victory_flag 永不置位 →
    boss_defeated 等剧情门控 flag 拿不到 → 后续房间/结局门控卡死。"""
    encounter["active"] = False
    encounter["outcome"] = outcome
    _sync_active_entities_to_scene(state)
    if outcome == "victory":
        victory_flag = (encounter.get("definition") or {}).get("victory_flag")
        if victory_flag:
            state.set_scene_flag(victory_flag, True)


@player_action
def player_attack(state, target_id: str, weapon_id: str = "shortsword",
                  advantage: bool = False, disadvantage: bool = False,
                  seed: int | None = None, expected_turn: str | None = None) -> dict:
    """玩家对当前 encounter 中的 target 发动攻击。"""
    engine = get_engine()
    encounter = state.data.get("encounter") or {}
    if not encounter.get("active"):
        return {"ok": False, "error": "当前没有进行中的战斗"}
    if expected_turn and expected_turn != turn_token(encounter):
        return {"ok": False, "error": "战斗回合已变化，请刷新后行动"}
    error = action_error(state)
    if error:
        return {"ok": False, "error": error}
    target = next((c for c in encounter.get("combatants", [])
                   if c.get("id") == target_id and c.get("side") == "enemy"), None)
    if not target:
        return {"ok": False, "error": f"未找到敌方目标：{target_id}"}
    if target.get("defeated"):
        return {"ok": False, "error": f"目标已倒下：{target_id}"}

    pc = state.data.get("player_character") or {}
    weapon = (pc.get("weapons") or {}).get(weapon_id)
    if not weapon:
        return {"ok": False, "error": f"角色未持有武器：{weapon_id}"}

    result = engine.attack_roll(
        attacker=pc, target=target,
        attack_bonus=int(weapon.get("attack_bonus", 4)),
        damage_expr=str(weapon.get("damage", "1d6")),
        advantage=advantage, disadvantage=disadvantage,
        seed=seed,
        attacker_name=pc.get("name"),
        target_name=target.get("name"),
        weapon_name=weapon.get("name") or weapon_id,
    )
    # 应用 state_ops（命中扣 target HP）
    state.apply_rules_state_ops([op.to_dict() for op in result.state_ops], reason=f"player_attack {target_id}")
    state.append_dice_log(RulesEngine.make_dice_log_entry(result, reason=f"attack {target_id}"))

    # 检查 defeated；若是首领被击败，置 victory_flag
    newly = engine.mark_defeated_by_hp(encounter)
    if newly:
        result.gm_facts.append(f"{', '.join(newly)} 倒下。")

    resolved, outcome = engine.is_encounter_resolved(encounter)
    if resolved:
        _finalize_encounter(state, encounter, outcome)
        result.gm_facts.append(f"战斗结束：{outcome}。")
    enemy_results = finish_player_action(state) if encounter.get("active") else []
    for enemy_result in enemy_results:
        result.gm_facts.extend((enemy_result.get("result") or {}).get("gm_facts") or [])
    _sync_active_entities_to_scene(state)
    return {"ok": True, "result": result.to_dict(), "encounter": encounter, "enemy_actions": enemy_results}


def enemy_attack(state, attacker_id: str, target_id: str = "player",
                 attack_index: int = 0, seed: int | None = None) -> dict:
    """敌方角色对玩家或其他战斗员发动攻击。"""
    engine = get_engine()
    encounter = state.data.get("encounter") or {}
    if not encounter.get("active"):
        return {"ok": False, "error": "当前没有进行中的战斗"}
    error = action_error(state, attacker_id)
    if error:
        return {"ok": False, "error": error}
    attacker = next((c for c in encounter.get("combatants", []) if c.get("id") == attacker_id), None)
    if not attacker or attacker.get("side") != "enemy" or attacker.get("defeated"):
        return {"ok": False, "error": f"无效的攻击者：{attacker_id}"}
    attacks = attacker.get("attacks") or []
    if not attacks:
        return {"ok": False, "error": "攻击者没有攻击动作"}
    atk_def = attacks[max(0, min(int(attack_index), len(attacks) - 1))]
    # 目标
    if target_id == "player":
        pc = state.data.get("player_character") or {}
        target = {"name": pc.get("name") or "Player", "ac": int(pc.get("ac", 10)), "id": "player"}
    else:
        target = next((c for c in encounter.get("combatants", []) if c.get("id") == target_id), None)  # type: ignore[arg-type]
        if not target:
            return {"ok": False, "error": f"未知目标：{target_id}"}
        # 与 player_attack 一致:不能攻击已倒下的目标(原来 enemy_attack 缺此守卫,
        # 可对已 defeated 目标反复结算,刷无意义 dice_log)。
        if target.get("defeated"):
            return {"ok": False, "error": f"目标已倒下：{target_id}"}

    result = engine.attack_roll(
        attacker=attacker, target=target,
        attack_bonus=int(atk_def.get("attack_bonus", 3)),
        damage_expr=str(atk_def.get("damage", "1d6")),
        seed=seed,
        attacker_name=attacker.get("name"),
        target_name=str(target.get("name")) if target.get("name") is not None else None,
        weapon_name=atk_def.get("name") or "Attack",
    )
    if result.success and target_id == "player":
        amount = int((result.damage or {}).get("total", 0))
        actual = state.damage_player(amount, reason=f"enemy_attack {attacker_id}")
        _sync_player_combatant(state)
        # 打玩家走 damage_player 直改 HP,绕过 apply_rules_state_ops → 原来漏审计(打 NPC 分支有)。
        # 补一条同构 audit_log(source=rules_engine),dice_log 仍由下方 append_dice_log 单独写,不双写。
        state.append_rules_audit(reason=f"enemy_attack {attacker_id}", ops=1)
        result.gm_facts.append(
            f"玩家受到 {actual} 点伤害（HP {state.data['player_character'].get('hp')}/"
            f"{state.data['player_character'].get('max_hp')}）。"
        )
    elif result.success and target_id != "player":
        state.apply_rules_state_ops([op.to_dict() for op in result.state_ops], reason="enemy_attack")
    state.append_dice_log(RulesEngine.make_dice_log_entry(result, reason=f"enemy_attack {attacker_id}->{target_id}"))
    encounter["action_used"] = turn_token(encounter)

    engine.mark_defeated_by_hp(encounter)
    resolved, outcome = engine.is_encounter_resolved(encounter)
    if resolved:
        # 用共用 finalize:原来这里漏写 victory_flag → 最后一敌死于敌方回合时门控 flag 永不置。
        _finalize_encounter(state, encounter, outcome)
        result.gm_facts.append(f"战斗结束：{outcome}。")
    _sync_active_entities_to_scene(state)
    return {"ok": True, "result": result.to_dict(), "encounter": encounter}


@player_action
def advance_turn(state) -> dict:
    encounter = state.data.get("encounter") or {}
    if not encounter.get("active"):
        return {"ok": False, "error": "没有进行中的战斗"}
    _sync_player_combatant(state)
    if current_actor(encounter) == "player" or encounter.get("action_used") == turn_token(encounter):
        _advance_raw(state)
    enemy_results = run_enemy_turns(state)
    # next_turn 可能因 >50 回合僵局(或退化空 initiative)兜底强制结束战斗(active=False)。
    # 这条路径不经攻击结算,故必须在此收尾:否则 encounter 静默失活、无结算事实/无 flag,
    # 玩家再攻击只会得"没有进行中的战斗",依赖战斗结局的剧情门控卡死(软锁)。
    if not encounter.get("active"):
        outcome = encounter.get("outcome") or "stalemate"
        _finalize_encounter(state, encounter, outcome)
        return {
            "ok": True, "encounter": encounter, "resolved": True, "outcome": outcome,
            "message": "战斗超过 50 回合未分胜负,判定为僵局(stalemate)结束。",
        }
    return {"ok": True, "encounter": encounter, "enemy_actions": enemy_results}
