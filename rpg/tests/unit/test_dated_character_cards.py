import copy
import json

import pytest

from context_engine import build_context_bundle
from context_providers import Demand, ProviderServices, resolve_content_pack, run_providers
from state import GameState


@pytest.fixture
def model():
    def fact(fid, field, value, start='early', end=None, subject='hou'):
        return dict(id=fid, subject=subject, field=field, value=value, starts_at=start,
                    ends_at=end, kind='state', basis='novel', evidence=[dict(source='原著', locator='已核章节')])
    return dict(version=1, edition='cards-test', moments=[
        dict(key='early', order=0, label='战前', chapter_min=1, chapter_max=9),
        dict(key='battle', order=10, label='战中', chapter_min=10, chapter_max=10),
        dict(key='after', order=20, label='战后', chapter_min=11, chapter_max=20),
    ], subjects=[dict(key='hou', name='侯丹', kind='character', aliases=['侯都头'])], facts=[
        fact('early-id', 'identity', '当期准备将', end='battle'),
        fact('alive', 'status', '战前存活', end='battle'),
        fact('early-personality', 'personality', '战前尚思归乡', end='battle'),
        fact('early-voice', 'speech_style', '旧日军中粗直', end='battle'),
        fact('late-id', 'identity', '战后追封', 'after'),
        fact('death', 'status', '原著决战阵亡', 'battle'),
        fact('late-voice', 'speech_style', '终局话风不能回填', 'after'),
    ])


def state(moment='early'):
    g = GameState.new()
    g.data['world'].update(guide_edition='cards-test', guide_moment=moment, time='自定日期')
    g.data['worldline'] = dict(progress_chapter=1)
    g.data['player'].update(name='随军小吏', current_location='营地')
    return g


def collect(g, model, monkeypatch, *, anchors=(), **demand):
    import context_engine

    def unexpected(*args, **kwargs):
        pytest.fail('dated NPC cards must never fall back to static character cards')

    monkeypatch.setattr(context_engine, '_load_characters', unexpected)
    monkeypatch.setattr('context_providers.dated_characters._load_model', lambda sid: copy.deepcopy(model))
    monkeypatch.setattr('context_providers.novel._read_progress_and_mode', unexpected)
    monkeypatch.setattr('context_providers.novel._extract_anchor_npc_names', lambda *a: list(anchors))
    manifest = resolve_content_pack(g, script_id=7)
    manifest['context_providers'] = ['novel_characters']
    contributions, used = run_providers(g, manifest, Demand(**demand), ProviderServices(script_id=7, save_id=9))
    assert used == ['novel_characters']
    result = contributions[0]
    assert result.applied, result.warnings
    prompt = build_context_bundle(g, demand.get('player_intent', ''), contributions=contributions, manifest=manifest)['prompt']
    return result, prompt


def test_current_voice_identity_and_personality_reach_actual_bundle_without_static_fallback(monkeypatch, model):
    result, prompt = collect(state(), model, monkeypatch, player_intent='问侯都头')
    assert '当期准备将' in prompt and '战前存活' in prompt
    assert '战前尚思归乡' in prompt and '旧日军中粗直' in prompt
    assert '战后追封' not in prompt and '原著决战阵亡' not in prompt
    assert '终局话风' not in prompt and '不从静态卡补齐' in prompt
    assert result.debug['moment'] == 'early'


def test_expired_fields_stay_unknown_even_with_omniscient_mode_and_future_demand(monkeypatch, model):
    g = state('battle')
    g.data['worldline'].update(progress_chapter=99, foreknowledge_mode='omniscient')
    _, prompt = collect(g, model, monkeypatch, player_intent='侯丹', target_time='after')
    assert '原著决战阵亡' in prompt
    assert '当期准备将' not in prompt and '战前尚思归乡' not in prompt
    assert '旧日军中粗直' not in prompt and '终局话风' not in prompt


@pytest.mark.parametrize('bad', [None, {'edition': 'different'}, {'edition': 'cards-test'}])
def test_unavailable_data_emits_warning_without_loading_static_fields(monkeypatch, bad):
    result, prompt = collect(state(), bad, monkeypatch, player_intent='侯丹')
    assert result.warnings and '静态卡补齐' in prompt
    assert '原著决战阵亡' not in prompt


