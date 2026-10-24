"""Render NPC cards from the same branch-bound dated facts as the play guide."""
from __future__ import annotations

from collections import Counter

from .curated_world import _load_model


def current_cards(state, *, script_id, save_id, scan_text, priority_text=''):
    from context_engine.helpers import _neutralize_state_write_tags
    from platform_app.player.guide_world import WorldQueries

    data = getattr(state, 'data', state) or {}
    edition = (data.get('world') or {}).get('guide_edition')
    debug = dict(edition=edition, moment=None, fact_ids=[], truncated=False)
    if not script_id:
        return {}, '人物当期资料缺少绑定剧本，不使用静态卡补齐。', debug
    try:
        model = _load_model(script_id)
        if not isinstance(model, dict) or model.get('edition') != edition:
            return {}, '人物当期资料版本不可用，不使用旧卡或终局卡补齐。', debug
        # Use the in-flight branch, never a later game_sessions snapshot. A
        # global/omniscient setting cannot reveal future NPC states here.
        world = WorldQueries(model, data, script_id=script_id, save_id=save_id or 0, allow_future=False)
    except (ValueError, TypeError):
        return {}, '人物当期资料未通过校验，不使用静态卡补齐。', debug
    if world.current is None:
        return {}, '人物当前时点未命中，只依存档既成事实，不猜人物阶段。', debug
    debug['moment'] = world.current.key
    relevant = [s for s in world.subjects.values() if s.kind == 'character'
                and any(name in scan_text for name in world.known_names(s))]
    relevant.sort(key=lambda s: not any(name in priority_text for name in world.known_names(s)))
    staged = []
    for subject in relevant[:8]:
        result = world.query(dict(tool='get_character', query=subject.key, limit=12))
        debug['truncated'] |= result.get('truncated', False)
        if not result['facts']:
            continue
        grouped = {}
        other = []
        for row in result['facts']:
            # Preserve provenance: a post-divergence baseline is a comparison,
            # not proof that the current save acquired that office or injury.
            labels = []
            if row['applicability'] == 'baseline_after_divergence':
                labels.append('分歧后原著对照')
            elif row['basis'] == 'history':
                labels.append('史籍对照')
            elif row['basis'] == 'save':
                labels.append('本存档')
            if row['certainty'] != 'confirmed':
                labels.append({'reported': '所报', 'inferred': '归纳或推断', 'disputed': '有争议'}[row['certainty']])
            value = ('【'+'／'.join(labels)+'】' if labels else '') + row['value']
            value = _neutralize_state_write_tags(value)
            field = row['field']
            if field in ('name', 'alias'):
                continue
            if field in ('identity', 'appearance', 'personality', 'speech_style', 'background'):
                grouped.setdefault(field, []).append(value)
            else:
                other.append(value)
            debug['fact_ids'].append(row['id'])
        display = world.display_name(subject, world.current)
        card = dict(
            aliases=world.known_names(subject),
            **{field: '\n'.join(grouped.get(field, [])) for field in
               ('identity', 'appearance', 'personality', 'speech_style', 'background')},
            current_status='\n'.join(other),
            # Static dialogue samples and secrets can themselves encode a late
            # personality or death. Only current dated facts are rendered.
            secrets='', sample_dialogue=[],
        )
        staged.append((display, card))
    # A recorded rename can create two currently visible namesakes. Keep both
    # cards; dictionary assignment by the bare name would silently merge them.
    counts = Counter(name for name, _ in staged)
    cards = {}
    for index, (name, card) in enumerate(staged, start=1):
        if counts[name] > 1:
            qualifier = next((n for n in card['aliases'] if n != name), f'同名人物{index}')
            name = f'{name}〔{qualifier}〕'
        while name in cards:
            name += f'〔同名人物{index}〕'
        cards[name] = card
    debug['truncated'] |= len(relevant) > 8
    return cards, '', debug
