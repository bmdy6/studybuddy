import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockGetNote, mockRelatedErrors, mockUpdateNote, mockDeleteNote } = vi.hoisted(() => ({
  mockGetNote: vi.fn(),
  mockRelatedErrors: vi.fn(),
  mockUpdateNote: vi.fn(),
  mockDeleteNote: vi.fn(),
}));

vi.mock('@/features/note/api', () => ({
  noteApi: {
    get: mockGetNote,
    relatedErrors: mockRelatedErrors,
    update: mockUpdateNote,
    delete: mockDeleteNote,
  },
}));

vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({ role: 'student' }),
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd');
  const AppMock = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  AppMock.useApp = () => ({
    message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
  });
  return { ...actual, App: AppMock };
});

import { App } from 'antd';
import NoteDetailPage from '@/features/note/pages/NoteDetailPage';

const note = {
  id: 7,
  title: '函数复盘',
  subject: '数学',
  category: '错题复盘',
  content: '这是笔记正文内容',
  knowledge_tags: ['一次函数'],
  status: 'confirmed',
  source: 'agent',
  updated_at: '2026-07-18',
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/notes/7']}>
      <App>
        <Routes>
          <Route path="/notes/:noteId" element={<NoteDetailPage />} />
        </Routes>
      </App>
    </MemoryRouter>,
  );
}

describe('NoteDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetNote.mockResolvedValue(note);
    mockRelatedErrors.mockResolvedValue([]);
  });

  it('关联错题加载失败时仍展示已加载的笔记正文', async () => {
    mockRelatedErrors.mockRejectedValueOnce(new Error('related errors unavailable'));

    renderPage();

    expect(await screen.findByText('这是笔记正文内容')).toBeInTheDocument();
    expect(screen.queryByText('笔记暂时加载失败')).not.toBeInTheDocument();
  });

  it('主笔记加载失败时展示整页错误态', async () => {
    mockGetNote.mockRejectedValueOnce(new Error('note unavailable'));

    renderPage();

    expect(await screen.findByText('笔记暂时加载失败')).toBeInTheDocument();
    expect(mockRelatedErrors).not.toHaveBeenCalled();
  });
});
