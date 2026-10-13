"""consume.py — 物品消耗 (parse + action) 与短休。"""
from __future__ import annotations

import re

from core.clock import now_iso
from rules import RulesEngine, get_engine
from rules_bridge.combat import _sync_player_combatant, action_error, finish_player_action
from rules_bridge.conditions import player_action

# 中文/英文消耗动词
_CONSUME_VERBS_CN = ("点燃", "使用", "消耗", "用掉", "喝", "饮", "服下", "服用",
                     "吃", "用上", "用一", "拿出", "点亮", "拿来")
_CONSUME_VERBS_EN = ("use", "consume", "burn", "light", "drink", "eat", "spend")

# 量词
_QTY_CLASSIFIERS = "(?:支|份|瓶|颗|根|片|个|只|样|件|管)"


def _zh_numeral_to_int(token: str) -> int:
    mapping = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "零": 0}
    return mapping.get(token, 0)


def parse_consume_intent(text: str, character: dict) -> list[dict]:
    """从玩家文本里抽取 inventory 消耗意图。返回 list of
    {alias, qty, item_id, matched, raw}。

    确定性 parser，不依赖 LLM：
      1. 定位每个消耗动词位置（点燃/使用/消耗/use/burn 等）
      2. 在动词后窗口（≤20 字符）内寻找 inventory 真实存在的 item alias
      3. 窗口内的数字 + 量词解析为 qty（默认 1）
    """
    if not text:
        return []
    from rules.dnd5e.character import _ITEM_ALIASES, find_inventory_item, normalize_item_alias
    text_str = str(text)
    out: list[dict] = []
    seen: set[tuple] = set()

    # 按长度降序构造别名 list，确保 "healing draught" 不被 "draught" 之类的偏前匹配遮蔽
    aliases_sorted = sorted(_ITEM_ALIASES.keys(), key=lambda x: -len(x))

    # 中英文动词合并匹配
    all_verbs = list(_CONSUME_VERBS_CN) + list(_CONSUME_VERBS_EN)
    verb_pattern = "|".join(re.escape(v) for v in all_verbs)
    # 数量 token：阿拉伯数字 或 中文数字
    qty_pattern = r"(?:(\d+)|([一二两三四五六七八九十]))"

    # 步骤 1：定位每个 verb
    for verb_match in re.finditer(verb_pattern, text_str, re.IGNORECASE):
        verb_end = verb_match.end()
        # 步骤 2：动词后 20 字符窗口里找第一个 inventory 真实存在的 alias
        window = text_str[verb_end : verb_end + 24]
        found_alias = None
        alias_offset = None
        for alias in aliases_sorted:
            idx = window.lower().find(alias.lower())
            if idx >= 0:
                if alias_offset is None or idx < alias_offset:
                    found_alias = alias
                    alias_offset = idx
        if not found_alias:
            continue
        canonical = normalize_item_alias(found_alias)
        if not canonical:
            continue
        # 必须 inventory 里真有此物
        item = find_inventory_item(character, canonical)
        if item is None:
            continue
        # 步骤 3：在动词到 alias 之间解析 qty
        between = window[:alias_offset]
        qty = 1
        qm = re.search(qty_pattern, between)
        if qm:
            if qm.group(1):
                qty = int(qm.group(1))
            elif qm.group(2):
                qty = _zh_numeral_to_int(qm.group(2)) or 1

        key = (canonical, qty, verb_match.start())
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "alias": found_alias,
            "item_id": canonical,
            "item_name": item.get("name"),
            "qty": qty,
            "matched": text_str[verb_match.start() : verb_end + alias_offset + len(found_alias)],  # type: ignore[operator]
        })
    return out


