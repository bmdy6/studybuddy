import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockGet } = vi.hoisted(() => ({ mockGet: vi.fn() }));

vi.mock('@/shared/api/client', () => ({
  default: {
    get: mockGet,
  },
}));

import { learningFlowApi } from '@/features/learning/learningFlow';

describe('learningFlowApi', () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it('读取指定学生的只读学习入口', async () => {
    const entry = { kind: 'empty' };
    mockGet.mockResolvedValue({ data: entry });

    await expect(learningFlowApi.getEntry(2)).resolves.toBe(entry);
    expect(mockGet).toHaveBeenCalledWith('/api/learning-flow/entry', {
      params: { student_id: 2 },
    });
  });
});
