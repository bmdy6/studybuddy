import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import type { ReactNode } from 'react';

const { mockExamList, mockNavigate, mockUseAuth } = vi.hoisted(() => ({
  mockExamList: vi.fn(),
  mockNavigate: vi.fn(),
  mockUseAuth: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('@/features/auth/useAuth', () => ({
  useAuth: mockUseAuth,
}));

vi.mock('@/features/exams/exam', () => ({
  examApi: { list: mockExamList },
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  const AppMock = ({ children }: { children: ReactNode }) => <>{children}</>;
  AppMock.useApp = () => ({
    message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
  });
  return { ...actual, App: AppMock };
});

import ExamListPage from '@/features/exams/pages/ExamListPage';

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/exams']}>
      <Routes>
        <Route path="/exams" element={<ExamListPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const examItem = {
  id: 5,
  title: 'U5 单元测验',
  subject: 'english',
  status: 'published',
  visibility: 'public',
  assignment_status: null,
  assignment_note: null,
  assignment_due_at: null,
  question_count: 10,
  total_score: 100,
  has_new: false,
  created_at: '2026-07-01 10:00:00',
};

describe('ExamListPage 试卷列表', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAuth.mockReturnValue({ displayName: '小明' });
  });

  it('渲染试卷卡片并展示分值', async () => {
    mockExamList.mockResolvedValue([examItem]);
    renderPage();
    await waitFor(() => expect(mockExamList).toHaveBeenCalled());
    expect(await screen.findByText('U5 单元测验')).toBeInTheDocument();
    expect(screen.getByText('100 分')).toBeInTheDocument();
  });

  it('未作答卡片一次完整鼠标点击只进入一次答题页', async () => {
    mockExamList.mockResolvedValue([examItem]);
    renderPage();
    const title = await screen.findByText('U5 单元测验');
    fireEvent.mouseDown(title);
    fireEvent.click(title);
    expect(mockNavigate).toHaveBeenCalledTimes(1);
    expect(mockNavigate).toHaveBeenCalledWith('/exams/5/take');
  });

  it.each([
    ['submitted', '批改中'],
    ['graded', '已完成'],
  ])('%s 卡片点击进入本次结果页', async (status, label) => {
    mockExamList.mockResolvedValue([
      { ...examItem, latest_record_status: status, latest_record_id: 88 },
    ]);
    renderPage();

    fireEvent.click(await screen.findByText('U5 单元测验'));

    expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    expect(mockNavigate).toHaveBeenCalledWith('/exams/5/result', {
      state: { examRecordId: 88 },
    });
  });

  it('窄屏下题数和分数保持横排，操作区整体换行', async () => {
    mockExamList.mockResolvedValue([
      { ...examItem, latest_record_status: 'graded', latest_record_id: 88 },
    ]);
    renderPage();

    await screen.findByText('U5 单元测验');

    expect(screen.getByTestId('exam-question-count-5')).toHaveStyle({ whiteSpace: 'nowrap' });
    expect(screen.getByTestId('exam-total-score-5')).toHaveStyle({ whiteSpace: 'nowrap' });
    expect(screen.getByTestId('exam-card-footer-5')).toHaveStyle({ flexWrap: 'wrap' });
  });

  it('已完成试卷只有点击再练一次才进入答题页', async () => {
    mockExamList.mockResolvedValue([
      { ...examItem, latest_record_status: 'graded', latest_record_id: 88 },
    ]);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /再练一次/ }));

    expect(mockNavigate).toHaveBeenCalledWith('/exams/5/take');
  });

  it('没有试卷时展示空状态', async () => {
    mockExamList.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText('现在还没有可练习的试卷')).toBeInTheDocument();
  });
});
