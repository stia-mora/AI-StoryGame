import copy
import json
from contextlib import contextmanager
from types import SimpleNamespace

from platform_app.player.experience import progress
from platform_app.player.turn_updates import milestones, recording_packet, tasks


def test_committed_round_reports_all_six_panels_without_repeating_existing_facts():
    before = {
        "player": {"name": "沈砚", "role": "少年", "current_location": "村口", "soul_power": 4},
        "world": {"time": "清晨", "known_events": []},
        "memory": {
            "tasks": {
                "求学": {"status": "active", "description": "办理入学", "progress": "已有证明"}
            }
        },
    }
    after = copy.deepcopy(before)
    after["player"].update(role="工读生", current_location="学院", soul_power=5)
    after["world"].update(time="下午", known_events=["入学名额已经确认"])
    after["memory"].update(
        resources=["学院木牌"],
        abilities=["基础弓术"],
        tasks={
            "求学": {"status": "completed", "description": "办理入学", "progress": "已经登记与安顿"}
        },
        milestones=[
            {"name": "独自入学", "description": "选择工读路线并办妥入学", "status": "completed"}
        ],
    )
    after["relationships"] = {"宿舍管理员": "已认识，登记负责人"}
    change = progress(before, after, "你办妥入学并领取学院木牌。")
    assert change["panels"] == ["局势", "角色", "背包", "人物", "任务", "世界线"]
    assert any(c["kind"] == "任务" and "已完成" in c["after"] for c in change["changes"])
    assert any(c["kind"] == "关键节点" for c in change["changes"])
    assert progress(after, after, "你读了此前的记录。")["panels"] == []


def test_tasks_and_milestones_do_not_publish_future_or_private_fields():
    data = {
        "memory": {
            "tasks": [
                {
                    "name": "已接任务",
                    "status": "active",
                    "progress": "已经找到线索",
                    "secret": "私密后台材料",
                },
                {"name": "未来任务", "status": "future", "description": "未来秘密"},
            ],
            "milestones": [
                {
                    "name": "已达成",
                    "status": "completed",
                    "description": "实际结果",
                    "reward_plan": "未领取奖励",
                },
                {"name": "未来机缘", "status": "pending", "description": "将来的仙草"},
            ],
        },
        "player_private": {"secrets": "隐私"},
        "credentials": "凭据",
    }
    assert [t["name"] for t in tasks(data)] == ["已接任务"]
    assert milestones(data) == [{"name": "已达成", "description": "实际结果"}]
    assert milestones({"memory": {"milestones": data["memory"]["milestones"][0]}}) == [
        {"name": "已达成", "description": "实际结果"},
    ]
    packet = recording_packet(data)
    assert all(
        hidden not in packet
        for hidden in ["未来任务", "未来机缘", "secret", "credentials", "未领取奖励", "隐私"]
    )


def test_custom_service_provider_uses_owner_config_and_retains_player_identity(monkeypatch):
    import model_registry
    from agents.gm import master
    from core import llm_backend
    from platform_app import user_credentials
    from platform_app.player.meter import active_run

    seen = []
    monkeypatch.setattr(llm_backend, "resolve_text_model", lambda uid, api, model: (api, model))
    monkeypatch.setattr(model_registry, "load_model_catalog", lambda: {})
    monkeypatch.setattr(model_registry, "find_api", lambda catalog, api: None)
    monkeypatch.setattr(
        user_credentials,
        "get_credential",
        lambda uid, api: (
            seen.append((uid, api)) or {"base_url_override": "https://example.test/v1"}
        ),
    )
    monkeypatch.setattr(master, "_OpenAICompatBackend", lambda **kwargs: SimpleNamespace(**kwargs))
    token = active_run.set(
        SimpleNamespace(uid=3, profile={"api_id": "custom_service", "credential_owner_id": 7})
    )
    try:
        gm = master.GameMaster(model="text", api_id="custom_service", user_id=3)
    finally:
        active_run.reset(token)
    assert seen == [(7, "custom_service")]
    assert gm.user_id == 3 and gm._backend.user_id == 3


def test_known_current_goal_remains_visible_alongside_completed_tasks():
    data = {
        "memory": {
            "current_objective": "办理入学",
            "tasks": {
                "觉醒": {"name": "觉醒", "status": "completed"},
            },
        }
    }
    assert [(task["name"], task["status"]) for task in tasks(data)] == [
        ("觉醒", "completed"),
        ("当前目标", "active"),
    ]


