import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }));

vi.mock('@/shared/api/client', () => ({ default: { get: getMock } }));

import { familyGoalApi } from '@/features/family_goal/api';

describe('familyGoalApi.parentBound', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('查家长绑定状态走只读端点', async () => {
    getMock.mockResolvedValue({ data: { parent_bound: false } });

    const result = await familyGoalApi.parentBound(2);

    expect(getMock).toHaveBeenCalledWith('/api/students/2/family-goal-context');
    expect(result).toEqual({ parent_bound: false });
  });
});
