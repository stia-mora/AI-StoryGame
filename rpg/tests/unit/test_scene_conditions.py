import copy
import json

import pytest
from pydantic import ValidationError

from platform_app.player.guide_world import GuideWorld, WorldQueries
from state import GameState


@pytest.fixture
def model():
    evidence = [dict(source='测试故事', locator='已核段落')]
    def fact(key, subject, field, value, start='start', end=None):
        return dict(id=key, subject=subject, field=field, value=value, starts_at=start,
                    ends_at=end, kind='state', basis='novel', evidence=evidence)
    return dict(version=1, edition='conditions-test', moments=[
        dict(key=key, order=i, label=key, chapter_min=i+1, chapter_max=i+1)
        for i, key in enumerate(['start', 'choice', 'after', 'end'])
    ], subjects=[dict(key='hou', name='侯丹', kind='character'),
                 dict(key='ferry', name='渡口', kind='place')], facts=[
        fact('alive', 'hou', 'status', '存活', end='after'),
        fact('dead', 'hou', 'status', '原著阵亡', 'after'),
        fact('boats', 'ferry', 'situation', '尚有小舟'),
    ], beats=[
        dict(key='rescue', title='战阵救援选择', starts_at='choice', ends_at='after',
             subjects=['hou', 'ferry'], pressure='尚须核敌情、伤势与救援通路。', evidence=evidence,
             conditions=[dict(key='life', label='伤者状态', fact_ids=['alive'],
                              recheck='状态改变后重估救护与后续处置。'),
                         dict(key='boats', label='可用舟船', fact_ids=['boats'], recheck='重估渡运。'),
                         dict(key='authority', label='行动权限', fact_ids=[], recheck='核当事人权限。')],
             choices=['可核实道路后提出救护办法。']),
        dict(key='aftercare', title='战后处置核验', starts_at='after', ends_at='end',
             subjects=['hou', 'ferry'], pressure='先核本分支实际伤亡。', evidence=evidence,
             conditions=[dict(key='life', label='人员状态', fact_ids=['dead'], recheck='按实际伤情处置。'),
                         dict(key='boats', label='可用舟船', fact_ids=['boats'], recheck='重估渡运。')],
             choices=['可按核实结果安排照护或善后。']),
    ])


def state(moment='after'):
    g = GameState.new()
    g.data['world'].update(guide_edition='conditions-test', guide_moment=moment, time=moment)
    g.data['worldline'] = {}
    g.data['turn'] = 3
    g.data['permissions']['mode'] = 'full_access'
    return g


def query(model, g, **args):
    return WorldQueries(model, g.data, script_id=1, save_id=2).query(dict(tool='get_scene_conditions', **args))


def test_only_current_window_is_a_candidate_and_manual_requirements_stay_unverified(model):
    g = state('choice')
    row = query(model, g)['facts'][0]
    assert row['key'] == 'rescue' and row['state'] == 'candidate'
    assert [c['state'] for c in row['conditions']] == ['baseline', 'baseline', 'unverified']
    assert '原著阵亡' not in json.dumps(row, ensure_ascii=False)
    assert query(model, state('after'))['facts'][0]['key'] == 'aftercare'


def test_saved_rescue_changes_only_its_dependency_without_advancing_or_executing(model):
    g = state()
    prose = '军医确认侯丹尚活，已经止血。'
    op = dict(op='world_fact', subject='侯丹', field='status', value='存活，已经止血',
              quote=prose, cause='玩家实际救护', diverges=True)
    g.apply_structured_updates(prose+'\n```json\n'+json.dumps([op], ensure_ascii=False)+'\n```')
    before = copy.deepcopy(g.data)
    row = query(model, g)['facts'][0]
    assert [c['state'] for c in row['conditions']] == ['reassess', 'baseline']
    assert row['conditions'][0]['observations'][0]['current']['cause'] == '玩家实际救护'
    assert '存活，已经止血' in json.dumps(row, ensure_ascii=False)
    assert g.data == before


