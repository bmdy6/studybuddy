import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

const { mockExamDetail, mockNavigate } = vi.hoisted(() => ({
  mockExamDetail: vi.fn(),
  mockNavigate: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('@/features/exams/exam', () => ({
  examApi: { detail: mockExamDetail },
}));

import ExamPreviewPage from '@/features/exams/pages/ExamPreviewPage';

function renderPage(examId = '1') {
  return render(
    <MemoryRouter initialEntries={[`/exams/${examId}/preview`]}>
      <Routes>
        <Route path="/exams/:examId/preview" element={<ExamPreviewPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ExamPreviewPage 试卷预览（只读）', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockExamDetail.mockResolvedValue({
      id: 1,
      title: 'U5 预览卷',
      feedback_mode: 'after_submit',
      questions: [
        {
          id: 11,
          type: 'single_choice',
          stem: 'He ___ to school.',
          options: ['go', 'went'],
          score: 2,
          group_id: null,
        },
        { id: 12, type: 'essay', stem: '写一段短文。', options: null, score: 10, group_id: null },
      ],
    });
  });

  it('渲染试卷标题、题量与题目', async () => {
    renderPage();
    await waitFor(() => expect(mockExamDetail).toHaveBeenCalledWith(1));
    expect(await screen.findByText('U5 预览卷')).toBeInTheDocument();
    expect(screen.getByText('2 题')).toBeInTheDocument();
    expect(screen.getByText('满分 12 分')).toBeInTheDocument();
    expect(screen.getByText('He ___ to school.')).toBeInTheDocument();
    expect(screen.getByText('写一段短文。')).toBeInTheDocument();
  });

  it('只读模式不渲染作答控件', async () => {
    renderPage();
    await screen.findByText('He ___ to school.');
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('返回按钮调用 navigate(-1)', async () => {
    renderPage();
    const back = await screen.findByRole('button', { name: /返回/ });
    fireEvent.click(back);
    expect(mockNavigate).toHaveBeenCalledWith(-1);
  });
});
