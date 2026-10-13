"""
test_rules_chat_pipeline.py — free-form player input must hit RulesEngine before GM narration.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.helpers import cleanup_test_users, make_client, register_user


class RulesChatPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from platform_app.db import init_db
        init_db()
        cleanup_test_users()
        cls.client = make_client()

    @classmethod
    def tearDownClass(cls):
        cleanup_test_users()

    def _consume(self, resp) -> list[dict]:
        events: list[dict] = []
        ev = "message"
        data_lines: list[str] = []
        for raw_line in resp.iter_lines():
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if line == "":
                if data_lines:
                    try:
                        data = json.loads("\n".join(data_lines))
                    except Exception:
                        data = "\n".join(data_lines)
                    events.append({"event": ev, "data": data})
                ev = "message"
                data_lines = []
                continue
            if line.startswith("event:"):
                ev = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
        return events

    def test_free_text_stealth_runs_rules_engine_before_gm(self):
        import app as ui_mod

        user = register_user(self.client)
        cookies = user["cookies"]
        self.client.post("/api/v1/rules/module/start", json={"module_id": "ash_mine"}, cookies=cookies)

        def fake_context_agent(*args, **kwargs):
            yield {
                "type": "result",
                "retrieved_context": "",
                "bundle": {"debug": {"cache_plan": {}}, "prompt": "stub"},
                "steps": [],
                "agent_prompt": "stub",
                "curator_plan": {
                    "rule_candidate_actions": [{
                        "kind": "skill_check",
                        "skill": "stealth",
                        "dc": 13,
                        "move_to": "minecart_track",
                        "reason": "悄悄靠近矿车",
                        "seed": 7,
                    }],
                },
            }

        class StubGM:
            api_id = "stub"

            class Backend:
                model_name = "stub"
                last_usage = {}

            _backend = Backend()

            def curate_context(self, *args, **kwargs):
                return ""

            def respond_stream_with_tools(self, *args, **kwargs):
                yield {"type": "text", "text": "你压低脚步，矿车阴影挡住了你的轮廓。"}

        orig_rca = ui_mod.run_context_agent
        orig_get_gm = ui_mod._get_gm
        orig_get_sub_gm = ui_mod._get_sub_gm
        ui_mod.run_context_agent = fake_context_agent
        ui_mod._get_gm = lambda u: StubGM()
        ui_mod._get_sub_gm = lambda u: StubGM()
        try:
            with self.client.stream(
                "POST",
                "/api/v1/chat",
                json={"message": "我悄悄靠近矿车", "attachments": []},
                cookies=cookies,
            ) as resp:
                self.assertEqual(resp.status_code, 200)
                events = self._consume(resp)
        finally:
            ui_mod.run_context_agent = orig_rca
            ui_mod._get_gm = orig_get_gm
            ui_mod._get_sub_gm = orig_get_sub_gm

        self.assertNotIn("error", [e["event"] for e in events], events)
        rule_updates = [
            e for e in events
            if e["event"] == "updates" and isinstance(e["data"], dict)
            and e["data"].get("stage") == "rules_engine"
        ]
        self.assertTrue(rule_updates, events)

        state = self.client.get("/api/v1/state", cookies=cookies).json()
        self.assertEqual(state["scene"]["location_id"], "minecart_track")
        self.assertEqual(len(state["dice_log"]), 1)
        self.assertEqual(state["dice_log"][0]["kind"], "skill_check")
        self.assertEqual(state["dice_log"][0]["dc"], 13)

    def test_module_rule_suggestion_overrides_generic_llm_candidate(self):
        import app as ui_mod

        user = register_user(self.client)
        cookies = user["cookies"]
        self.client.post("/api/v1/rules/module/start", json={"module_id": "ash_mine"}, cookies=cookies)

        def fake_context_agent(*args, **kwargs):
            yield {
                "type": "result",
                "retrieved_context": "",
                "bundle": {"debug": {"cache_plan": {}}, "prompt": "stub"},
                "steps": [],
                "agent_prompt": "stub",
                "curator_plan": {
                    "rule_candidate_actions": [{
                        "kind": "skill_check",
                        "skill": "stealth",
                        "dc": 12,
                        "reason": "generic stealth",
                    }],
                },
            }

        class StubGM:
            api_id = "stub"

            class Backend:
                model_name = "stub"
                last_usage = {}

            _backend = Backend()

            def curate_context(self, *args, **kwargs):
                return ""

            def respond_stream_with_tools(self, *args, **kwargs):
                yield {"type": "text", "text": "你贴着岩壁靠近废弃矿车。"}

        orig_rca = ui_mod.run_context_agent
        orig_get_gm = ui_mod._get_gm
        orig_get_sub_gm = ui_mod._get_sub_gm
        ui_mod.run_context_agent = fake_context_agent
        ui_mod._get_gm = lambda u: StubGM()
        ui_mod._get_sub_gm = lambda u: StubGM()
        try:
            with self.client.stream(
                "POST",
                "/api/v1/chat",
                json={"message": "我悄悄靠近矿车", "attachments": []},
                cookies=cookies,
            ) as resp:
                self.assertEqual(resp.status_code, 200)
                events = self._consume(resp)
        finally:
            ui_mod.run_context_agent = orig_rca
            ui_mod._get_gm = orig_get_gm
            ui_mod._get_sub_gm = orig_get_sub_gm

        self.assertNotIn("error", [e["event"] for e in events], events)
        state = self.client.get("/api/v1/state", cookies=cookies).json()
        self.assertEqual(state["scene"]["location_id"], "minecart_track")
        self.assertEqual(state["dice_log"][0]["dc"], 13)

    def test_failed_narration_checkpoint_survives_cold_kb_reload(self):
        self._assert_cold_checkpoint(stopped=False)

    def test_stopped_narration_checkpoint_survives_cold_kb_reload(self):
        self._assert_cold_checkpoint(stopped=True)

    def test_checkpoint_survives_optional_kb_import_failure(self):
        self._assert_cold_checkpoint(stopped=False, kb_unavailable=True)

    def _assert_cold_checkpoint(self, *, stopped, kb_unavailable=False):
        """Real DB/KB loading must preserve a settled potion across worker restarts."""
        from contextlib import nullcontext
        from unittest.mock import patch

        import app as ui_mod
        import chat_pipeline

        user = register_user(self.client)
        cookies, api_user = user["cookies"], user["body"]["user"]
        launch = self.client.post("/api/v1/rules/module/launch", json={"module_id": "ash_mine"}, cookies=cookies)
        self.assertEqual(launch.status_code, 200, launch.text)
        state = ui_mod._ensure_loaded(api_user, ensure_gm=False)
        state.data["player_character"]["hp"] = 1
        ui_mod._persist_runtime_checkpoint(state, api_user)
        context_calls = []

        async def context(ctx, **kwargs):
            if ctx.resume_action:
                async for event in original_context(ctx, **kwargs):
                    yield event
                return
            context_calls.append(ctx)
            ctx.bundle = {"prompt": "stub", "debug": {}}
            ctx.agent_result = {"steps": [], "curator_plan": {}}
            yield "agent", {"phase": "context", "status": "done"}

        attempts = []

        async def gm(ctx, **kwargs):
            attempts.append(ctx)
            if len(attempts) == 1:
                if stopped:
                    self.client.post("/api/v1/stop", cookies=cookies)
                    ui_mod._persist_chat_turn(api_user, ctx.state, ctx.message_for_model, "部分叙事",
                                              persist_user_id=ctx.persist_user_id,
                                              active_save_id=ctx.active_save_id, interrupted=True)
                    ctx.early_return = True
                    yield "done", {"interrupted": True, "status": ui_mod._payload_sse(api_user)}
                    return
                raise ConnectionError("synthetic narration failure")
            ctx.response = "伤口逐渐闭合。"
            yield "token", {"text": ctx.response}

        original_context = chat_pipeline.run_context_phase
        stub = type("GM", (), {"api_id": "stub"})()
        body = {"message": "我喝一瓶急救药剂", "action_id": "cold-retry", "action_turn": 0}
        with patch.object(ui_mod, "_get_gm", return_value=stub), \
                patch.object(ui_mod, "_get_sub_gm", return_value=stub), \
                patch.object(ui_mod, "_is_set_parser_enabled", return_value=False), \
                patch.object(chat_pipeline, "run_context_phase", context), \
                patch.object(chat_pipeline, "run_gm_phase", gm):
            kb_failure = patch("kb.save_kb.import_state", side_effect=RuntimeError("synthetic KB import failure"))
            with kb_failure if kb_unavailable else nullcontext():
                with self.client.stream("POST", "/api/v1/chat", json=body, cookies=cookies) as response:
                    events = self._consume(response)
            if not stopped:
                self.assertIn("error", [e["event"] for e in events], events)
            settled = self.client.get("/api/v1/state", cookies=cookies).json()
            self.assertGreater(settled["player_character"]["hp"], 1)
            self.assertEqual(settled["pending_action"]["id"], "cold-retry")
            ui_mod._invalidate_user_cache(api_user)
            cold = self.client.get("/api/v1/state", cookies=cookies).json()
            for key in ("pending_action", "player_character", "dice_log"):
                self.assertEqual(cold[key], settled[key], key)
            with self.client.stream("POST", "/api/v1/chat", json={**body, "retry": True}, cookies=cookies) as response:
                events = self._consume(response)
            self.assertNotIn("error", [e["event"] for e in events], events)
            final = self.client.get("/api/v1/state", cookies=cookies).json()
            self.assertEqual(final["player_character"]["hp"], settled["player_character"]["hp"])
            self.assertEqual(final["dice_log"], settled["dice_log"])
            self.assertEqual(final["turn"], 1)
            self.assertEqual(len(context_calls), 1)
            state = ui_mod._ensure_loaded(api_user, ensure_gm=False)
            state.data["player_character"]["hp"] = 0
            ui_mod._persist_runtime_checkpoint(state, api_user)
            ui_mod._invalidate_user_cache(api_user)
            dead = self.client.get("/api/v1/state", cookies=cookies).json()
            self.assertEqual(dead["player_character"]["hp"], 0)
            fork = self.client.post("/api/v1/branches/continue", json={
                "save_id": launch.json()["save_id"], "message_index": 2,
            }, cookies=cookies)
            self.assertEqual(fork.status_code, 200, fork.text)
            restored = self.client.get("/api/v1/state", cookies=cookies).json()
            self.assertEqual(restored["player_character"], final["player_character"])
            self.assertEqual(restored["dice_log"], final["dice_log"])
            self.assertEqual(restored["turn"], 1)
            self.assertEqual(restored["history"][-1]["content"], "伤口逐渐闭合。")

    def test_gm_json_ops_are_not_saved_as_player_visible_text(self):
        self._assert_gm_json_options_persist()

    def test_unified_recorder_retains_narrator_choices(self):
        from unittest.mock import patch

        with patch("chat_pipeline.gm._POSTPROC_MODE", "async"), patch(
            "chat_pipeline.gm._recorder_unified", return_value=True,
        ), patch("gm_serving.recorder_bridge.run_unified_recorder", return_value={
            "ops": [{"op": "set", "path": "player.current_location", "value": "矿车旁"}],
        }):
            self._assert_gm_json_options_persist()

    def _assert_gm_json_options_persist(self):
        import app as ui_mod

        user = register_user(self.client)
        cookies = user["cookies"]
        self.client.post("/api/v1/rules/module/start", json={"module_id": "ash_mine"}, cookies=cookies)

        def fake_context_agent(*args, **kwargs):
            yield {
                "type": "result",
                "retrieved_context": "",
                "bundle": {"debug": {"cache_plan": {}}, "prompt": "stub"},
                "steps": [],
                "agent_prompt": "stub",
                "curator_plan": {},
            }

        class StubGM:
            api_id = "stub"

            class Backend:
                model_name = "stub"
                last_usage = {}

            _backend = Backend()

            def curate_context(self, *args, **kwargs):
                return ""

            def respond_stream_with_tools(self, *args, **kwargs):
                yield {
                    "type": "text",
                    "text": (
                        "你在矿车旁找到一枚裂纹徽章。\n\n"
                        "```json\n"
                        "[{\"op\":\"question\",\"question\":\"下一步？\",\"options\":[\"继续搜索\",\"返回入口\"]}]\n"
                        "```"
                    ),
                }

        orig_rca = ui_mod.run_context_agent
        orig_get_gm = ui_mod._get_gm
        orig_get_sub_gm = ui_mod._get_sub_gm
        ui_mod.run_context_agent = fake_context_agent
        ui_mod._get_gm = lambda u: StubGM()
        ui_mod._get_sub_gm = lambda u: StubGM()
        try:
            with self.client.stream(
                "POST",
                "/api/v1/chat",
                json={"message": "搜查矿车", "attachments": []},
                cookies=cookies,
            ) as resp:
                self.assertEqual(resp.status_code, 200)
                events = self._consume(resp)
        finally:
            ui_mod.run_context_agent = orig_rca
            ui_mod._get_gm = orig_get_gm
            ui_mod._get_sub_gm = orig_get_sub_gm

        self.assertNotIn("error", [e["event"] for e in events], events)
        state = self.client.get("/api/v1/state", cookies=cookies).json()
        last = state["history"][-1]["content"]
        self.assertIn("裂纹徽章", last)
        self.assertNotIn("```json", last)
        self.assertNotIn('"op"', last)
        self.assertEqual(state["permissions"]["pending_questions"][0]["options"], ["继续搜索", "返回入口"])

    def test_game_console_keeps_rules_state_in_react_state(self):
        entry = Path(__file__).resolve().parents[3] / "frontend" / "src" / "entries" / "game-console.jsx"
        text = entry.read_text(encoding="utf-8")
        for key in ("ruleset", "player_character", "scene", "encounter", "dice_log"):
            self.assertIn(f"'{key}'", text)
        self.assertIn("'game-state-refresh'", text)
        self.assertIn("getRightTabForLocation", text)
        self.assertIn("location.hash", text)
        self.assertIn("if (nextAction) startRun(nextAction)", text)

    def test_game_panel_does_NOT_promote_relationship_to_user_card(self):
        """三层人物系统重构(test_active_entities_three_tier 落地)后,
        游戏面板**不应**再有"转为用户角色卡"按钮 / saveAsUserCard 函数。
        创建 / 提升用户角色卡只能在平台『角色卡』页操作。
        此测试反过来确认旧 promote 路径已彻底从 game-panels.jsx 移除。"""
        # 拆分后守卫读取范式:壳 + components/ 子目录全量拼接(负向断言覆盖只增)
        _root = Path(__file__).resolve().parents[3]
        _src = _root / "frontend" / "src"
        text = "\n".join(
            [(_src / "game-panels.jsx").read_text(encoding="utf-8")]
            + [p.read_text(encoding="utf-8")
               for p in sorted((_src / "components" / "game").glob("*.jsx"))])
        self.assertNotIn('data-tip="转为用户角色卡"', text,
            "game-panels.jsx 不应再有 data-tip='转为用户角色卡' 按钮")
        self.assertNotIn("saveAsUserCard", text,
            "saveAsUserCard 函数应已删除 — 游戏内不创建用户卡")
        self.assertNotIn("window.api.cards.myUpsert", text,
            "game-panels.jsx 不应再调 cards.myUpsert — 那是平台职责")
        # 平台一侧应仍保留 promote 路径(合法关注点)
        platform_text = "\n".join(
            [(_src / "platform-app.jsx").read_text(encoding="utf-8")]
            + [p.read_text(encoding="utf-8")
               for p in sorted((_src / "components" / "platform").glob("*.jsx"))])
        self.assertIn("promoteNpcToUserCard", platform_text,
            "平台『角色卡』页应保留 promoteNpcToUserCard")

    def test_game_ui_strips_state_ops_from_gm_messages(self):
        # game-app.jsx 模块化拆分后:壳 + components/game 全量拼接(NarrativeBlock 等已搬进组件目录)。
        _src = Path(__file__).resolve().parents[3] / "frontend" / "src"
        text = "\n".join(
            [(_src / "game-app.jsx").read_text(encoding="utf-8")]
            + [_p.read_text(encoding="utf-8")
               for _p in sorted((_src / "components" / "game").glob("*.jsx"))])
        self.assertIn("stripStateOpsForDisplay", text)
        self.assertIn("return stripNarrativeOps(text)", text)
        self.assertIn("const displayText = stripStateOpsForDisplay(text)", text)

    def test_gm_system_prompt_keeps_literal_json_examples(self):
        """通用 RPG 底座：system prompt 任何状态下都必须保留 JSON 写回示例（"op": "set" ...）
        不被 str.format 误解析；只有绑定到《我蕾穆丽娜不爱你》兼容老存档的 session 才注入
        柏林世界简介（world.json）。"""
        import agents.gm as gm_mod

        old_world = gm_mod._WORLD
        gm_mod._WORLD = {
            "setting": "测试世界",
            "current_situation": "测试局势",
            "current_berlin": {
                "atmosphere": "测试氛围",
                "risk_level": "低",
                "power_presence": ["测试势力"],
            },
        }
        try:
            # 1) 不绑定 state：world_section 必须为空（freeform / 通用底座）
            built_empty = gm_mod.GameMaster.__new__(gm_mod.GameMaster)._build_system()
            self.assertIn('"op": "set"', built_empty)
            self.assertNotIn("测试世界", built_empty)
            self.assertNotIn("测试局势", built_empty)

            # 2) 绑定默认柏林兼容 state：world_section 应注入 _WORLD 的设置
            from state import GameState
            g = GameState.new()
            g.data["world"]["time"] = "图卢兹失守后翌日，柏林"
            g.data["player"]["current_location"] = "柏林街头"
            g.data["history"] = [{"role": "assistant", "content": "前情提要"}]
            gm = gm_mod.GameMaster.__new__(gm_mod.GameMaster)
            gm._active_state = g
            built_berlin = gm._build_system()
            self.assertIn('"op": "set"', built_berlin)
            self.assertIn("测试世界", built_berlin)
            self.assertIn("测试局势", built_berlin)
        finally:
            gm_mod._WORLD = old_world


if __name__ == "__main__":
    unittest.main(verbosity=2)