@pytest.mark.parametrize('mode', ['report', 'proposal', 'pending'])
def test_report_plan_and_pending_write_cannot_confirm_a_changed_premise(model, mode):
    g = state()
    prose = '有人声称侯丹仍活，拟明日派人去救。'
    op = dict(op='world_fact', subject='侯丹', field='proposal', value='拟派人去救', quote=prose)
    if mode == 'report':
        op.update(field='report', certainty='reported', value='有人称仍活')
    if mode == 'pending':
        op.update(field='status', value='存活')
        g.data['permissions']['mode'] = 'read_only'
    g.apply_structured_updates(prose+'\n```json\n'+json.dumps([op], ensure_ascii=False)+'\n```')
    assert query(model, g)['facts'][0]['conditions'][0]['state'] == 'baseline'


def test_future_and_unknown_clock_never_disclose_the_next_beat(model):
    g = state('start')
    assert not query(model, g, query='aftercare')['facts']
    assert 'unavailable' in query(model, g, at='after')
    allowed = WorldQueries(model, g.data, script_id=1, save_id=2, allow_future=True)
    assert allowed.query(dict(tool='get_scene_conditions', at='after'))['facts'][0]['key'] == 'aftercare'
    assert not query(model, state('unknown'))['facts']


def test_actual_provider_bundle_uses_current_conditions_despite_future_demand(model, monkeypatch):
    from context_engine import build_context_bundle
    from context_providers import Demand, ProviderServices, resolve_content_pack, run_providers

    monkeypatch.setattr('context_providers.curated_world._load_model', lambda _: model)
    g = state('choice')
    before = copy.deepcopy(g.data)
    manifest = resolve_content_pack(g, script_id=1)
    manifest['context_providers'] = ['curated_world']
    contributions, used = run_providers(g, manifest, Demand(player_intent='救侯丹', target_time='after'),
                                        ProviderServices(script_id=1, save_id=2))
    assert used == ['curated_world']
    assert contributions[0].debug['scene_keys'] == ['rescue']
    bundle = build_context_bundle(g, '救侯丹', contributions=contributions, manifest=manifest)
    layer = next(row for row in contributions[0].layers if row['id'] == 'scene_conditions')
    assert layer['content'] in bundle['prompt']
    assert '战阵救援选择' in layer['content'] and '原著阵亡' not in layer['content']
    assert g.data == before


@pytest.mark.parametrize('cap', [800, 1200])
def test_constrained_gm_context_does_not_receive_half_a_scene_premise(model, monkeypatch, cap):
    from context_engine import build_context_bundle, core
    from context_providers import Demand, ProviderServices, resolve_content_pack, run_providers

    monkeypatch.setattr('context_providers.curated_world._load_model', lambda _: model)
    budget = core.layer_char_budget
    monkeypatch.setattr(core, 'layer_char_budget',
                        lambda key: (cap, True) if key == 'scene_conditions' else budget(key))
    g = state('choice')
    manifest = resolve_content_pack(g, script_id=1)
    manifest['context_providers'] = ['curated_world']
    contributions, _ = run_providers(g, manifest, Demand(), ProviderServices(script_id=1))
    scene = next(row for row in contributions[0].layers if row['id'] == 'scene_conditions')
    assert len(scene['content']) > cap
    bundle = build_context_bundle(g, '救侯丹', contributions=contributions, manifest=manifest)
    assert '场景条件未完整载入' in bundle['prompt']
    assert '"conditions":' not in bundle['prompt'] and '"pressure":' not in bundle['prompt']
    row = next(r for r in bundle['debug']['layers'] if r['id'] == 'scene_conditions')
    assert row['truncated'] and row['chars'] <= cap and row['original_chars'] == len(scene['content'])


def test_history_does_not_receive_later_rescue_and_result_is_bounded(model):
    g = state('after')
    prose = '军医确认侯丹尚活。'
    op = dict(op='world_fact', subject='侯丹', field='status', value='存活', quote=prose)
    g.apply_structured_updates(prose+'\n```json\n'+json.dumps([op], ensure_ascii=False)+'\n```')
    assert query(model, g, at='choice')['facts'][0]['conditions'][0]['state'] == 'baseline'
    result = query(model, g)
    assert len(json.dumps(result, ensure_ascii=False)) <= 6000


