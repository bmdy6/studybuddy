import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { p2Api } from '@/features/p2/api';
import ManualStudyPlanDrawer from '@/features/chat/components/ManualStudyPlanDrawer';
import type { StudyPlan } from '../types';

vi.mock('@/features/p2/api', () => ({
  p2Api: {
    createStudyPlan: vi.fn(),
  },
}));

const mockedP2Api = vi.mocked(p2Api);

const createdPlan: StudyPlan = {
  id: 20,
  student_id: 2,
  title: '英语错题复习',
  focus: null,
  status: 'active',
  planned_date: '2026-07-13',
  is_overdue: false,
  overdue_days: 0,
  reminder_message: null,
  created_by: 2,
  created_at: '2026-07-13 20:00:00',
  items: [
    {
      id: 201,
      title: '一般过去时错题',
      target: null,
      minutes: 20,
      status: 'todo',
      related_tags: [],
      sort_order: 0,
      completed_at: null,
    },
  ],
};

describe('ManualStudyPlanDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedP2Api.createStudyPlan.mockResolvedValue(createdPlan);
  });

  it('手动保存今天计划并回传创建结果', async () => {
    const onCreated = vi.fn();
    render(
      <ManualStudyPlanDrawer
        open
        studentId={2}
        onClose={vi.fn()}
        onCreated={onCreated}
      />,
    );

    fireEvent.change(screen.getByLabelText('计划名称'), {
      target: { value: ' 英语错题复习 ' },
    });
    fireEvent.change(screen.getByLabelText('任务 1'), {
      target: { value: ' 一般过去时错题 ' },
    });
    fireEvent.click(screen.getByRole('button', { name: '保存计划' }));

    await waitFor(() =>
      expect(mockedP2Api.createStudyPlan).toHaveBeenCalledWith(
        2,
        expect.objectContaining({
          title: '英语错题复习',
          planned_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
          focus: null,
          items: [
            {
              title: '一般过去时错题',
              target: null,
              minutes: 20,
              related_tags: [],
            },
          ],
        }),
      ),
    );
    expect(onCreated).toHaveBeenCalledWith(createdPlan);
  });

  it('空白计划名称和任务不能提交', async () => {
    render(
      <ManualStudyPlanDrawer
        open
        studentId={2}
        onClose={vi.fn()}
        onCreated={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '保存计划' }));

    expect(await screen.findByText('请输入计划名称')).toBeInTheDocument();
    expect(await screen.findByText('请输入任务名称')).toBeInTheDocument();
    expect(mockedP2Api.createStudyPlan).not.toHaveBeenCalled();
  });

  it('最多允许添加三项任务', () => {
    render(
      <ManualStudyPlanDrawer
        open
        studentId={2}
        onClose={vi.fn()}
        onCreated={vi.fn()}
      />,
    );

    const addButton = screen.getByRole('button', { name: '再加一项' });
    fireEvent.click(addButton);
    fireEvent.click(addButton);

    expect(screen.getByLabelText('任务 2')).toBeInTheDocument();
    expect(screen.getByLabelText('任务 3')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '再加一项' })).not.toBeInTheDocument();
  });

  it('创建失败时保留输入并显示错误', async () => {
    mockedP2Api.createStudyPlan.mockRejectedValue(new Error('network'));
    render(
      <ManualStudyPlanDrawer
        open
        studentId={2}
        onClose={vi.fn()}
        onCreated={vi.fn()}
      />,
    );

    const titleInput = screen.getByLabelText('计划名称');
    fireEvent.change(titleInput, { target: { value: '数学练习' } });
    fireEvent.change(screen.getByLabelText('任务 1'), { target: { value: '函数题' } });
    fireEvent.click(screen.getByRole('button', { name: '保存计划' }));

    expect(await screen.findByText('创建计划失败，请再试一次')).toBeInTheDocument();
    expect(titleInput).toHaveValue('数学练习');
  });
});
