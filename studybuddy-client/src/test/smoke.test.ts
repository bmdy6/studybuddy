import { describe, it, expect } from 'vitest';

describe('vitest 框架冒烟测试', () => {
  it('assertion works', () => {
    expect(1 + 1).toBe(2);
  });

  it('jsdom environment', () => {
    expect(document).toBeDefined();
    expect(window).toBeDefined();
  });
});