def test_unknown_clock_does_not_guess_from_target_time(monkeypatch, model):
    g = state('unknown')
    g.data['worldline'] = {}
    result, prompt = collect(g, model, monkeypatch, player_intent='侯丹', target_time='after')
    assert result.warnings and '时点未命中' in prompt
    assert '当期准备将' not in prompt and '原著决战阵亡' not in prompt


def test_rescue_branch_and_rename_are_read_only_and_keep_baseline_as_comparison(monkeypatch, model):
    g = state('battle')
    g.data['turn'] = 5
    g.data['permissions']['mode'] = 'full_access'
    g.data['worldline']['progress_chapter'] = 10
    baseline = copy.deepcopy(g.data)
    quote = '军医确认侯丹存活，已改名侯安。'
    ops = [dict(op='world_fact', subject='侯丹', subject_kind='character', kind='state', field=field,
                value=value, certainty='confirmed', quote=quote, cause='玩家救治与本人改名', diverges=True)
           for field, value in [('status', '存活，留营休养'), ('name', '侯安')]]
    g.apply_structured_updates(quote+'\n```json\n'+json.dumps(ops, ensure_ascii=False)+'\n```')
    before = copy.deepcopy(g.data)
    _, prompt = collect(g, model, monkeypatch, player_intent='问侯都头')
    assert '【侯安】' in prompt and '存活，留营休养' in prompt
    assert '原著决战阵亡' not in prompt and before == g.data
    _, old = collect(GameState(baseline), model, monkeypatch, player_intent='侯丹')
    assert '原著决战阵亡' in old and '侯安' not in old


def test_dated_rename_does_not_expose_future_name_and_old_anchor_uses_current_name(monkeypatch, model):
    model['facts'] += [
        dict(model['facts'][0], id='name-before', field='name', value='侯丹'),
        dict(model['facts'][0], id='name-after', field='name', value='侯安', starts_at='battle', ends_at=None),
    ]
    _, early = collect(state(), model, monkeypatch, player_intent='寻找侯安')
    assert '当期准备将' not in early and '【侯安】' not in early
    _, late = collect(state('battle'), model, monkeypatch, player_intent='继续', anchors=['侯丹'])
    assert '【侯安】' in late and '【侯丹】' not in late


def test_player_own_name_or_alias_never_becomes_a_second_npc_via_pending_anchor(monkeypatch, model):
    g = state()
    g.data['player'].update(name='玩家自取名', aliases=['侯丹'])
    result, _ = collect(g, model, monkeypatch, player_intent='问侯都头', anchors=['侯丹'])
    assert result.debug['cards_count'] == 0


def test_target_entities_and_active_entities_can_select_current_cards(monkeypatch, model):
    _, prompt = collect(state(), model, monkeypatch, player_intent='询问伤势', target_entities=['侯丹'])
    assert '战前存活' in prompt
    g = state()
    g.data['active_entities'] = [{'name': '侯都头'}]
    _, prompt = collect(g, model, monkeypatch, player_intent='继续')
    assert '战前存活' in prompt


def test_current_request_is_not_crowded_out_by_old_history_names(monkeypatch, model):
    others = []
    for i in range(9):
        sid, name = f'other-{i}', f'旧人甲{i}'
        others.append(name)
        model['subjects'].insert(0, dict(key=sid, name=name, kind='character'))
        model['facts'].append(dict(model['facts'][0], id=f'other-fact-{i}', subject=sid))
    g = state()
    g.data['memory']['current_objective'] = '、'.join(others)
    _, prompt = collect(g, model, monkeypatch, player_intent='侯丹')
    assert '战前存活' in prompt


def test_current_namesakes_created_by_rename_keep_distinct_cards(monkeypatch, model):
    model['subjects'].append(dict(key='other', name='侯安', kind='character'))
    model['facts'] += [
        dict(model['facts'][0], id='old-name', field='name', value='侯丹'),
        dict(model['facts'][0], id='new-name', field='name', value='侯安', starts_at='battle', ends_at=None),
        dict(model['facts'][0], id='other-state', subject='other', field='status',
             value='另一同名者当前在世', starts_at='battle', ends_at=None),
    ]
    g = state('battle')
    g.data['active_entities'] = [{'name': '侯安'}]
    result, prompt = collect(g, model, monkeypatch, player_intent='侯都头与侯安各自如何')
    assert result.debug['cards_count'] == 2
    assert '原著决战阵亡' in prompt and '另一同名者当前在世' in prompt
