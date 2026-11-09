import { afterEach, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

it('honors an explicitly configured local API in a production build', async () => {
  vi.stubEnv('PROD', true);
  vi.stubEnv('VITE_API_BASE', 'http://127.0.0.1:18001');
  const { API_BASE } = await import('./client');
  expect(API_BASE).toBe('http://127.0.0.1:18001');
});

it('defaults to the local backend without a private hosted service', async () => {
  vi.stubEnv('VITE_API_BASE', '');
  const { API_BASE } = await import('./client');
  expect(API_BASE).toBe('http://127.0.0.1:8001');
});
