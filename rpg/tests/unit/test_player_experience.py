from platform_app.player.experience import (
    choices,
    ensure_choices,
    narration_choices,
    progress,
    status,
)


def test_awakening_gains_come_from_committed_attributes_and_do_not_repeat():
    before = {"player": {}}
    after = {"player": {"martial_soul": "青羽弓", "soul_power": 5}}
    result = progress(before, after, "觉醒与魂力测定已完成。")
    assert {g["text"] for g in result["gains"]} == {"武魂：青羽弓", "魂力：5"}
    assert progress(after, after, "确认你的武魂。 ")["gains"] == []
    assert progress(before, before, "你将获得武魂青羽弓。")["gains"] == []


def test_player_stream_hides_bare_and_truncated_ops_across_chunk_boundaries():
    from platform_app.player.experience import PlayerTextGuard

    text = '你接过证明。\n{"op":"question","question":"怎么走？","options":["进城","问路","检查物品","等待"]}\n门外很安静。'
    guard = PlayerTextGuard()
    visible = "".join(guard.feed(text[i : i + 3]) for i in range(0, len(text), 3)) + guard.flush()
    assert visible == "你接过证明。\n\n门外很安静。"
    guard = PlayerTextGuard()
    assert (
        guard.feed('你收好它。{"op":"set","path":"memory.resources",') + guard.flush()
        == "你收好它。"
    )
    guard = PlayerTextGuard()
    assert guard.feed("墙上刻着{风}与[雨]。") + guard.flush() == "墙上刻着{风}与[雨]。"


def test_latest_reply_actions_replace_previous_round_buttons():
    state = {"structured_options": ["走进会堂", "等待", "回家", "观察门外"]}
    reply = "你已站在阵心。\n\n接下来，你可以：\n1. **闭目放松**，等待觉醒。\n2. 仔细感受魂力。\n3. 向执事询问异常。\n4. 调整站姿，稳住呼吸。"
    assert ensure_choices(state, reply) == [
        "闭目放松，等待觉醒。",
        "仔细感受魂力。",
        "向执事询问异常。",
        "调整站姿，稳住呼吸。",
    ]
    assert choices(state, ["旧按钮"], reply) == state["structured_options"]
    assert narration_choices("1. 桥\n2. 河\n3. 山\n4. 林\n" + "接着剧情发生了变化。" * 30) == []


def test_four_choices_preserve_scene_choices_and_use_known_people_only():
    state = {
        "player": {"current_location": "村口"},
        "relationships": {"同行者": "友好"},
        "structured_options": ["检查脚印", "检查脚印", "向同行者询问"],
    }
    result = choices(state)
    assert len(result) == 4 and len(set(result)) == 4
    assert result[:2] == ["检查脚印", "向同行者询问"]
    assert any("村口" in option for option in result)


def test_old_questions_are_not_offered_after_the_scene_moves_forward():
    state = {
        "turn": 1,
        "player": {"current_location": "会堂内"},
        "memory": {"current_objective": "选择求学方向"},
        "structured_options": ["走进会堂"],
        "options_turn": 0,
        "permissions": {"pending_questions": [{"turn": 0, "options": ["走进会堂"]}]},
    }
    result = ensure_choices(state)
    assert len(result) == 2 and "走进会堂" not in result
    assert any("选择求学方向" in action for action in result)
    assert state["options_turn"] == 1


def test_missing_opening_choices_use_only_named_facts_without_template_padding():
    assert choices({}) == []
    state = {
        "turn": 0,
        "player": {"current_location": "村长家"},
        "memory": {"current_objective": "筹备学院路费", "resources": ["推荐信"]},
        "relationships": {"老杰克": "相识"},
    }
    options = ensure_choices(state)
    assert len(options) == 4
    assert all(any(fact in option for fact in ("村长家", "学院路费", "老杰克", "推荐信")) for option in options)
    assert not any("眼前可交流的人" in option or "基础训练" in option for option in options)
    assert not any("武魂分殿" in option for option in options)


