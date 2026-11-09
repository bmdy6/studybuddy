import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';

const { mockListErrorBook, mockGetReviewEntry, mockNavigate, mockMessage } = vi.hoisted(() => ({
  mockListErrorBook: vi.fn(),
  mockGetReviewEntry: vi.fn(),
  mockNavigate: vi.fn(),
  mockMessage: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
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
    activeChildId: 2,
    userId: 1,
    children: [{ id: 2, display_name: '弟弟' }],
  }),
  getActiveStudentId: () => 2,
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  const AppMock = ({ children }: { children: ReactNode }) => <>{children}</>;
  AppMock.useApp = () => ({
    message: mockMessage,
  });
  return {
    ...actual,
    App: AppMock,
  };
});

vi.mock('@/features/error_book/api', () => ({
  errorBookApi: {
    list: mockListErrorBook,
  },
}));

vi.mock('@/features/learning/learningFlow', () => ({
  learningFlowApi: { getReviewEntry: mockGetReviewEntry },
}));

import ErrorBookPage from '@/features/error_book/pages/ErrorBookPage';

describe('ErrorBookPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListErrorBook.mockResolvedValue([
      {
        subject: 'english',
        total_count: 1,
        type_groups: [
          {
            question_type: 'single_choice',
            type_label: '单选题',
            error_count: 1,
            last_wrong_at: '2026-07-03 10:00:00',
            questions: [
              {
                error_id: 101,
                question_id: 11,
                stem: 'He ___ to school yesterday.',
                student_answer: 'go',
                correct_answer: 'went',
                error_count: 2,
                knowledge_tags: ['一般过去时'],
              },
            ],
          },
        ],
      },
    ]);
    mockGetReviewEntry.mockResolvedValue({
      prompt: '可信错题复习 prompt',
    });
  });

  it('家长查看错题本时携带当前学生 id', async () => {
    render(
      <MemoryRouter>
        <ErrorBookPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(mockListErrorBook).toHaveBeenCalledWith(2));
    expect(screen.getByText('He ___ to school yesterday.')).toBeInTheDocument();
  });

  it('可以把错题带到对话页开始复习（生成同类练习）', async () => {
    render(
      <MemoryRouter>
        <ErrorBookPage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: /开始复习/ }));

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledTimes(1));
    const target = mockNavigate.mock.calls[0][0] as string;
    expect(target).toContain('/chat?');
    const params = new URLSearchParams(target.slice(target.indexOf('?') + 1));
    expect(params.get('student_id')).toBe('2');
    expect(mockGetReviewEntry).toHaveBeenCalledWith({ studentId: 2, errorId: 101 });
    expect(params.get('prompt')).toBe('可信错题复习 prompt');
  });
});
