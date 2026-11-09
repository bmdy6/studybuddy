import { describe, expect, it, vi } from 'vitest';

import { withRetry } from '@/shared/utils/retry';

/** 构造带 HTTP status 的错误（模拟 axios 错误结构） */
function makeError(status: number, message = 'fail'): unknown {
  const err = new Error(message) as unknown as { response?: { status?: number }; message: string };
  err.response = { status };
  return err;
}

describe('withRetry', () => {
  it('首次成功不重试', async () => {
    const fn = vi.fn().mockResolvedValue('ok');
    const result = await withRetry(fn, { baseDelayMs: 1 });
    expect(result).toBe('ok');
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('瞬时错误后重试成功', async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(makeError(500))
      .mockRejectedValueOnce(makeError(502))
      .mockResolvedValueOnce('ok');
    const result = await withRetry(fn, { retries: 3, baseDelayMs: 1 });
    expect(result).toBe('ok');
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it('重试耗尽抛最后错误', async () => {
    const fn = vi.fn().mockRejectedValue(makeError(503));
    await expect(withRetry(fn, { retries: 2, baseDelayMs: 1 })).rejects.toThrow('fail');
    expect(fn).toHaveBeenCalledTimes(3); // 首次 + 2 次重试
  });

  it('4xx 不重试直接抛', async () => {
    const fn = vi.fn().mockRejectedValue(makeError(403));
    await expect(withRetry(fn, { retries: 3, baseDelayMs: 1 })).rejects.toThrow('fail');
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('404 也不重试', async () => {
    const fn = vi.fn().mockRejectedValue(makeError(404));
    await expect(withRetry(fn, { retries: 3, baseDelayMs: 1 })).rejects.toThrow('fail');
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('网络错误(无 response)会重试', async () => {
    const fn = vi.fn().mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce('ok');
    const result = await withRetry(fn, { retries: 2, baseDelayMs: 1 });
    expect(result).toBe('ok');
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('429 限流会重试', async () => {
    const fn = vi.fn().mockRejectedValueOnce(makeError(429)).mockResolvedValueOnce('ok');
    const result = await withRetry(fn, { retries: 2, baseDelayMs: 1 });
    expect(result).toBe('ok');
    expect(fn).toHaveBeenCalledTimes(2);
  });
});
