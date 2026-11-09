/// <reference types="vitest/jsdom" />

import '@testing-library/jest-dom';
import { vi } from 'vitest';

Object.defineProperty(globalThis, 'localStorage', {
  value: jsdom.window.localStorage,
  configurable: true,
});

// jsdom 不实现 scrollIntoView / scrollTo / matchMedia，mock 掉
Element.prototype.scrollIntoView = vi.fn();
Element.prototype.scrollTo = vi.fn();
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock antd message（组件测试里会触发，但 jsdom 不支持）
vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...actual,
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
    App: Object.assign(({ children }: { children: React.ReactNode }) => <>{children}</>, {
      useApp: () => ({
        message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
        modal: { confirm: vi.fn(), info: vi.fn() },
        notification: { info: vi.fn() },
      }),
    }),
  };
});