@player_action
def consume_item_action(state, item_id: str, qty: int = 1,
                        reason: str = "", seed: int | None = None) -> dict:
    """RulesEngine consume_item 入口（chat 流程 / /api/rules/action 都用）。

    返回 {ok, result, dice_log_entry?, error}。
    成功时 player_character.inventory 已扣减，memory.resources 已同步。
    失败保持状态不变。
    """
    if not item_id:
        return {"ok": False, "error": "缺少 item_id"}
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        return {"ok": False, "error": "qty 必须是正整数"}
    from rules.dnd5e.character import find_inventory_item, heal
    pc = state.data.get("player_character") or {}
    item = find_inventory_item(pc, item_id)
    if not item or qty <= 0 or int(item.get("qty", 0)) < qty:
        return {"ok": False, "error": "物品数量不足或消耗数量无效"}
    import modules as module_registry
    module_id = (state.data.get("scene") or {}).get("module_id")
    definitions = module_registry.load_module(module_id).get("loot", []) if module_id else []
    definition = next((d for d in definitions if d.get("id") == item.get("id")), {})
    effect = definition.get("effect") or {}
    healing = effect.get("kind") == "heal"
    if healing and int(pc.get("hp", 0)) >= int(pc.get("max_hp", 0)):
        return {"ok": False, "error": "生命值已满，无需消耗治疗药剂"}
    in_combat = bool((state.data.get("encounter") or {}).get("active"))
    if in_combat and (error := action_error(state)):
        return {"ok": False, "error": error}
    # Validate and roll before mutating inventory; healing and consumption share one checkpoint.
    healing_roll = None
    if healing:
        rolls = [get_engine().damage_roll(effect["expression"], seed=seed + i if seed is not None else None)
                 for i in range(qty)]
        healing_roll = {"expression": effect["expression"], "total": sum(r["total"] for r in rolls),
                        "rolls": rolls}
    result = state.consume_inventory_item(item_id, qty)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "consume_item 失败"}
    # 记 dice_log（虽然没掷骰，但作为 rules action 留痕）
    healed = heal(pc, int(healing_roll["total"])) if healing_roll else 0
    _sync_player_combatant(state)
    entry = {
        "kind": "consume_item",
        "actor": pc.get("name") or "player",
        "target": result.get("item_name") or result.get("item_id"),
        "expression": "",
        "rolls": [],
        "modifier": 0,
        "total": result.get("consumed"),
        "dc": None,
        "success": True,
        "reason": reason or f"消耗 {result.get('item_name')} ×{result.get('consumed')}",
        "ts": now_iso(),
        "extra": {
            "healing": healing_roll,
            "healed": healed,
            "hp_after": pc.get("hp"),
            "item_id": result.get("item_id"),
            "qty_before": result.get("qty_before"),
            "qty_after": result.get("qty_after"),
        },
    }
    state.append_dice_log(entry)
    enemy_results = finish_player_action(state) if in_combat else []
    facts = [f"{entry['actor']} 消耗 {result.get('item_name')} ×{result.get('consumed')}（剩余 {result.get('qty_after')}）。"]
    if healing_roll:
        facts.append(f"恢复 {healed} 点生命值（HP {pc.get('hp')}/{pc.get('max_hp')}）。")
    for enemy_result in enemy_results:
        facts.extend((enemy_result.get("result") or {}).get("gm_facts") or [])
    return {
        "ok": True,
        "result": {
            "kind": "consume_item",
            "actor": entry["actor"],
            "target": entry["target"],
            "success": True,
            "gm_facts": facts,
            "extra": entry["extra"],
        },
        "dice_log_entry": entry,
        "enemy_actions": enemy_results,
    }


@player_action
def short_rest(state, seed: int | None = None) -> dict:
    """玩家短休：花生命骰回血。"""
    engine = get_engine()
    if (state.data.get("encounter") or {}).get("active"):
        return {"ok": False, "error": "战斗中无法短休"}
    scene = state.data.get("scene") or {}
    cur_room_flags = (scene.get("current_room") or {}).get("flags") or {}
    if not cur_room_flags.get("can_short_rest"):
        return {"ok": False, "error": "当前房间不适合短休"}
    pc = state.data.setdefault("player_character", {})
    result = engine.short_rest(pc, hit_die="1d8", seed=seed)
    _sync_player_combatant(state)
    state.append_dice_log(RulesEngine.make_dice_log_entry(result, reason="short_rest"))
    return {"ok": True, "result": result.to_dict(), "player_character": pc}
