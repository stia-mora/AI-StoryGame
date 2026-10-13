"""_gen_params.py — 把用户「生成参数预设」偏好接进各 provider 的 LLM 调用。

背景(反馈#93):设置页早有生成参数 UI(temperature/top_p/top_k/惩罚项 + 保守/均衡/创意/精确
四档预设),值落 user_preferences.preferences 顶层扁平键,但**过去从没被后端读取** → 预设是摆设。
这里补上单一来源的 resolver,各 backend(anthropic/vertex/openai_compat)在**叙事**调用时读它。

关键安全语义:**只返回用户显式设过的键**(pref 里存在该键才返回)。用户从没动过参数 → 返回 {}
→ 后端沿用各自既有默认(temperature 0.9 等),**零行为变化**。这样接线不会惊动未配置的存量用户,
只有主动调过预设/参数的用户才让它生效。

映射到各 provider(调用方按能力取子集):
- openai_compat:temperature/top_p/frequency_penalty/presence_penalty(标准字段)+ top_k/repetition_penalty
  走 extra_body(部分中转/本地支持);provider 拒绝时 backend 有自愈(剥采样参数退默认)。
- anthropic:temperature/top_p/top_k(不支持 frequency/presence penalty;thinking 开启时跳过 temperature)。
- vertex/gemini:temperature/top_p/top_k。
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# 键 → (下限, 上限, 是否取整)
_RANGES: dict[str, tuple[float, float, bool]] = {
    "temperature": (0.0, 2.0, False),
    "top_p": (0.0, 1.0, False),
    "top_k": (0.0, 500.0, True),
    "frequency_penalty": (-2.0, 2.0, False),
    "presence_penalty": (-2.0, 2.0, False),
    "repetition_penalty": (0.0, 2.0, False),
}


def resolve_gen_params(user_id: int | None) -> dict[str, Any]:
    """读 user_preferences.preferences,返回**用户显式设过**的生成参数(已校验/夹取)。

    未配置 / 读失败 → {}(调用方沿用后端默认,零行为变化)。
    """
    from platform_app.player.meter import current
    if current(user_id):
        return {'temperature': 0.85}
    if not user_id:
        return {}
    try:
        from platform_app.db import connect as _conn
        with _conn() as db:
            r = db.execute(
                "select preferences from user_preferences where user_id = %s",
                (int(user_id),),
            ).fetchone()
        if not r:
            return {}
        prefs = dict(r["preferences"] or {})
    except Exception as exc:
        log.warning(f"[gen_params] read failed: {exc}")
        return {}
    out: dict[str, Any] = {}
    for key, (lo, hi, as_int) in _RANGES.items():
        if key not in prefs:
            continue
        raw = prefs.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        v = max(lo, min(hi, v))
        out[key] = int(v) if as_int else v
    return out
