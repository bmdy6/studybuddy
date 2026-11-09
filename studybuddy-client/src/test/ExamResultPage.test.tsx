import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const { mockExamDetail, mockAnswerResult, mockSubmitFeedback, mockNavigate } = vi.hoisted(() => ({
  mockExamDetail: vi.fn(),
  mockAnswerResult: vi.fn(),
  mockSubmitFeedback: vi.fn(),
  mockNavigate: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('@/features/exams/hooks/usePolling', () => ({
  usePolling: () => ({ isGrading: false, pendingCount: 0 }),
}));

vi.mock('@/features/auth/store', () => ({
  useAuthStore: () => ({
    token: 'mock-token',
    role: 'student',
    activeChildId: null,
    userId: 2,
    children: [],
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

vi.mock('@/features/exams/exam', () => ({
  examApi: {
    detail: mockExamDetail,
  },
}));

vi.mock('@/features/exams/answer', () => ({
  answerApi: {
    result: mockAnswerResult,
  },
}));

vi.mock('@/features/p2/api', () => ({
  p2Api: {
    submitFeedback: mockSubmitFeedback,
  },
}));

import ExamResultPage from '@/features/exams/pages/ExamResultPage';

function renderResultPage(options?: { planItemId?: number }) {
  return render(
    <MemoryRouter
      initialEntries={[
        {
          pathname: '/exams/1/result',
          search: options?.planItemId ? `?exam_record_id=8&plan_item_id=${options.planItemId}` : '',
          state: {
            examRecordId: 8,
            objectiveScore: 0,
            pendingManualCount: 0,
          },
        },
      ]}
    >
      <Routes>
        <Route path="/exams/:examId/result" element={<ExamResultPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ExamResultPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockExamDetail.mockResolvedValue({
      id: 1,
      title: 'U5 测验',
      feedback_mode: 'after_submit',
      questions: [{ id: 11, type: 'single_choice', stem: 'He ___ to school.', options: ['go', 'went'], score: 2, group_id: null }],
    });
    mockAnswerResult.mockResolvedValue({
      exam_record_id: 8,
      exam_id: 1,
      exam_title: 'U5 测验',
      status: 'submitted',
      total_score: 0,
      feedback_mode: 'after_submit',
      answers: [
        {
          answer_id: 21,
          question_id: 11,
          question_stem: 'He ___ to school.',
          question_type: 'single_choice',
          student_answer: 'go',
          correct_answer: 'went',
          is_correct: false,
          score: 0,
          max_score: 2,
          graded: true,
          knowledge_tags: ['过去时'],
        },
      ],
    });
    mockSubmitFeedback.mockResolvedValue({
      id: 1,
      feedback_type: 'difficulty',
      content: '错题原因',
      created_at: '2026-07-03 10:00:00',
    });
  });

  it('学生可以在结果页给错题记录错因', async () => {
    renderResultPage();

    await waitFor(() => expect(mockAnswerResult).toHaveBeenCalledWith(8));
    expect(await screen.findByText('错因记录')).toBeInTheDocument();
    expect(screen.getAllByText('He ___ to school.').length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: '概念不清' }));

    await waitFor(() => {
      expect(mockSubmitFeedback).toHaveBeenCalledWith(
        2,
        'difficulty',
        expect.stringContaining('错因：概念不清'),
        21,
      );
    });
  });

  it('计划内自练卷结果页可以返回原任务复盘', async () => {
    renderResultPage({ planItemId: 100 });

    await waitFor(() => expect(mockAnswerResult).toHaveBeenCalledWith(8));
    fireEvent.click(screen.getByRole('button', { name: '返回学习任务复盘' }));

    expect(mockNavigate).toHaveBeenCalledWith(
      '/chat?continue_task_item=100&practice_exam_record=8',
    );
  });

  it('试卷概览每行使用 exam-overview-row 布局，防止长题干横向溢出', async () => {
    renderResultPage();
    await waitFor(() => {
      expect(document.querySelectorAll('.exam-overview-row').length).toBe(1);
    });
    expect(document.querySelector('.exam-overview-stem')).toBeTruthy();
  });
});
