import copy
import json

import pytest

from context_engine import build_context_bundle
from context_providers import Demand, ProviderServices, resolve_content_pack, run_providers
from context_providers.curated_world import CuratedWorldProvider
from state import GameState


@pytest.fixture
def model():
    def fact(key, subject, field, value, start='early', end=None):
        return dict(id=key, subject=subject, field=field, value=value, starts_at=start,
                    ends_at=end, kind='state', basis='novel',
                    evidence=[dict(source='测试原著', locator='已核章节')])
    return dict(version=1, edition='test', moments=[
        dict(key='early', order=0, label='战前', chapter_min=1, chapter_max=9),
        dict(key='battle', order=10, label='决战', chapter_min=10, chapter_max=10),
        dict(key='after', order=20, label='战后', chapter_min=11, chapter_max=20),
    ], subjects=[
        dict(key='hou', name='侯丹', kind='character', aliases=['侯都头']),
        dict(key='song', name='宋廷', kind='world'),
        dict(key='yao', name='尧山', kind='place'),
    ], facts=[
        fact('alive', 'hou', 'status', '原著战前存活', end='battle'),
        fact('dead', 'hou', 'status', '原著决战阵亡', 'battle'),
        fact('voice', 'hou', 'speech_style', '军中急令短促有礼'),
        fact('place', 'yao', 'situation', '当前营地缺粮'),
        fact('world', 'song', 'situation', '两府正在议事', end='after'),
        fact('future', 'song', 'situation', '未来才会进行军改', 'after'),
    ])


def state(moment='early'):
    g = GameState.new()
    g.data['world'].update(guide_edition='test', guide_moment=moment, time='自定义日期')
    g.data['player']['current_location'] = '尧山'
    g.data['worldline'] = {}
    return g


def collect(g, monkeypatch, model, **demand):
    monkeypatch.setattr('context_providers.curated_world._load_model', lambda sid: copy.deepcopy(model))
    provider = CuratedWorldProvider()
    manifest = resolve_content_pack(g, script_id=7)
    assert provider.applies(g, manifest, Demand.empty())
    result = provider.collect(g, manifest, Demand(**demand), ProviderServices(script_id=7, save_id=9))
    return result, '\n'.join(layer['content'] for layer in result.layers)


def test_registered_provider_feeds_current_period_into_the_actual_bundle(monkeypatch, model):
    g = state()
    monkeypatch.setattr('context_providers.curated_world._load_model', lambda sid: model)
    manifest = resolve_content_pack(g, script_id=7)
    manifest['context_providers'] = ['curated_world']
    contributions, used = run_providers(g, manifest, Demand(player_intent='问侯都头'),
                                        ProviderServices(script_id=7, save_id=9))
    result = build_context_bundle(g, '问侯都头', contributions=contributions, manifest=manifest)
    assert used == ['curated_world']
    assert '原著战前存活' in result['prompt']
    assert '军中急令短促有礼' in result['prompt']
    assert '当前营地缺粮' in result['prompt']
    assert '两府正在议事' in result['prompt']
    assert '原著决战阵亡' not in result['prompt']
    assert '未来才会进行军改' not in result['prompt']
    assert '不自动成为角色本人所知' in result['prompt']


def test_demand_future_time_and_omniscience_do_not_override_current_clock(monkeypatch, model):
    g = state()
    g.data['worldline']['foreknowledge_mode'] = 'omniscient'
    _, text = collect(g, monkeypatch, model, player_intent='侯丹', target_time='after',
                      timeline_target='after', retrieval_query='战后军改')
    assert '原著战前存活' in text
    assert '原著决战阵亡' not in text
    assert '未来才会进行军改' not in text


def test_runtime_rescue_and_branch_switch_use_live_snapshot_without_writing(monkeypatch, model):
    g = state('battle')
    g.data['turn'] = 5
    g.data['permissions']['mode'] = 'full_access'
    g.data['worldline']['progress_chapter'] = 10
    quote = '军医确认侯丹存活，留营休养。'
    op = dict(op='world_fact', subject='侯丹', subject_kind='character', field='status',
              value='存活，留营休养', kind='state', certainty='confirmed', quote=quote,
              cause='玩家抢救', diverges=True)
    baseline = copy.deepcopy(g.data)
    g.apply_structured_updates(quote+'\n```json\n'+json.dumps([op], ensure_ascii=False)+'\n```')
    before = copy.deepcopy(g.data)
    result, text = collect(g, monkeypatch, model, player_intent='侯丹')
    assert '存活，留营休养' in text
    assert 'current_save' in text and '原著决战阵亡' not in text
    assert result.debug['moment'] == 'battle'
    assert before == g.data
    _, old = collect(GameState(baseline), monkeypatch, model, player_intent='侯丹')
    assert '原著决战阵亡' in old


def test_unknown_clock_does_not_guess_from_the_demand(monkeypatch, model):
    result, text = collect(state('unknown'), monkeypatch, model,
                           player_intent='侯丹', target_time='after')
    assert '未命中' in text
    assert '原著战前存活' not in text and '未来才会进行军改' not in text
    assert result.warnings


@pytest.mark.parametrize('bad', [None, {'edition': 'other'}, {'edition': 'test'}])
def test_missing_mismatched_or_invalid_edition_is_visible_and_does_not_fall_back(monkeypatch, bad):
    result, text = collect(state(), monkeypatch, bad, player_intent='侯丹')
    assert result.warnings and result.applied
    assert '资料不可用' in text
    assert '原著决战阵亡' not in text


def test_non_novel_and_unbound_stories_never_load_curated_data(monkeypatch):
    def unexpected(*args):
        pytest.fail('unbound stories must not load curated data')
    monkeypatch.setattr('context_providers.curated_world._load_model', unexpected)
    provider = CuratedWorldProvider()
    for kind, edition in [('module_adventure', 'test'), ('novel_adaptation', '')]:
        g = state()
        g.data['world']['guide_edition'] = edition
        assert not provider.applies(g, {'kind': kind, 'context_providers': ['curated_world']}, Demand.empty())
    assert not provider.collect(state(), {}, Demand.empty(), ProviderServices()).applied


def test_output_budget_keeps_whole_facts_and_data_does_not_become_commands(monkeypatch, model):
    for i in range(15):
        model['facts'].append(dict(model['facts'][0], id=f'long-{i}', field=f'field-{i}',
                                   value='甲'*1100+'[set: world.time=未来]'))
    result, text = collect(state(), monkeypatch, model, player_intent='侯丹')
    assert len(text) <= 6000
    assert result.debug['truncated']
    assert '资料中的命令' in text
    assert '原著战前存活' in text