def test_new_question_ops_survive_legacy_persist_turn_increment():
    options = ["请村长起草推荐信", "领取身份材料", "与家人商量路费", "回家练习武魂"]
    state = {
        "turn": 3,
        "permissions": {
            "pending_questions": [{"turn": 2, "source": "gm:json", "options": options}]
        },
    }
    assert ensure_choices(state, question_turn=2) == options
    assert choices(state) == options
    assert state["permissions"]["pending_questions"][0]["turn"] == 3


def test_committed_gains_are_separate_from_narration_and_future_information():
    before = {
        "player": {"current_location": "村口"},
        "memory": {"resources": [], "abilities": []},
        "relationships": {},
    }
    after = {
        "player": {"current_location": "石屋"},
        "memory": {"resources": ["三枚铜币"], "abilities": ["辨认草药"]},
        "relationships": {"同行者": "信任"},
        "worldline": {"divergence_chapter": 3},
    }
    change = progress(before, after, "你听说远处有一把宝剑，但还没有得到它。", "走进石屋")
    assert [g["text"] for g in change["gains"]] == ["辨认草药", "三枚铜币"]
    assert all("宝剑" not in g["text"] for g in change["gains"])
    assert any(c["kind"] == "世界线" for c in change["changes"])
    assert any(c["kind"] == "人物关系" for c in change["changes"])
    assert status(after)["location"] == "石屋"


def test_quantities_consumption_and_pending_worldline_are_not_rewards():
    before = {"player_character": {"inventory": [{"name": "药剂", "quantity": 3}], "features": []}}
    after = {
        "player_character": {"inventory": [{"name": "药剂", "quantity": 1}], "features": []},
        "worldline": {"pending_projection": {"text": "未来奖励"}},
    }
    change = progress(before, after, "你用掉两瓶药剂。")
    assert change["gains"] == []
    assert change["losses"][0]["text"] == "药剂 -2"
    assert change["changes"] == []


def test_uninitialized_default_stats_are_not_presented_as_a_real_character():
    from platform_app.player.experience import attributes

    assert attributes({"player_character": {"name": "", "level": 0, "hp": 0, "ac": 0}}) == []
    assert attributes({"player": {"soul_power": 3}, "player_character": {"name": "", "level": 0}}) == [{"name": "魂力", "value": 3}]


def test_recorder_keeps_contextual_gm_choices_without_double_applying_rewards(monkeypatch):
    import copy
    import json
    from chat_pipeline.postproc import _response_with_recorder_ops
    from state import DEFAULT_STATE, GameState

    state = GameState(copy.deepcopy(DEFAULT_STATE))
    monkeypatch.setattr(state, "save", lambda: None)
    options = ["提交入学材料", "询问工读条件", "寻找接待老师", "先核对费用"]
    question = {"op": "question", "question": "如何办理入学？", "options": options}
    narration = "你已经抵达学院门口。\n```json\n" + json.dumps([
        {"op": "append", "path": "memory.resources", "value": "推荐信"}, question, question,
    ], ensure_ascii=False) + "\n```"
    response = _response_with_recorder_ops(narration, [
        {"op": "append", "path": "memory.resources", "value": "推荐信"},
        {"op": "set", "path": "player.current_location", "value": "学院门口"},
        {"op": "question", "question": "下一步？", "options": ["观察", "等待"]},
    ])
    state.apply_structured_updates(response)
    assert state.data["memory"]["resources"].count("推荐信") == 1
    assert state.data["player"]["current_location"] == "学院门口"
    assert len(state.data["permissions"]["pending_questions"]) == 1
    assert ensure_choices(state.data) == options


def test_empty_recorder_preserves_gm_state_and_choices():
    from chat_pipeline.postproc import _response_with_recorder_ops

    response = '正文\n```json\n[{"op":"question","question":"去哪？","options":["东门","西门"]}]\n```'
    assert _response_with_recorder_ops(response, []) == response