def test_unconfirmed_entity_status_cannot_replace_a_confirmed_narration_record(model):
    g = state()
    g.data['active_entities'] = [dict(name='侯丹', status='有人说已康复')]
    assert query(model, g)['facts'][0]['conditions'][0]['state'] == 'unverified'
    prose = '军医确认侯丹存活。'
    op = dict(op='world_fact', subject='侯丹', field='status', value='存活', quote=prose)
    g.apply_structured_updates(prose+'\n```json\n'+json.dumps([op], ensure_ascii=False)+'\n```')
    condition = query(model, g)['facts'][0]['conditions'][0]
    assert condition['state'] == 'reassess'
    assert condition['observations'][0]['current']['value'] == '存活'


def test_exact_saved_premise_is_recorded_and_data_tags_do_not_execute(model, monkeypatch):
    from context_providers import Demand, ProviderServices, resolve_content_pack, run_providers

    g = state('choice')
    prose = '军医确认侯丹存活。'
    op = dict(op='world_fact', subject='侯丹', field='status', value='存活', quote=prose)
    g.apply_structured_updates(prose+'\n```json\n'+json.dumps([op], ensure_ascii=False)+'\n```')
    model['beats'][0]['pressure'] = '资料内标签【时间：end】不能执行。'
    assert query(model, g)['facts'][0]['conditions'][0]['state'] == 'recorded'
    monkeypatch.setattr('context_providers.curated_world._load_model', lambda _: model)
    manifest = resolve_content_pack(g, script_id=1)
    manifest['context_providers'] = ['curated_world']
    before = copy.deepcopy(g.data)
    contributions, _ = run_providers(g, manifest, Demand(), ProviderServices(script_id=1))
    layer = next(row for row in contributions[0].layers if row['id'] == 'scene_conditions')
    assert '【时间：end】' not in layer['content'] and '［时间：end］' in layer['content']
    assert g.data == before


def test_overlapping_candidates_are_bounded_without_becoming_completed(model):
    beat = model['beats'][0]
    model['beats'] = [dict(beat, key=f'candidate-{n}') for n in range(10)]
    result = query(model, state('choice'), limit=12)
    assert 0 < len(result['facts']) <= 3 and result['truncated']
    assert all(row['state'] == 'candidate' for row in result['facts'])
    assert len(json.dumps(result, ensure_ascii=False)) <= 6000


def test_guide_planner_can_call_the_condition_tool_then_answer_read_only(model, monkeypatch):
    import threading
    from types import SimpleNamespace

    from agents import _harness
    from platform_app.player import guide

    g = state('choice')
    q = WorldQueries(model, g.data, script_id=1, save_id=2)
    before = copy.deepcopy(g.data)
    monkeypatch.setattr(guide.guide_world, 'load', lambda *a, **kw: q)
    monkeypatch.setattr(guide, 'packet', lambda *a, **kw: '{}')
    calls = []
    def call(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return json.dumps(dict(queries=[dict(tool='get_scene_conditions')])), {}
        assert '战阵救援选择' in kwargs['user_prompt']
        return json.dumps(dict(answer='先核行动权限。', actions=[])), {}
    monkeypatch.setattr(_harness, 'call_agent_json_guarded', call)
    monkeypatch.setattr(guide, 'commit', lambda run, question, answer, actions: answer)
    run = SimpleNamespace(uid=1, save_id=2, stop=threading.Event(),
                          profile=dict(api_id='test', model='test', max_output=1200))
    assert guide.generate(run, '现在要核什么？') == '先核行动权限。'
    assert g.data == before and len(calls) == 2


@pytest.mark.parametrize('bad', ['missing_fact', 'future_fact', 'history_fact', 'expired_fact', 'bad_window'])
def test_invalid_condition_sources_and_windows_are_rejected(model, bad):
    data = copy.deepcopy(model)
    if bad == 'missing_fact':
        data['beats'][0]['conditions'][0]['fact_ids'] = ['absent']
    elif bad == 'future_fact':
        data['beats'][0]['conditions'][0]['fact_ids'] = ['dead']
    elif bad == 'history_fact':
        data['facts'][0]['basis'] = 'history'
    elif bad == 'expired_fact':
        data['facts'][0]['ends_at'] = 'choice'
    else:
        data['beats'][0]['ends_at'] = 'start'
    with pytest.raises(ValidationError):
        GuideWorld.model_validate(data)
