from contextlib import contextmanager
from types import SimpleNamespace

from platform_app.player import catalog, generation_progress


def test_zero_turn_summary_uses_saved_opening_content_instead_of_turn_number():
    save = {"id": 1, "player_story_id": 7, "title": "角色", "updated_at": "now",
            "state_snapshot": {"turn": 0, "history": [{"role": "assistant", "content": "已保存的序章。"}]}}
    assert catalog.save_summary(save)["has_opening"] is True
    save["state_snapshot"]["history"] = []
    assert catalog.save_summary(save)["has_opening"] is False
    save["has_opening"] = True
    assert catalog.save_summary(save)["has_opening"] is True


def test_public_status_keeps_known_people_and_resources_without_private_memory():
    data = {"player": {"name": "旅人", "current_location": "码头", "secret": "PRIVATE"},
            "world": {"time": "清晨"}, "memory": {"resources": ["推荐信"], "notes": "PRIVATE"},
            "relationships": {"守灯人": {"relationship": "相识", "secret": "PRIVATE"}}}
    result = catalog.public_status(data)
    assert result["location"] == "码头" and result["time"] == "清晨"
    assert result["people"] == [{"name": "守灯人", "relationship": "相识"}]
    assert result["resources"] == ["推荐信"]
    assert "PRIVATE" not in str(result)


def test_each_history_message_gets_its_own_public_status(monkeypatch):
    from kb import live_repo

    old = {"player": {"name": "旅人", "current_location": "码头"}, "world": {"time": "清晨"}}
    new = {"player": {"name": "旅人", "current_location": "学院"}, "world": {"time": "次日"}}
    story = {"id": 7, "title": "雾港", "introduction": "简介", "identities": [], "cover": "", "defaults": {}}
    save = {"id": 9, "player_story_id": 7, "title": "旅人", "updated_at": "now", "active_commit_id": 2,
            "state_snapshot": new, "player_story_snapshot": story}
    rows = [
        {"id": 2, "parent_id": 1, "player_input": "去学院", "gm_output": "抵达学院。", "turn_index": 1, "display_state": new, "previous_state": old},
        {"id": 1, "parent_id": None, "player_input": "", "gm_output": "站在码头。", "turn_index": 0, "display_state": old, "previous_state": {}},
    ]
    @contextmanager
    def connect():
        yield SimpleNamespace(execute=lambda sql, args: SimpleNamespace(fetchall=lambda: rows if "with recursive path" in sql else []))
    monkeypatch.setattr(catalog, "connect", connect)
    monkeypatch.setattr(catalog, "player_save", lambda *args: save)
    seen = []
    def known_people(db, table, sid, commit_id, columns):
        seen.append((table, sid, commit_id))
        return [{"from_key": "_player", "to_key": "守灯人", "kind": "初识", "metadata": {}},
                {"from_key": "别人", "to_key": "不该显示的人", "kind": "相识", "metadata": {}}]
    monkeypatch.setattr(live_repo, "_newest_visible", known_people)
    result = catalog.view(3, 9)
    assert [message["status"]["location"] for message in result["messages"] if message["role"] == "assistant"] == ["码头", "学院"]
    assert result["status"]["location"] == "学院"
    assert result["save"]["has_opening"] is True
    assert result["status"]["people"] == [{"name": "守灯人", "value": "初识"}]
    assert result["messages"][0]["status"]["people"] == []
    assert seen == [("kb_relationships", 9, 2)]


def test_duration_reference_uses_only_observed_completed_request_timings(monkeypatch):
    seen = []
    @contextmanager
    def connect():
        def execute(sql, args):
            seen.append((sql, args))
            return SimpleNamespace(fetchall=lambda: [{"seconds": value} for value in (180, 240, 300)])
        yield SimpleNamespace(execute=execute)
    monkeypatch.setattr(generation_progress, "connect", connect)
    result = generation_progress.recent_timing(3, 9, "turn", {"api_id": "test", "model": "fast"})
    assert result == {"samples": 3, "median_seconds": 240, "low_seconds": 180, "high_seconds": 300}
    assert seen[0][1] == (3, 9, "turn", "test", "fast")
    assert "r.status='settled'" in seen[0][0] and "l.kind='settle'" in seen[0][0]


def test_no_duration_history_returns_no_invented_estimate(monkeypatch):
    @contextmanager
    def connect():
        yield SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: []))
    monkeypatch.setattr(generation_progress, "connect", connect)
    assert generation_progress.recent_timing(3, 9, "opening", {"api_id": "test", "model": "fast"}) is None


def test_output_limit_notice_is_saved_with_actual_charge_and_unused_hold_returned(monkeypatch):
    from platform_app.player import wallet

    request = {"id": "request", "rates": wallet.DEFAULT_RATES, "cap_micro": 141320000,
               "free_hold": 0, "permanent_hold": 141320000, "free_day": "today"}
    monkeypatch.setattr(wallet, "lock_request", lambda *args: ({"free_day": "today"}, request))
    updates, entries = [], []
    def execute(sql, args):
        updates.append((sql, args))
        return SimpleNamespace(fetchall=lambda: [{"billable": True, "input_tokens": 250, "output_tokens": 12500}])
    monkeypatch.setattr(wallet, "ledger", lambda *args, **kwargs: entries.append(args))
    receipt = wallet.settle(SimpleNamespace(execute=execute), 3, "request", 9, "已保存的原文", [],
                            output_notice="正文可能不完整")
    assert receipt["output_notice"] == "正文可能不完整"
    assert receipt["text"] == "已保存的原文" and receipt["charged_micro"] == 50250000
    assert entries[0][2:6] == ("settle", 0, 91070000, -141320000)
    stored = next(args[2].obj for sql, args in updates if "status='settled'" in sql)
    assert stored["output_notice"] == receipt["output_notice"]
