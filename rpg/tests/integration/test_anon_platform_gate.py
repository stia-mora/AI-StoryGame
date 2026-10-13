"""
test_anon_platform_gate.py — UI 审计任务 3 回归

防止再次出现：
1) data-loader 在匿名态下泄露 mock admin 用户
2) Platform.html / Game Console.html 未在加载完成后跳转 Login
3) /api/auth/me 给匿名返回 user!=null 让前端误判
"""
from __future__ import annotations

import unittest
from pathlib import Path

from tests.helpers import cleanup_test_users, make_client, register_user

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


class FrontendGateWiring(unittest.TestCase):
    """静态扫描前端文件，确认 gate 代码在位（防止 revert）。"""

    def test_data_loader_exposes_authed_flag(self):
        src = (FRONTEND / "src" / "data-loader.js").read_text(encoding="utf-8")
        self.assertIn("window.RPG_AUTH", src, "data-loader 必须暴露 window.RPG_AUTH 让 mount 同步读")
        self.assertIn("authed", src)
        self.assertIn("anonymizeUser", src, "匿名时必须脱敏 platform.user，否则 mock admin 漏到 UI")

    def test_data_loader_resolves_with_authed(self):
        src = (FRONTEND / "src" / "data-loader.js").read_text(encoding="utf-8")
        # bootstrap 应把 authed 传给 resolvers；同时检查异常路径也带上
        self.assertIn("readyResolvers.forEach", src)
        # 两条 resolve 路径（有 window.api / 没有 window.api）都要带 authed
        resolve_lines = [ln for ln in src.splitlines() if "readyResolvers.forEach" in ln]
        for ln in resolve_lines:
            self.assertIn("authed", ln, f"resolve 行必须传 authed：{ln.strip()}")

    def test_authenticated_loader_does_not_fall_back_to_mock_data(self):
        src = (FRONTEND / "src" / "data-loader.js").read_text(encoding="utf-8")
        self.assertIn("emptyPlatformFallback", src)
        self.assertIn("emptyGameStateFallback", src)
        self.assertIn("useDesignerFallback", src)
        self.assertIn("const allowMockFallback = !window.api || useDesignerFallback();", src)
        self.assertTrue(
            "const merged = allowMockFallback ? deepCopy(BASELINE.state) : emptyGameStateFallback();" in src
            or "const merged = allowMockFallback ? deepCopy(baseline().state) : emptyGameStateFallback();" in src,
            "登录态 /api/state partial merge 必须用空骨架，不能用 mock baseline",
        )
        self.assertIn("Object.assign(platform, emptyPlatformFallback(platform));", src)
        self.assertIn("catch (e) { platform.scripts = []; }", src)
        self.assertIn("catch (e) { platform.saves = []; }", src)
        self.assertIn("catch (e) { platform.recent_assets = []; }", src)

    def test_game_console_title_mock_only_for_anonymous_preview(self):
        # game-app.jsx 模块化拆分后:壳 + components/game 全量拼接(LeftRail 已搬进组件目录)。
        src = "\n".join(
            [(FRONTEND / "src" / "game-app.jsx").read_text(encoding="utf-8")]
            + [_p.read_text(encoding="utf-8")
               for _p in sorted((FRONTEND / "src" / "components" / "game").glob("*.jsx"))])
        self.assertIn("allowMockTitle", src)
        self.assertIn("window.RPG_AUTH && window.RPG_AUTH.authed", src)
        self.assertIn("window.MOCK_NOVEL && window.MOCK_NOVEL.script_title", src)

    def test_platform_entry_gates_on_authed(self):
        html = (FRONTEND / "Platform.html").read_text(encoding="utf-8")
        src = (FRONTEND / "src" / "entries" / "platform.jsx").read_text(encoding="utf-8")
        self.assertIn("src/entries/platform.jsx", html)
        self.assertIn("info.authed", src, "Platform entry 必须用 info.authed 判断")
        self.assertIn("Login.html", src, "未登录必须跳 Login.html")
        self.assertIn("offline", src, "?offline=1 设计预览旁路必须保留")

    def test_game_console_entry_gates_on_authed(self):
        html = (FRONTEND / "Game Console.html").read_text(encoding="utf-8")
        src = (FRONTEND / "src" / "entries" / "game-console.jsx").read_text(encoding="utf-8")
        self.assertIn("src/entries/game-console.jsx", html)
        self.assertIn("info.authed", src)
        self.assertIn("Login.html", src)

    def test_login_html_NOT_gated(self):
        # Login.html 自己不能跳 Login.html，否则死循环
        src = (FRONTEND / "Login.html").read_text(encoding="utf-8")
        self.assertNotIn("location.replace(\"Login.html\"", src)
        self.assertNotIn("location.href = \"Login.html\"", src)

    def test_authpage_honors_next_param_safely(self):
        auth_src = FRONTEND / "src" / "components" / "platform" / "AuthPage.jsx"
        src = auth_src.read_text(encoding="utf-8") if auth_src.exists() else (FRONTEND / "src" / "platform-app.jsx").read_text(encoding="utf-8")
        # 安全：必须有开放重定向防护
        self.assertIn("__nextOrDefault", src)
        self.assertIn("new URL(raw, location.href)", src)
        self.assertIn("u.origin !== location.origin", src, "next= 必须拒绝跨源 URL")
        self.assertIn("u.pathname + u.search + u.hash", src)


class BackendAnonContract(unittest.TestCase):
    """后端契约：匿名 me 返回 user=null（驱动前端 authed=false 分支）。
    如果哪天后端把这个改成 user={...guest...}，前端 gate 会失效。
    """

    @classmethod
    def setUpClass(cls):
        cleanup_test_users()
        cls.client = make_client()

    @classmethod
    def tearDownClass(cls):
        cleanup_test_users()

    def test_anonymous_me_returns_null_user(self):
        r = self.client.get("/api/v1/auth/me")
        self.assertEqual(r.status_code, 200, "/api/v1/auth/me 必须对匿名 200，否则前端连 gate 都跑不到")
        body = r.json()
        self.assertIsNone(body.get("user"), f"匿名 user 必须 null，实际：{body.get('user')}")

    def test_anonymous_business_endpoints_4xx(self):
        # Gate 假设这些接口对匿名 401/403，不能静默 200 漏数据
        for p in ("/api/v1/scripts", "/api/v1/saves", "/api/v1/library?path="):
            r = self.client.get(p)
            self.assertIn(r.status_code, (400, 401, 403), f"{p} 匿名必须 4xx")

    def test_authenticated_me_returns_user(self):
        u = register_user(self.client)
        r = self.client.get("/api/v1/auth/me", cookies=u["cookies"])
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.json().get("user"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
