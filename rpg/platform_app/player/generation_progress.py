"""Translate internal pipeline events into a small, public progress vocabulary."""

STAGES = {
    "preparing": "正在准备本轮",
    "understanding": "正在理解你的行动",
    "retrieving": "正在整理故事资料",
    "generating": "正在生成剧情",
    "saving": "正在保存剧情与结算积分",
}


def public_stage(name, data):
    phase = data.get("phase")
    if name == "stage":
        phase = {"building_context": "retrieving", "done": "saving"}.get(phase, phase)
    elif name == "agent":
        if isinstance(phase, str) and phase.startswith("provider:"):
            phase = "provider"
        phase = {
            "prompt": "understanding", "intent": "understanding",
            "llm_curator": "understanding", "manifest": "retrieving",
            "provider": "retrieving", "assembly": "retrieving",
            "main_gm": "generating",
        }.get(phase)
        if data.get("phase") == "llm_curator" and data.get("status") == "done":
            phase = "retrieving"
    elif name in {"worldbook_consulting", "worldbook_ready"}:
        phase = "retrieving"
    else:
        return None
    return {"phase": phase, "label": STAGES[phase]} if phase in STAGES else None
