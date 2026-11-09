import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

const {
  mockList,
  mockAssign,
  mockAssignments,
  mockNavigate,
  mockMessageSuccess,
  mockMessageError,
  mockAuthState,
} = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockAssign: vi.fn(),
  mockAssignments: vi.fn(),
  mockNavigate: vi.fn(),
  mockMessageSuccess: vi.fn(),
  mockMessageError: vi.fn(),
  mockAuthState: {
    role: 'student',
    displayName: '测试同学',
    children: [] as Array<{ id: number; display_name: string }>,
    activeChildId: null as number | null,
  },
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd');
  const AppMock = ({ children }: { children: ReactNode }) => <>{children}</>;
  AppMock.useApp = () => ({
    message: {
      success: mockMessageSuccess,
      error: mockMessageError,
      info: vi.fn(),
      warning: vi.fn(),
    },
  });
  return {
    ...actual,
    App: AppMock,
  };
});

vi.mock('@/features/exams/exam', () => ({
  examApi: {
    list: mockList,
    assign: mockAssign,
    assignments: mockAssignments,
  },
}));

vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

import ExamListPage from '@/features/exams/pages/ExamListPage';
import ExamManagePage from '@/features/teacher/pages/ExamManagePage';
import type { ExamListItem } from '../types';

function renderWithRouter(ui: ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

function examItem(overrides: Partial<ExamListItem> = {}): ExamListItem {
  return {
    id: 1,
    title: '英语周练',
    subject: 'english',
    status: 'published',
    question_count: 3,
    total_score: 30,
    has_new: false,
    created_at: '2026-07-06 10:00:00',
    ...overrides,
  };
}

describe('Exam assignment flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState.role = 'student';
    mockAuthState.displayName = '测试同学';
    mockAuthState.children = [];
    mockAuthState.activeChildId = null;
    mockList.mockResolvedValue([]);
    mockAssign.mockResolvedValue([]);
    mockAssignments.mockResolvedValue([]);
  });

  it('家长多选学生分发试卷时会提交 student_ids 并提示成功', async () => {
    mockAuthState.role = 'parent';
    mockAuthState.displayName = '家长';
    mockAuthState.children = [
      { id: 2, display_name: '弟弟' },
      { id: 3, display_name: '妹妹' },
    ];
    mockList.mockResolvedValue([examItem()]);

    renderWithRouter(<ExamManagePage />);

    expect(await screen.findByText('英语周练')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /分发/ }));

    expect(screen.getByText('弟弟')).toBeInTheDocument();
    fireEvent.click(screen.getByText('弟弟'));
    fireEvent.click(screen.getByText('妹妹'));
    fireEvent.click(screen.getByRole('button', { name: '确认分发' }));

    await waitFor(() => expect(mockAssign).toHaveBeenCalledWith(1, {
      student_ids: [2, 3],
      due_at: null,
      note: null,
    }));
    await waitFor(() => expect(mockMessageSuccess).toHaveBeenCalledWith('已分发给 2 位学生'));
  });

  it('分发记录加载失败时给出轻量错误提示', async () => {
    mockAuthState.role = 'parent';
    mockAuthState.displayName = '家长';
    mockAuthState.children = [{ id: 2, display_name: '弟弟' }];
    mockList.mockResolvedValue([examItem()]);
    mockAssignments.mockRejectedValue(new Error('boom'));

    renderWithRouter(<ExamManagePage />);

    expect(await screen.findByText('英语周练')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /分发/ }));

    expect(await screen.findByText('分发记录加载失败')).toBeInTheDocument();
    expect(mockMessageError).toHaveBeenCalledWith('分发记录加载失败');
  });

  it('学生试卷卡片显示分发备注和截止时间', async () => {
    mockList.mockResolvedValue([
      examItem({
        assignment_status: 'assigned',
        assignment_note: '周五前完成',
        assignment_due_at: '2026-07-10 20:00:00',
        visibility: 'assigned',
        has_new: true,
      }),
    ]);

    renderWithRouter(<ExamListPage />);

    expect(await screen.findByText('周五前完成')).toBeInTheDocument();
    expect(screen.getByText('截止 07-10 20:00')).toBeInTheDocument();
  });
});
