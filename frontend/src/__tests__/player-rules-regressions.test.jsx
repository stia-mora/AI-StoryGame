import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import AgentModelPicker from '../components/AgentModelPicker.jsx';
import { PanelRules } from '../components/game/PanelRules.jsx';
import '../i18n/index.js';

const apis = [{ id: 'test', display_name: 'Test', models: [
  { real_name: 'image-only', capabilities: ['image_gen'], enabled: true },
  { real_name: 'text-model', capabilities: ['text', 'streaming'], enabled: true },
  { real_name: 'embed-only', capabilities: ['embedding'], enabled: true },
] }];

beforeEach(() => {
  window.api = {
    models: { list: vi.fn().mockResolvedValue({ models: { apis }, selected: { api_id: 'test', real_name: 'image-only' } }) },
    account: { profile: vi.fn().mockResolvedValue({ preferences: { 'gm.api_id': 'test', 'gm.model_real_name': 'image-only' } }) },
    credentials: { list: vi.fn().mockResolvedValue({ items: [{ api_id: 'test', has_credential: true, enabled: true }] }) },
    rules: { action: vi.fn().mockResolvedValue({ ok: true }), encounterNext: vi.fn().mockResolvedValue({ ok: true }) },
  };
});

describe('player flow regression', () => {
  it('text picker repairs an image preference and only offers text models', async () => {
    const onChange = vi.fn();
    render(<AgentModelPicker prefPrefix="gm" variant="popover" onChange={onChange} />);
    await screen.findByText('text-model');
    expect(screen.queryByText('image-only')).toBeNull();
    expect(screen.queryByText('embed-only')).toBeNull();
    expect(onChange).toHaveBeenCalledWith('test', 'text-model', 'init');
  });

  it('image picker remains independent from the text restriction', async () => {
    render(<AgentModelPicker prefPrefix="image_gen" variant="popover" capabilityFilter="image_gen" />);
    await screen.findByText('image-only');
    expect(screen.queryByText('text-model')).toBeNull();
  });

  function rulesState(actor = 'player') {
    return { content_pack: { kind: 'module_adventure' }, player_character: { hp: 8, max_hp: 9 },
      scene: { module_id: 'test', current_room: { checks: [{ id: 'journal-check', kind: 'skill_check', skill: 'investigation', dc: 11 }] } },
      encounter: { active: true, encounter_id: 'fight', round: 1, turn_index: 0,
        initiative_order: [{ id: actor }], combatants: [{ id: 'foe', name: '敌人', side: 'enemy', hp: 7, max_hp: 7 }] } };
  }

  it('check buttons send the authoritative ID instead of secrets or effect parameters', async () => {
    render(<PanelRules state={rulesState()} />);
    fireEvent.click(screen.getByText(/investigation.*11/));
    await waitFor(() => expect(window.api.rules.action).toHaveBeenCalledWith({ kind: 'skill_check', check_id: 'journal-check' }));
  });

  it('attack sends a turn token and manual enemy controls are removed', async () => {
    render(<PanelRules state={rulesState()} />);
    fireEvent.click(screen.getByText(/攻击.*敌人/));
    await waitFor(() => expect(window.api.rules.action).toHaveBeenCalledWith({ kind: 'attack', target: 'foe', turn_token: 'fight:1:0' }));
    expect(screen.queryByText(/让.*敌人.*出招/)).toBeNull();
  });

  it('attack is disabled during an enemy turn', () => {
    render(<PanelRules state={rulesState('foe')} />);
    expect(screen.getByText(/攻击.*敌人/).disabled).toBe(true);
  });
});
