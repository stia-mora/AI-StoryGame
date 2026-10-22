"""Fail fast on missing shared production credentials and canonical mail origin."""
import os
from urllib.parse import urlsplit


def validate():
    from core.config import effective_auth_required, is_local_mode

    if is_local_mode():
        if os.getenv("RPG_ENV", "").lower() in {"prod", "production"}:
            raise RuntimeError("生产环境必须设置 RPG_DEPLOYMENT_MODE=server")
        return
    if not effective_auth_required():
        raise RuntimeError("生产模式必须启用 RPG_REQUIRE_AUTH=1")
    for name in ("RPG_MASTER_KEY", "EMAIL_CODE_SECRET"):
        if len(os.getenv(name, "").strip()) < 32:
            raise RuntimeError(f"生产模式必须设置稳定的 {name}（至少 32 字符）")
    url = urlsplit(os.getenv("PUBLIC_BASE_URL", ""))
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
        raise RuntimeError("PUBLIC_BASE_URL 必须是本站公网 HTTPS 源地址")
    if not os.getenv("RPG_CORS_ORIGINS", "").strip() or "*" in os.getenv("RPG_CORS_ORIGINS", ""):
        raise RuntimeError("生产模式必须设置明确的 RPG_CORS_ORIGINS")
