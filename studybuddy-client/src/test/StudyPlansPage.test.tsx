import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';

const { mockListStudyPlans, mockUpdateStudyPlanItem, mockSetActiveChild, mockNavigate } =
  vi.hoisted(() => ({
    mockListStudyPlans: vi.fn(),
    mockUpdateStudyPlanItem: vi.fn(),
    mockSetActiveChild: vi.fn(),
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
    token: 'mock-token',
    role: 'parent',
    displayName: '家长',
    userId: 1,
    children: [{ id: 2, display_name: '弟弟' }],
    activeChildId: 2,
    setActiveChild: mockSetActiveChild,
  }),
  getActiveStudentId: () => 2,
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  const AppMock = ({ children }: { children: ReactNode }) => <>{children}</>;
  AppMock.useApp = () => ({
    message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
  });
  return {
    ...actual,
    App: AppMock,
  };
});

vi.mock('@/features/p2/api', () => ({
  p2Api: {
    listStudyPlans: mockListStudyPlans,
    updateStudyPlanItem: mockUpdateStudyPlanItem,
  },
}));

import StudyPlansPage from '@/features/learning/pages/StudyPlansPage';

const plan = {
  id: 1,
  student_id: 2,
  title: '今晚英语计划',
  focus: '一般过去时',
  status: 'active',
  planned_date: '2026-07-03',
  is_overdue: false,
  overdue_days: 0,
  created_by: 1,
  created_at: '2026-07-03T10:00:00',
  items: [
    {
      id: 11,
      title: '复盘错题',
      target: '说出 2 个错因',
      minutes: 15,
      status: 'todo',
      related_tags: ['一般过去时'],
      sort_order: 0,
      completed_at: null,
    },
  ],
};

describe('StudyPlansPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListStudyPlans.mockResolvedValue([plan]);
    mockUpdateStudyPlanItem.mockResolvedValue({ ...plan.items[0], status: 'done' });
  });

  it('渲染学习计划和任务', async () => {
    render(
      <MemoryRouter>
        <StudyPlansPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('今晚英语计划')).toBeInTheDocument();
      expect(screen.getByText('复盘错题')).toBeInTheDocument();
      expect(screen.getByText('说出 2 个错因')).toBeInTheDocument();
    });
  });

  it('点击完成会弹证据框，填证据后才更新任务状态', async () => {
    render(
      <MemoryRouter>
        <StudyPlansPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('复盘错题')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /完成/ }));

    // P0 门禁：弹证据输入框，未填证据前不请求 PATCH
    await waitFor(() =>
      expect(screen.getByPlaceholderText(/背出了不规则动词的过去式/)).toBeInTheDocument(),
    );
    expect(mockUpdateStudyPlanItem).not.toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText(/背出了不规则动词的过去式/), {
      target: { value: '说清了时态和错因' },
    });
    fireEvent.click(screen.getByRole('button', { name: '确认完成' }));

    await waitFor(() => {
      expect(mockUpdateStudyPlanItem).toHaveBeenCalledWith(11, 'done', '说清了时态和错因');
      expect(mockListStudyPlans).toHaveBeenCalledTimes(2);
    });
  });

  it('切换全部计划时用空状态查询', async () => {
    const { container } = render(
      <MemoryRouter>
        <StudyPlansPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(mockListStudyPlans).toHaveBeenCalledWith(2, 'active'));
    const selects = container.querySelectorAll('.ant-select-selector');
    fireEvent.mouseDown(selects[0]);
    fireEvent.click(await screen.findByText('全部计划'));

    await waitFor(() => {
      expect(mockListStudyPlans).toHaveBeenCalledWith(2, '');
    });
  });

  it('展示逾期计划提醒', async () => {
    mockListStudyPlans.mockResolvedValue([{ ...plan, is_overdue: true, overdue_days: 2 }]);

    render(
      <MemoryRouter>
        <StudyPlansPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('1 个逾期')).toBeInTheDocument();
      expect(screen.getByText('逾期 2 天')).toBeInTheDocument();
    });
  });

  it('全部计划里展示已归档状态', async () => {
    mockListStudyPlans.mockResolvedValue([
      { ...plan, status: 'archived', is_overdue: false, overdue_days: 0 },
    ]);

    render(
      <MemoryRouter>
        <StudyPlansPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('已归档')).toBeInTheDocument();
    });
  });

  it('逾期计划可以跳转到对话页复盘', async () => {
    mockListStudyPlans.mockResolvedValue([{ ...plan, is_overdue: true, overdue_days: 2 }]);

    render(
      <MemoryRouter>
        <StudyPlansPage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: /复盘/ }));

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const target = mockNavigate.mock.calls[0][0] as string;
    expect(target).toContain('/chat?');
    expect(target).toContain('continue_task_item=11');
  });

  it('已完成项显示查看按钮，待做项仍显示完成', async () => {
    const mixedPlan = {
      ...plan,
      items: [
        plan.items[0],
        {
          ...plan.items[0],
          id: 12,
          title: '已完成任务',
          status: 'done',
          completed_at: '2026-07-03T12:00:00',
        },
      ],
    };
    mockListStudyPlans.mockResolvedValue([mixedPlan]);

    render(
      <MemoryRouter>
        <StudyPlansPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('已完成任务')).toBeInTheDocument());
    const viewBtns = screen
      .getAllByRole('button', { name: /查看/ })
      .filter((el) => el.tagName === 'BUTTON');
    expect(viewBtns.length).toBeGreaterThan(0);
    const doneBtns = screen
      .getAllByRole('button', { name: /完成/ })
      .filter((el) => el.tagName === 'BUTTON');
    expect(doneBtns.length).toBeGreaterThan(0);
  });

  it('点击查看按钮导航到对话页继续任务', async () => {
    const donePlan = {
      ...plan,
      items: [
        {
          ...plan.items[0],
          id: 12,
          title: '已完成任务',
          status: 'done',
          completed_at: '2026-07-03T12:00:00',
        },
      ],
    };
    mockListStudyPlans.mockResolvedValue([donePlan]);

    render(
      <MemoryRouter>
        <StudyPlansPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('已完成任务')).toBeInTheDocument());
    const viewBtn = screen
      .getAllByRole('button', { name: /查看/ })
      .find((el) => el.tagName === 'BUTTON') as HTMLElement;
    expect(viewBtn).toBeDefined();
    fireEvent.click(viewBtn);

    expect(mockNavigate).toHaveBeenCalledWith('/chat?continue_task_item=12');
  });

  it('点击已完成项行或标题也会导航到对话页', async () => {
    const donePlan = {
      ...plan,
      items: [
        {
          ...plan.items[0],
          id: 12,
          title: '已完成任务',
          status: 'done',
          completed_at: '2026-07-03T12:00:00',
        },
      ],
    };
    mockListStudyPlans.mockResolvedValue([donePlan]);

    const { container } = render(
      <MemoryRouter>
        <StudyPlansPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('已完成任务')).toBeInTheDocument());

    fireEvent.click(screen.getByText('已完成任务'));
    expect(mockNavigate).toHaveBeenCalledWith('/chat?continue_task_item=12');

    mockNavigate.mockClear();
    const row = container.querySelector('.sb-plan-item--done') as HTMLElement;
    expect(row).not.toBeNull();
    fireEvent.click(row);
    expect(mockNavigate).toHaveBeenCalledWith('/chat?continue_task_item=12');
  });
});
