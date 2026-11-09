import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { PlanCarryOverPanel, type PlanCarryOverState } from '@/features/chat/components/PlanCarryOverPanel';

const state: PlanCarryOverState = {
  asOfDate: '2026-08-19',
  plans: [
    {
      id: 12,
      title: '历史英语计划',
      planned_date: '2026-08-17',
      status: 'archived',
      overdue_days: 2,
      items: [
        { title: '继续复习一般过去时', minutes: 20, status: 'todo' },
        { title: '已完成语法', minutes: 10, status: 'done' },
      ],
    },
  ],
};

describe('PlanCarryOverPanel', () => {
  it('展示旧计划未完成任务并把来源 id 交给沿用操作', () => {
    const onCarryOver = vi.fn();

    render(
      <PlanCarryOverPanel
        state={state}
        onCarryOver={onCarryOver}
        onReplan={vi.fn()}
        confirmingPlanId={null}
        error={null}
      />,
    );

    expect(screen.getByText('发现可继续的旧计划')).toBeInTheDocument();
    expect(screen.getByText('历史英语计划')).toBeInTheDocument();
    expect(screen.getByText(/继续复习一般过去时/)).toBeInTheDocument();
    expect(screen.queryByText('已完成语法')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '沿用历史英语计划' }));

    expect(onCarryOver).toHaveBeenCalledWith(12);
  });

  it('点击重新制定会把选择交给主会话', () => {
    const onReplan = vi.fn();
    render(
      <PlanCarryOverPanel
        state={state}
        onCarryOver={vi.fn()}
        onReplan={onReplan}
        confirmingPlanId={null}
        error={null}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '重新制定今天计划' }));

    expect(onReplan).toHaveBeenCalledTimes(1);
  });
  it('沿用失败时展示可读错误并保留按钮', () => {
    render(
      <PlanCarryOverPanel
        state={state}
        onCarryOver={vi.fn()}
        onReplan={vi.fn()}
        confirmingPlanId={null}
        error="旧计划没有可沿用的未完成任务"
      />,
    );

    expect(screen.getByText('旧计划没有可沿用的未完成任务')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '沿用历史英语计划' })).toBeEnabled();
  });
});