def test_active_long_running_task_does_not_hide_a_new_committed_goal():
    before = {
        "memory": {
            "current_objective": "办理推荐信",
            "tasks": {
                "求学": {
                    "name": "求学",
                    "status": "active",
                    "progress": "待领取推荐信",
                }
            },
        }
    }
    after = copy.deepcopy(before)
    after["memory"]["current_objective"] = "携带推荐信前往学院"
    assert tasks(after)[-1]["description"] == "携带推荐信前往学院"
    assert tasks(after)[0] == tasks(before)[0]  # Do not infer task completion.
    change = progress(before, after, "推荐信已领取。")
    assert "任务" in change["panels"]
    assert [item["kind"] for item in change["changes"]] == ["目标"]
    assert progress(after, after, "查看存档。")["panels"] == []
    assert "携带推荐信前往学院" in recording_packet(after)


def test_six_panel_ops_survive_the_actual_state_writer_and_public_projection():
    from platform_app.player.experience import attributes, status
    from state import DEFAULT_STATE, GameState

    game = GameState(copy.deepcopy(DEFAULT_STATE))
    game.data["permissions"]["mode"] = "full_access"
    before = copy.deepcopy(game.data)
    ops = [
        {"op": "set", "path": "player.current_location", "value": "学院"},
        {"op": "set", "path": "player.soul_power", "value": 4},
        {"op": "append", "path": "memory.resources", "value": "学院木牌"},
        {"op": "set", "path": "relationships.宿舍管理员", "value": "已认识，负责登记"},
        {
            "op": "set",
            "path": "memory.tasks.求学",
            "value": {
                "name": "求学",
                "status": "completed",
                "description": "完成登记和安顿",
            },
        },
        {
            "op": "append",
            "path": "memory.milestones",
            "value": {
                "name": "学院入学",
                "status": "completed",
                "description": "以工读身份入学",
            },
        },
    ]
    game.apply_structured_updates("```json\n" + json.dumps(ops, ensure_ascii=False) + "\n```")
    assert {a["name"]: a["value"] for a in attributes(game.data)}["魂力"] == 4
    assert status(game.data)["resources"] == ["学院木牌"]
    assert tasks(game.data)[0]["status"] == "completed"
    assert milestones(game.data)[0]["name"] == "学院入学"
    next_node = {"name": "正式开课", "status": "completed", "description": "完成第一段训练"}
    game.apply_structured_updates(
        "```json\n"
        + json.dumps(
            [
                {"op": "append", "path": "memory.milestones", "value": next_node},
                {"op": "append", "path": "memory.milestones", "value": next_node},
            ],
            ensure_ascii=False,
        )
        + "\n```"
    )
    assert [m["name"] for m in milestones(game.data)] == ["学院入学", "正式开课"]
    assert progress(before, game.data, "你完成登记并领取学院木牌。")["panels"] == [
        "局势",
        "角色",
        "背包",
        "人物",
        "任务",
        "世界线",
    ]


def test_numeric_story_node_importance_is_honored_and_clamped():
    from agents.anchor_seed_agent import _compute_importance

    assert _compute_importance({"importance": 85}, "普通事件描述") == 85
    assert _compute_importance({"importance": 65}, "普通事件描述") == 65
    assert _compute_importance({"importance": "high"}, "普通事件描述") == 70
    assert _compute_importance({"importance": 999}, "普通事件描述") == 100


def test_enriched_nodes_seed_choices_and_metadata_without_rewriting_existing_history(monkeypatch):
    from agents import anchor_seed_agent as seed

    writes = []
    existing = []
    event = {
        "event": "学院登记与安顿完成后选择新的学习方向，不强制发生死亡剧情",
        "importance": 85,
        "node_id": "academy-enrollment",
        "must_preserve": [],
        "may_vary": ["参与者", "成败结果"],
        "dimensions": ["角色", "任务", "私有后台字段"],
        "decision_required": True,
        "is_fatal": False,
    }

    class Database:
        def execute(self, query, args):
            if "select id, script_id" in query:
                return SimpleNamespace(fetchone=lambda: {"id": 1, "script_id": 2})
            if "from chapter_facts" in query:
                return SimpleNamespace(fetchall=lambda: [{"chapter": 1, "events": [event]}])
            if "select anchor_key" in query:
                return SimpleNamespace(fetchall=lambda: existing)
            assert "insert into save_anchor_states" in query
            writes.append(args)

    @contextmanager
    def database():
        yield Database()

    monkeypatch.setattr(seed, "connect", database)
    monkeypatch.setattr(seed, "init_db", lambda: None)
    assert seed.seed_anchors_for_save(1)["seeded"] == 1
    row = writes[0]
    assert row[7].obj == []
    assert row[8].obj == ["参与者", "成败结果"]
    assert row[9] == 85
    assert row[10] is False
    assert row[11].obj["dimensions"] == ["角色", "任务"]
    assert row[11].obj["decision_required"] is True
    existing.append({"anchor_key": "chapter:1:event:0"})
    assert seed.seed_anchors_for_save(1)["seeded"] == 0
    assert len(writes) == 1
