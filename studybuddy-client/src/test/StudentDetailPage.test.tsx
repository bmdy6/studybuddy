import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockGetAttributes, mockGetSupervisionSummary, mockNavigate } = vi.hoisted(() => ({
  mockGetAttributes: vi.fn(),
  mockGetSupervisionSummary: vi.fn(),
  mockNavigate: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('@/features/auth/store', () => ({
  useAuthStore: () => ({
    children: [{ id: 2, display_name: '弟弟' }],
  }),
}));

vi.mock('@/features/p2/api', () => ({
  p2Api: {
    getAttributes: mockGetAttributes,
  },
}));

vi.mock('@/features/growth/supervision', () => ({
  supervisionApi: {
    summary: mockGetSupervisionSummary,
  },
}));

import StudentDetailPage from '@/features/family/pages/StudentDetailPage';

function renderStudentDetail() {
  return render(
    <MemoryRouter initialEntries={['/students/2']}>
      <Routes>
        <Route path="/students/:id" element={<StudentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('StudentDetailPage supervision panel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetAttributes.mockResolvedValue({ current: null });
    mockGetSupervisionSummary.mockResolvedValue({
      student_id: 2,
      student_name: '弟弟',
      reminders: [
        {
          plan_id: 10,
          title: '英语补漏',
          planned_date: '2026-07-07',
          is_overdue: false,
          overdue_days: 0,
          todo_count: 1,
          todo_minutes: 20,
          first_todo_title: '做 2 道过去时错题',
          reminder_message: '今天计划「英语补漏」还有 1 个任务。',
        },
      ],
      support_items: [
        {
          note_id: 20,
          title: '2026.7.7 每日回顾',
          content: '下午不要先刷视频。',
          created_at: '2026-07-07 09:00:00',
        },
      ],
      weak_points: [
        {
          tag: '一般过去时',
          status: 'weak',
          error_count: 4,
          last_wrong_at: '2026-07-06T10:00:00',
          next_action: '先选 1 道错题整理复盘笔记。',
        },
      ],
      recent_assignments: [
        {
          assignment_id: 30,
          exam_id: 1,
          exam_title: '英语周练',
          status: 'assigned',
          due_at: '2026-07-10 20:00:00',
          note: '周五前完成',
          created_at: '2026-07-07 10:00:00',
        },
      ],
      weekly_report: {
        title: '本周学习情况草稿',
        is_empty: false,
        summary: '本草稿只基于已有错题、计划、每日回顾和分发记录生成。',
        highlights: ['本周优先关注「一般过去时」，错题累计 4 次。'],
        next_suggestions: ['先选 1 道错题整理复盘笔记。'],
        sources: ['学习地图', '学习计划', '每日回顾', '试卷分发'],
      },
    });
  });

  it('家长能看到督促面板并跳转分发试卷', async () => {
    renderStudentDetail();

    fireEvent.click(await screen.findByText('督促面板'));

    await waitFor(() => expect(mockGetSupervisionSummary).toHaveBeenCalledWith(2));
    expect(screen.getByText('英语补漏')).toBeInTheDocument();
    expect(screen.getByText('下午不要先刷视频。')).toBeInTheDocument();
    expect(screen.getByText('一般过去时')).toBeInTheDocument();
    expect(screen.getByText('英语周练')).toBeInTheDocument();
    expect(screen.getByText('本周学习情况草稿')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /去分发试卷/ }));
    expect(mockNavigate).toHaveBeenCalledWith('/teacher/exams');
  });
});
