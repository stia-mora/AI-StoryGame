"""Deterministic pacing signals from committed progress, scoped to managed play."""

from .experience import text

FAST_PREFIX = "【快进至下一处关键抉择】"


def clear_spurious_jump(state):
    """Discard old inferred jump proposals from ordinary fast actions."""
    from timeline_state import detect_time_directives

    world = state.data.get("world") or {}
    timeline = world.get("timeline") or {}
    pending = timeline.get("pending_jump") or {}
    raw = str(pending.get("raw") or "")
    if (
        raw.startswith(FAST_PREFIX)
        and not detect_time_directives(raw)
    ):
        timeline["pending_jump"] = None
        timeline["anchor_state"] = "locked"


def allow_curator_jump(state, user_input, target, user_id):
    """Managed ordinary action pacing cannot become an inferred time-jump request."""
    from .meter import current

    if target == (state.data.get("world") or {}).get("time"):
        return False
    return current(user_id) is None


RECORDING_GUIDE = """
【玩家收获与消耗记录】
逐项检查本轮正文已经实际交付、领取或消耗的物品、凭证和资源，不只记录地点与目标。
凭证、课表、钥匙、普通用品也要记录，不能因价值小而遗漏；仅听说、计划、尝试、未来奖励不算获得。
纯叙事存档使用 memory.resources：新获得且尚未记录的物品用 append，value 为真实物品名称及必要描述。
正文明确确认玩家实际携带的旧凭证若尚未入账，可以补录已确认的持有事实；快照已有同一物品时不得重复增加。
消耗或交走资源时更新其实际剩余情况，保留其他已有资源；不能因为展示清单而凭空恢复消耗品。
只保存正文已确认的事实，不编写数量、能力、奖励或未来情报。

【每轮六类状态核对】
以下是玩家入口追加的合法状态字段，与基础字段一同使用；禁止写身份姓名、权限或历史的限制仍然有效。
局势：实际地点、时间、天气、已公开的新事件写入 player.current_location / world.time / world.weather / world.known_events。
角色：已测定或实际成长的武魂、先天魂力、当前魂力、魂环、伤势等写入 player.martial_soul / player.innate_soul_power / player.soul_power / player.soul_rings / player.injury；实际学会的技巧写入 memory.abilities。
背包：真正交付、消耗、转交的物品与资源，写清数量、归属与余量；不得用未来奖励顶替已获得物品。
人物：已认识的人和本轮确认的关系、态度、约定写入 relationships.<人物名>，保留已知关系，不因问候就制造重大亲密或仇恨。
本轮与玩家实际交流的具名人物，即使关系尚无变化，也要保存其已知称呼、身份与“相识”等已发生事实；不能只在正文提及却让人物页保持空白。不得从原著未来资料补入尚未接触的人物。
任务：接取、推进、完成、失败或暂缓的任务写入 memory.tasks.<稳定任务名>，value 为 {"name":"任务名","description":"已知目标","status":"active|completed|failed|paused","progress":"本轮确认的进展"}。完成后保留记录，只有奖励实际交付才另记资源。
世界线：确已达成的成长或分支里程碑追加 memory.milestones，value 为 {"name":"节点名称","description":"实际结果及选择造成的影响","status":"completed"}；已公开的事件同步 world.known_events。计划、未来情报、可能后果不算已达成。
以给出的现有状态为基线逐项查漏。六类不必强行全变，未变化的字段不写；但正文有实质变化时不能漏记，也不能用改写同一事实冒充新进展。
"""


def context(view, message):
    recent = (view.get("journey") or [])[-3:]
    quiet = 0
    for step in reversed(recent):
        meaningful = [c for c in step.get("changes", []) if c.get("kind") != "时间"]
        if meaningful or step.get("gains") or step.get("losses") or step.get("events"):
            break
        quiet += 1
    fast = message.startswith(FAST_PREFIX)
    return dict(fast=fast, quiet_turns=quiet, location=text(view["status"].get("location")))


