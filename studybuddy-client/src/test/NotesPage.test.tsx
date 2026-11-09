import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

const { mockListNotes, mockBlindSpots } = vi.hoisted(() => ({
  mockListNotes: vi.fn(),
  mockBlindSpots: vi.fn(),
}));

vi.mock('@/features/note/api', () => ({
  noteApi: {
    list: mockListNotes,
    blindSpots: mockBlindSpots,
  },
}));

vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({
    role: 'student',
    activeChildId: undefined,
  }),
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd');
  const AppMock = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  AppMock.useApp = () => ({
    message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
  });
  return {
    ...actual,
    App: AppMock,
  };
});

import NotesPage from '@/features/note/pages/NotesPage';
import { App } from 'antd';

const noteBase = {
  subject: '其他',
  status: 'confirmed',
  source: 'agent',
  content: '',
  knowledge_tags: [],
  updated_at: '2026-07-05',
};

function renderPage() {
  return render(
    <MemoryRouter>
      <App>
        <NotesPage />
      </App>
    </MemoryRouter>,
  );
}

describe('NotesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockBlindSpots.mockResolvedValue([]);
  });

  it('默认展示普通笔记且排除每日回顾', async () => {
    mockListNotes.mockResolvedValue([
      { ...noteBase, id: 1, title: '7.5 每日回顾', category: '每日回顾' },
      { ...noteBase, id: 2, title: '英语错题复盘', subject: '英语', category: '错题复盘' },
    ]);

    renderPage();

    expect(await screen.findByText('英语错题复盘')).toBeInTheDocument();
    expect(screen.queryByText('7.5 每日回顾')).not.toBeInTheDocument();
  });

  it('通过历史回顾筛选查看旧每日回顾', async () => {
    mockListNotes.mockResolvedValue([
      { ...noteBase, id: 1, title: '7.5 每日回顾', category: '每日回顾' },
      { ...noteBase, id: 2, title: '英语错题复盘', subject: '英语', category: '错题复盘' },
    ]);

    renderPage();

    await screen.findByText('英语错题复盘');
    fireEvent.click(screen.getByRole('button', { name: '历史回顾' }));

    await waitFor(() => {
      expect(screen.getByText('7.5 每日回顾')).toBeInTheDocument();
      expect(screen.queryByText('英语错题复盘')).not.toBeInTheDocument();
    });
  });

  it('只有旧每日回顾时提示切换历史回顾', async () => {
    mockListNotes.mockResolvedValue([
      { ...noteBase, id: 1, title: '7.5 每日回顾', category: '每日回顾' },
    ]);

    renderPage();

    expect(await screen.findByText(/普通笔记暂时为空/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '历史回顾' })).toBeInTheDocument();
  });

  it('只在顶部显示高频分类，其余分类收进更多分类菜单', async () => {
    mockListNotes.mockResolvedValue([
      { ...noteBase, id: 1, title: '错题一', category: '错题复盘' },
      { ...noteBase, id: 2, title: '错题二', category: '错题复盘' },
      { ...noteBase, id: 3, title: '课堂笔记', category: '课堂笔记' },
      { ...noteBase, id: 7, title: '课堂笔记二', category: '课堂笔记' },
      { ...noteBase, id: 4, title: '知识总结', category: '知识总结' },
      { ...noteBase, id: 5, title: '摘录笔记', category: '读书摘录' },
      { ...noteBase, id: 6, title: '随笔笔记', category: '随笔' },
    ]);

    renderPage();

    await screen.findByText('错题一');
    expect(screen.getByRole('button', { name: '更多分类' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '读书摘录' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '更多分类' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: '读书摘录' }));

    await waitFor(() => {
      expect(screen.getByText('摘录笔记')).toBeInTheDocument();
      expect(screen.queryByText('错题一')).not.toBeInTheDocument();
    });
  });

  it('加载失败时展示可重试的行内错误', async () => {
    mockListNotes.mockRejectedValueOnce(new Error('network'));

    renderPage();

    expect(await screen.findByText('笔记暂时加载失败')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新加载笔记' })).toBeInTheDocument();
  });

  it('长标签不会挤压笔记标题层级', async () => {
    mockListNotes.mockResolvedValue([
      {
        ...noteBase,
        id: 1,
        title: '长标签笔记',
        category: '错题复盘',
        knowledge_tags: ['这是一个非常长的知识点标签用于验证移动端换行'],
      },
    ]);

    renderPage();

    await screen.findByText('长标签笔记');
    expect(document.querySelector('.sb-notes-note-tags')).toHaveTextContent(
      '#这是一个非常长的知识点标签用于验证移动端换行',
    );
  });
});
