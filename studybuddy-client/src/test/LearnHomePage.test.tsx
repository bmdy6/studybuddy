import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';

const { mockGetEntry } = vi.hoisted(() => ({
  mockGetEntry: vi.fn(),
}));

vi.mock('@/features/learning/learningFlow', () => ({
  learningFlowApi: { getEntry: mockGetEntry },
}));

vi.mock('@/features/auth/store', () => ({
  useAuthStore: () => ({
    role: 'student',
    userId: 2,
    activeChildId: null,
  }),
}));

import LearnHomePage from '@/features/learning/pages/LearnHomePage';
import type { LearningFlowEntry } from '../types';

function emptyEntry(): LearningFlowEntry {
  return {
    kind: 'empty',
    title: '',
    description: '',
    prompt: '',
    source_type: 'study_plan',
    source_id: null,
    item_id: null,
    primary_label: '',
    evidence: [],
  };
}

function renderHome() {
  return render(
    <MemoryRouter>
      <LearnHomePage />
      <LocationProbe />
    </MemoryRouter>,
  );
}

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="current-path">{loc.pathname}{loc.search}</div>;
}

describe('LearnHomePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetEntry.mockResolvedValue(emptyEntry());
  });

  it('学习首页提供每日记录入口，不再把手写每日回顾作为日常入口', async () => {
    renderHome();

    const dailyRecords = await screen.findByRole('button', { name: '每日记录' });
    expect(dailyRecords).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '每日回顾' })).not.toBeInTheDocument();
    fireEvent.click(dailyRecords);
    expect(screen.getByTestId('current-path')).toHaveTextContent('/daily-records');
  });

  it('保留六宫格分类，并提供计划历史次要入口', async () => {
    renderHome();

    await screen.findByRole('button', { name: '每日记录' });
    const grid = document.querySelector('.sb-learn-category-grid');
    expect(grid?.children.length).toBe(6);
    const managePlans = screen.getByRole('button', { name: '管理计划' });
    expect(managePlans).toBeInTheDocument();
    fireEvent.click(managePlans);
    expect(screen.getByTestId('current-path')).toHaveTextContent('/study-plans/all');
  });

  it('继续学习展示真实待执行计划', async () => {
    mockGetEntry.mockResolvedValueOnce({
      kind: 'continue_plan',
      title: '继续「今日英语计划」',
      description: '先完成「复习一般过去时」',
      prompt: '继续今日英语计划',
      source_type: 'study_plan',
      source_id: 9,
      item_id: 446,
      primary_label: '继续学习',
      evidence: ['今天', '1 个待完成任务'],
    });

    renderHome();

    expect(await screen.findByRole('button', { name: '继续学习 继续「今日英语计划」' })).toBeInTheDocument();
    expect(screen.getByText('先完成「复习一般过去时」')).toBeInTheDocument();
  });

  it('继续学习卡片点击后进入 task session 而非预填主会话', async () => {
    mockGetEntry.mockResolvedValueOnce({
      kind: 'continue_plan',
      title: '继续「今日英语语法补漏·一般过去时」',
      description: '先完成「一般过去时用法梳理与关键变形」',
      prompt: '我想继续学习计划',
      source_type: 'study_plan',
      source_id: 342,
      item_id: 446,
      primary_label: '继续学习',
      evidence: ['今天', '1 个待完成任务', '20 分钟'],
    });

    renderHome();

    const card = await screen.findByRole('button', { name: '继续学习 继续「今日英语语法补漏·一般过去时」' });
    fireEvent.click(card);

    expect(screen.getByTestId('current-path')).toHaveTextContent('/chat?continue_task_item=446');
  });

  it('没有待执行任务时展示空态，不显示旧任务', async () => {
    renderHome();

    expect(await screen.findByText('告诉助手今天想学什么')).toBeInTheDocument();
    expect(screen.queryByText('今日英语计划')).not.toBeInTheDocument();
  });

  it('学习建议失败时展示错误态和重试入口', async () => {
    mockGetEntry.mockRejectedValueOnce(new Error('network'));

    renderHome();

    expect(await screen.findByText('暂时没拿到学习建议')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument();
  });
});
