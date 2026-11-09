import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockMap, mockAttributes, mockProgress } = vi.hoisted(() => ({
  mockMap: vi.fn(),
  mockAttributes: vi.fn(),
  mockProgress: vi.fn(),
}));

vi.mock('@/features/learning/learningMap', () => ({ learningMapApi: { get: mockMap } }));
vi.mock('@/features/p2/api', () => ({ p2Api: { getAttributeHistory: mockAttributes } }));
vi.mock('@/features/learning/learningProgress', () => ({ learningProgressApi: { get: mockProgress } }));
vi.mock('@/features/auth/store', () => ({
  useAuthStore: () => ({ role: 'student', userId: 2, activeChildId: null }),
}));

import GrowthHomePage from '@/features/growth/pages/GrowthHomePage';

const progress = {
  student_id: 2,
  as_of: '2026-07-17',
  streak_days: 4,
  today: { completed_count: 2, total_count: 3, completion_rate: 2 / 3, status: 'planned' },
  week: [
    { record_date: '2026-07-14', status: 'active', completed_count: 2 },
    { record_date: '2026-07-15', status: 'planned', completed_count: 0 },
    { record_date: '2026-07-16', status: 'no_plan', completed_count: 0 },
    { record_date: '2026-07-17', status: 'active', completed_count: 2 },
  ],
  recent_7_days_completed_tasks: 5,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <GrowthHomePage />
    </MemoryRouter>,
  );
}

describe('GrowthHomePage real progress', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMap.mockResolvedValue({
      student_id: 2,
      generated_at: '2026-07-17',
      nodes: [],
      summary: { weak: 0, reviewing: 0, stable: 0, unknown: 0 },
    });
    mockAttributes.mockResolvedValue({ history: [] });
    mockProgress.mockResolvedValue(progress);
  });

  it('展示连续学习、今日完成率和本周每日状态', async () => {
    renderPage();
    expect(await screen.findByText('4 天')).toBeInTheDocument();
    expect(screen.getByText('2/3')).toBeInTheDocument();
    expect(screen.getByText('5 项')).toBeInTheDocument();
    expect(screen.getByLabelText('本周学习状态')).toBeInTheDocument();
    expect(screen.getByText('7月14日')).toBeInTheDocument();
  });

  it('没有真实进度时显示记录还少，不伪造趋势', async () => {
    mockProgress.mockResolvedValue({
      ...progress,
      streak_days: 0,
      today: { completed_count: 0, total_count: 0, completion_rate: null, status: 'no_plan' },
      week: [],
      recent_7_days_completed_tasks: 0,
    });
    renderPage();
    expect(await screen.findByText(/记录还少/)).toBeInTheDocument();
    expect(screen.queryByText(/连续学习 \d+ 天/)).not.toBeInTheDocument();
  });

  it('进度接口失败时保留学习地图数据并给出局部错误态', async () => {
    mockMap.mockResolvedValue({
      student_id: 2,
      generated_at: '2026-07-17',
      nodes: [],
      summary: { weak: 0, reviewing: 0, stable: 1, unknown: 0 },
    });
    mockProgress.mockRejectedValueOnce(new Error('progress unavailable'));
    renderPage();
    expect(
      await screen.findByText('真实进度暂时加载失败，其他成长数据仍可查看'),
    ).toBeInTheDocument();
    // 进度失败时学习地图仍可用：诊断入口卡基于 summary 算出暂无薄弱点
    expect(screen.getByText('暂无薄弱点，继续保持')).toBeInTheDocument();
  });
});
