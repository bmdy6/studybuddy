import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import dayjs from 'dayjs';

const { mockCreateNote, mockUpdateNote, mockListNotes, mockNavigate } = vi.hoisted(() => ({
  mockCreateNote: vi.fn(),
  mockUpdateNote: vi.fn(),
  mockListNotes: vi.fn(),
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
    role: 'student',
    displayName: '弟弟',
    userId: 2,
    children: [],
    activeChildId: null,
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

vi.mock('@/features/note/api', () => ({
  noteApi: {
    list: mockListNotes,
    create: mockCreateNote,
    update: mockUpdateNote,
  },
}));

import DailyReviewPage, { buildDailyReviewContent } from '@/features/growth/pages/DailyReviewPage';

const FROZEN_NOW = '2026-07-05T09:00:00+08:00';
const DEFAULT_REVIEW_LABEL = '2026.7.4';
const DEFAULT_TARGET_LABEL = '2026.7.5';

describe('DailyReviewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.setSystemTime(new Date(FROZEN_NOW));
    mockCreateNote.mockResolvedValue({
      id: 101,
      student_id: 2,
      type: 'study_record',
      title: `${DEFAULT_TARGET_LABEL} 每日回顾`,
      subject: '其他',
      category: '每日回顾',
      content: '',
      knowledge_tags: ['每日回顾'],
      source: '每日回顾',
      source_ref: [],
      status: 'confirmed',
      created_at: '2026-07-05 09:00:00',
      updated_at: '2026-07-05 09:00:00',
    });
    mockUpdateNote.mockResolvedValue({
      id: 101,
      status: 'confirmed',
    });
    mockListNotes.mockResolvedValue([
      {
        id: 77,
        student_id: 2,
        type: 'study_record',
        title: `${DEFAULT_REVIEW_LABEL} 每日回顾`,
        subject: '其他',
        category: '每日回顾',
        content:
          '## 昨日回顾（2026.7.3）\n\n复盘了英语错题。\n\n## 今日目标（2026.7.4）\n\n- [ ] 继续背单词\n- [ ] 做 1 道数学错题',
        knowledge_tags: ['每日回顾'],
        source: '每日回顾',
        source_ref: [],
        status: 'confirmed',
        created_at: '2026-07-04 21:00:00',
        updated_at: '2026-07-04 21:00:00',
      },
      {
        id: 88,
        student_id: 2,
        type: 'study_record',
        title: '普通英语笔记',
        subject: '英语',
        category: '语法',
        content: '一般现在时',
        knowledge_tags: ['语法'],
        source: 'AI整理',
        source_ref: [],
        status: 'confirmed',
        created_at: '2026-07-04 20:00:00',
        updated_at: '2026-07-04 20:00:00',
      },
    ]);
  });

  it('打开页面展示昨日回顾与今日目标语义及默认日期', async () => {
    render(
      <MemoryRouter>
        <DailyReviewPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText(`${DEFAULT_REVIEW_LABEL} 每日回顾`)).toBeInTheDocument();
    expect(screen.getByText(/复盘了英语错题/)).toBeInTheDocument();
    expect(screen.queryByText('普通英语笔记')).not.toBeInTheDocument();
    expect(screen.getByText('已确认')).toHaveClass('sb-status-chip--confirmed');

    // 页面文案使用「昨日回顾 / 今日目标」
    expect(screen.getByText('昨日回顾')).toBeInTheDocument();
    expect(screen.getByText('今日目标')).toBeInTheDocument();
    expect(screen.getByDisplayValue(DEFAULT_REVIEW_LABEL)).toBeInTheDocument();
    expect(screen.getByText(`目标 ${DEFAULT_TARGET_LABEL}`)).toHaveClass('sb-date-chip--target');
    expect(screen.queryByLabelText('目标日期')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText(`${DEFAULT_REVIEW_LABEL} 每日回顾`));

    expect(mockNavigate).toHaveBeenCalledWith('/notes/77');
  });

  it('填写昨日回顾和今日目标后保存为 checklist 笔记', async () => {
    render(
      <MemoryRouter>
        <DailyReviewPage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText('昨日回顾'), {
      target: { value: '背了 30 个英语单词，复盘了 2 道数学错题。' },
    });
    fireEvent.change(screen.getByPlaceholderText('输入一条今日目标'), {
      target: { value: '背英语单词 20 个' },
    });
    fireEvent.click(screen.getByRole('button', { name: '添加目标' }));
    fireEvent.change(screen.getByPlaceholderText('输入一条今日目标'), {
      target: { value: '做数学错题 2 道' },
    });
    fireEvent.click(screen.getByRole('button', { name: '添加目标' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '背英语单词 20 个' }));
    fireEvent.change(screen.getByLabelText('需要提醒我的地方'), {
      target: { value: '下午开始前容易拖延，希望先提醒我打开书。' },
    });

    const saveButton = screen.getByRole('button', { name: '保存回顾' });
    expect(saveButton).toBeEnabled();
    fireEvent.click(saveButton);

    await waitFor(() => expect(mockCreateNote).toHaveBeenCalledTimes(1));
    expect(mockCreateNote).toHaveBeenCalledWith({
      student_id: 2,
      title: `${DEFAULT_TARGET_LABEL} 每日回顾`,
      subject: '其他',
      category: '每日回顾',
      content: expect.stringContaining(`## 昨日回顾（${DEFAULT_REVIEW_LABEL}）`),
      knowledge_tags: ['每日回顾', '目标'],
      source: '每日回顾',
      source_ref: [],
      status: 'confirmed',
    });
    const payload = mockCreateNote.mock.calls[0][0];
    expect(payload.content).toContain(`## 昨日回顾（${DEFAULT_REVIEW_LABEL}）`);
    expect(payload.content).toContain('背了 30 个英语单词');
    expect(payload.content).toContain(`## 今日目标（${DEFAULT_TARGET_LABEL}）`);
    expect(payload.content).toContain('- [x] 背英语单词 20 个');
    expect(payload.content).toContain('- [ ] 做数学错题 2 道');
    expect(payload.content).toContain('## 需要督促的地方');
    expect(payload.content).toContain('下午开始前容易拖延');
    expect(mockUpdateNote).not.toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith('/notes/101');
  });

  it('线上创建接口返回草稿时会自动确认每日回顾笔记', async () => {
    mockCreateNote.mockResolvedValueOnce({
      id: 102,
      student_id: 2,
      type: 'study_record',
      title: `${DEFAULT_TARGET_LABEL} 每日回顾`,
      subject: '其他',
      category: '每日回顾',
      content: '',
      knowledge_tags: ['每日回顾'],
      source: '每日回顾',
      source_ref: [],
      status: 'draft',
      created_at: '2026-07-05 09:00:00',
      updated_at: '2026-07-05 09:00:00',
    });

    render(
      <MemoryRouter>
        <DailyReviewPage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText('昨日回顾'), {
      target: { value: '完成了英语复盘。' },
    });
    fireEvent.change(screen.getByPlaceholderText('输入一条今日目标'), {
      target: { value: '继续做错题。' },
    });
    fireEvent.click(screen.getByRole('button', { name: '添加目标' }));

    fireEvent.click(screen.getByRole('button', { name: '保存回顾' }));

    await waitFor(() => expect(mockUpdateNote).toHaveBeenCalledWith(102, { status: 'confirmed' }));
    expect(mockNavigate).toHaveBeenCalledWith('/notes/102');
  });

  it('回顾日期决定目标日期，完成目标保存为已完成 checklist', async () => {
    const content = buildDailyReviewContent(
      {
        summary: '复盘了英语。',
        goals: [
          { id: 'g1', text: '做数学错题 2 道', done: true },
          { id: 'g2', text: '背英语单词 20 个', done: false },
        ],
        support: '下午容易拖延。',
      },
      dayjs('2026-07-02'),
    );
    expect(content).toContain('## 昨日回顾（2026.7.2）');
    expect(content).toContain('复盘了英语。');
    expect(content).toContain('## 今日目标（2026.7.3）');
    expect(content).toContain('- [x] 做数学错题 2 道');
    expect(content).toContain('- [ ] 背英语单词 20 个');

    render(
      <MemoryRouter>
        <DailyReviewPage />
      </MemoryRouter>,
    );
    expect(screen.getByDisplayValue(DEFAULT_REVIEW_LABEL)).toBeInTheDocument();
    expect(screen.getByText(`目标 ${DEFAULT_TARGET_LABEL}`)).toBeInTheDocument();
    expect(screen.getByLabelText('回顾日期')).toBeInTheDocument();
    expect(screen.queryByLabelText('目标日期')).not.toBeInTheDocument();
  });

  it('点击今日目标可以切换完成状态并显示删除线', async () => {
    render(
      <MemoryRouter>
        <DailyReviewPage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText('输入一条今日目标'), {
      target: { value: '完成英语单词复习' },
    });
    fireEvent.click(screen.getByRole('button', { name: '添加目标' }));

    const goalCheckbox = screen.getByRole('checkbox', { name: '完成英语单词复习' });
    fireEvent.click(goalCheckbox);

    expect(goalCheckbox).toBeChecked();
    expect(screen.getByText('完成英语单词复习')).toHaveClass('is-done');
  });

  it('未完成目标可以跳转到对话页先商量计划', async () => {
    render(
      <MemoryRouter>
        <DailyReviewPage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText('输入一条今日目标'), {
      target: { value: '下午复习英语语法' },
    });
    fireEvent.click(screen.getByRole('button', { name: '添加目标' }));
    fireEvent.click(screen.getByRole('button', { name: '商量计划：下午复习英语语法' }));

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const target = mockNavigate.mock.calls[0][0] as string;
    expect(target).toContain('/chat?');
    expect(target).toContain('student_id=2');
    expect(decodeURIComponent(target)).toContain('我今天的目标是：下午复习英语语法');
    expect(decodeURIComponent(target)).toContain('请先和我商量');
    expect(decodeURIComponent(target)).toContain('确认学习时长、任务拆分和可行性');
    expect(decodeURIComponent(target)).toContain('再帮我创建学习计划');
    expect(decodeURIComponent(target)).toContain('没有我明确确认前，不要直接创建计划');
  });

  it('已完成目标不显示商量计划入口', async () => {
    render(
      <MemoryRouter>
        <DailyReviewPage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText('输入一条今日目标'), {
      target: { value: '完成英语单词复习' },
    });
    fireEvent.click(screen.getByRole('button', { name: '添加目标' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '完成英语单词复习' }));

    expect(screen.queryByRole('button', { name: '商量计划：完成英语单词复习' })).not.toBeInTheDocument();
  });
});