def instructions(run):
    signal = getattr(run, "pacing", {})
    lines = [
        "【玩家回合推进约定】",
        "先落实玩家本轮明确行动，写出结果或真实阻碍，再停在下一处值得玩家决定的节点。",
        "默认按完整场景推进：一次付费回合至少完成一段有明确结果的行动。到达、询问、办理、领取与安全行程通常属于同一段，不要每动一下就停。",
        "按本局叙事篇幅目标展开，通常完成2—3个相连节拍：实际行动、人物回应、结果与下一处局势。增加内容应带来新信息和有效进展，不只扩写动作神态；不在下一句答复、一次盖印或普通交接前无故停笔。",
        "普通问路、取信、证明、收拾行李、行程等连续低风险步骤合并叙述，不把每个手续拆成一个付费回合。",
        "两项可并行且无重大代价的日常手续，一并处理；其先后顺序不是值得停下来询问的抉择。",
        "快进是合并普通行动与自然耗时，不是申请修改时间线。同一日内拜访、登记和普通行程直接落实，不能再次收费询问是否确认时间跳跃；只有明确跳到某时点或章节才走跳跃审查。",
        "玩家已经选择申请工读、登记、报名等路线时，通常的清扫杂务、填写资料和核验属于该行动的普通步骤；可以说明并落实，不再专门问一轮是否愿意办理。效忠阵营、长期债务、大额付款或危险承诺仍须另行选择。",
        "觉醒、检测、报名等已获授权的普通仪式要在本轮完整结束并确认结果，不能停在抬手、触碰、排队或等待回答。入学办完普通核验、安顿、课表与基本安排后再询问方向。",
        "修炼按一次训练或数日常规练习推进，旅途概述到目的地，交流得到明确答复或关系反馈，探索带回已查明的线索。不能以观察一下、再问一项、等别人说完充当整轮进展。",
        "NPC主动回应并提供自己知道的事实。未设定的普通亲属、住址、日常安排可合理补足并记入状态，不要求玩家替NPC编答案。",
        "重大代价、战斗、机缘争夺、阵营和亲密关系等不可逆决定必须留给玩家；不能擅自跳过、获胜或授予奖励。",
        "若行动受阻，本轮说明具体原因，给出可执行的替代路径，不能再重复同一轮背景追问。",
        "正文以结果为中心，避免反复复述环境、已完成手续和上一轮选项。已发生的变化仍须写入状态。",
        "本轮尽量让明确行动带来多种有因果的变化：推进目标时同时处理合理的成长、资源、人物互动或任务进展。每轮至少兑现一个新的实质结果；不强制六类全变，不为更新面板捏造奖励、境界、关系或世界线偏离。",
        '正文之后必须追加 ```json 围栏保存本轮新事实：[{"op":"set","path":"player.current_location","value":"实际新地点"},{"op":"set","path":"memory.current_objective","value":"下一步目标"},{"op":"set","path":"relationships.实际已知人物","value":"已确认的关系"}]。这里只是格式示例，仅写确实变化的字段和事实；物品、能力使用实际状态路径写回，不输出示例值。',
    ]
    if signal.get("quiet_turns", 0) >= 2:
        lines.append(
            f"已连续{signal['quiet_turns']}轮没有已提交的实质进展。本轮优先兑现当前行动，结束重复准备，提供新的结果或明确替代路径。"
        )
    if signal.get("fast"):
        lines.append(
            "玩家已选择快进：在其明确授权的行动范围内，概述沿途日常步骤和耗时，直接抵达下一处关键抉择；遇到重大风险或机缘须立即停下供选择。"
        )
    lines.append(
        '【本轮最终输出检查】保存真实状态变化后，必须提供四项不同的、符合新现场的具体行动。每项都是一段完整行动，包含目标和可执行步骤，并明确推进到结果或下一关键节点。首项直接推进主目标，合并办理及其后安全行程；所需普通义务一并写在选项中，不让点击后再确认同一义务。其余是有收获的探索、完整交流或训练、安全替代路线。禁止把问时间、看课表、走到门口、单纯等候拆成选项；若确需等候，应包含等候期间的合理行动及收到结果后的下一步。选项只授权其写明的行动；高风险战斗、机缘争夺、不可逆付出仍停下选择，不自动获胜或拿到机缘。在结尾 JSON 数组加入 {"op":"question","question":"下一段故事，你想如何推进？","options":["完整行动一","完整行动二","完整行动三","完整行动四"]}；也可在正文末尾写四项编号列表。不要输出占位符，不得省略选项。'
    )
    lines.append(RECORDING_GUIDE)
    lines.append(
        "【首轮与后续选项质量】开场也必须在本次回复中给出四个现场行动。"
        "逐项写清去哪个已公开地点、找哪个已登场人物或处理哪件已知事务，并说明目的及已知条件或代价。"
        "不要只写推进主线、探索周围、与人交流、稳妥准备；不要虚构目的地、联系人、奖励或保证成功。"
    )
    return "\n".join(lines)
