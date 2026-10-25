"""Causal stories retain novel pressure without enforcing an already prevented outcome."""
import copy

import pytest

from gm_serving import steering
from platform_app.player.guide_world import bind_initial
from state import GameState


@pytest.fixture
def model():
    return dict(version=1, edition='causal-test', continuity_policy='causal',
                moments=[dict(key='start', label='开篇', order=0, chapter_min=1, chapter_max=1)],
                subjects=[], facts=[])


def causal_state(model):
    g = GameState.new()
    bind_initial(model, g.data, default_opening=True)
    return g


def test_initial_binding_carries_the_reviewed_story_policy(model):
    assert causal_state(model).data['world']['guide_policy'] == 'causal'
    legacy = copy.deepcopy(model)
    del legacy['continuity_policy']
    assert 'guide_policy' not in causal_state(legacy).data['world']


def test_unbound_or_invalid_policy_cannot_enable_causal_history(model):
    from fastapi import HTTPException

    from story_continuity import uses_causal_history

    assert not uses_causal_history(dict(world=dict(guide_policy='causal')))
    with pytest.raises(HTTPException):
        causal_state(dict(model, continuity_policy='anything'))


@pytest.mark.parametrize('guidance', [0, 40, 60, 100])
def test_actual_gm_system_replaces_fatal_convergence_only_for_causal_stories(model, monkeypatch, guidance):
    from agents.gm import master

    gm = master.GameMaster.__new__(master.GameMaster)
    gm.user_id = None
    monkeypatch.setattr(gm, '_world_section_for_active_content', lambda: '')
    monkeypatch.setattr(master, '_consequence_guide_block', lambda _: '')
    monkeypatch.setattr(master, '_agenda_guide_block', lambda _: '')
    gm._active_state = causal_state(model)
    text = gm._build_system(style_profile=dict(guidance_force=guidance))
    assert '因果改史' in text and '未受影响' in text
    assert '玩家任何阻止尝试都会' not in text
    assert '死神来了模式)必发生' not in text
    assert '命运式手段' not in text and '强收束' not in text
    assert '不得编造与原著冲突的事实' not in text
    gm._active_state = GameState.new()
    assert '玩家任何阻止尝试都会' in gm._build_system(style_profile={})


def test_curator_does_not_create_fatal_acceptance_for_causal_rail(model):
    from agents.context_agent import _curator_task_prompt

    text = _curator_task_prompt(causal_state(model), '救人', [], steering_strength='rail')
    assert '因果改史' in text and '不要求人物必死' in text
    assert '推动剧情朝原著走向收束' not in text


class EmptyDB:
    def execute(self, *args):
        return self

    def fetchall(self):
        return []


@pytest.mark.parametrize('coarse', [False, True])
@pytest.mark.parametrize('strength', ['guided', 'rail', 'free'])
def test_both_steering_paths_keep_baseline_without_forcing_death(model, monkeypatch, coarse, strength):
    monkeypatch.setattr(steering.canon_repo, 'read_worldlines', lambda *a: [dict(wl_key='main')])
    node = dict(node_key='death', label='侯丹原著结局', summary='侯丹阵亡',
                anchor_keys=['death'], must_preserve=['侯丹死亡'])
    monkeypatch.setattr(steering.canon_repo, 'read_worldline_nodes', lambda *a, **kw: [node] if coarse else [])
    monkeypatch.setattr('agents.anchor_seed_agent.get_progress_window', lambda *a: dict(chapter_min=1, chapter_max=2))
    monkeypatch.setattr('agents.anchor_seed_agent.list_pending_for_phase',
                        lambda *a, **kw: [dict(node, anchor_key='death')])
    before = causal_state(model)
    snapshot = copy.deepcopy(before.data)
    out = steering.resolve_steering_target(EmptyDB(), save_id=1, script_id=2,
                                          steering_strength=strength, state=before)
    text = out['soft_goal']
    if strength == 'free':
        assert not text
    else:
        assert '侯丹阵亡' in text and '原著对照' in text
        assert '因果' in text and out['strength'] == 'causal'
        assert '强制收束' not in text and '须保留:' not in text
        assert '1-3 轮' not in text
    assert before.data == snapshot
