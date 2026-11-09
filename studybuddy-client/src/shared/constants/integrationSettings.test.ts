import { afterEach, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

it('disables WeChat without an explicit opt-in', async () => {
  vi.stubEnv('VITE_WECHAT_ENABLED', '');
  const settings = await import('./index');
  expect(settings.WECHAT_ENABLED).toBe(false);
});

it('enables WeChat only for the explicit true setting', async () => {
  vi.stubEnv('VITE_WECHAT_ENABLED', 'true');
  const settings = await import('./index');
  expect(settings.WECHAT_ENABLED).toBe(true);
});
