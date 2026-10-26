import { afterEach, expect, it, vi } from 'vitest';

afterEach(() => { delete window.api; });

it('importing shared data helpers does not start private account requests', async () => {
  const me = vi.fn().mockResolvedValue({ user: null });
  window.api = {
    auth: { me },
    platform: { info: vi.fn().mockResolvedValue({}) },
    game: { state: vi.fn().mockResolvedValue({}) },
  };

  await import('../data-loader.js');
  await Promise.resolve();

  expect(me).not.toHaveBeenCalled();
  expect(window.api.game.state).not.toHaveBeenCalled();
});
