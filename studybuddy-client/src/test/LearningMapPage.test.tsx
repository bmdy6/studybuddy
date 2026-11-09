import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

const { mockGetLearningMap, mockGetReviewEntry, mockNavigate, stableMessage } = vi.hoisted(() => ({
  mockGetLearningMap: vi.fn(),
  mockGetReviewEntry: vi.fn(),
  mockNavigate: vi.fn(),
  stableMessage: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('@/features/learning/learningMap', () => ({
  learningMapApi: {
    get: mockGetLearningMap,
  },
}));

vi.mock('@/features/learning/learningFlow', () => ({
  learningFlowApi: { getReviewEntry: mockGetReviewEntry },
}));

vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({
    role: 'student',
    userId: 2,
    displayName: '测试学生',
    activeChildId: undefined,
  }),
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd');
  const AppMock = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  AppMock.useApp = () => ({
    message: stableMessage,
  });
  return {
    ...actual,
    App: AppMock,
  };
});

import { App } from 'antd';
import LearningMapPage from '@/features/learning/pages/LearningMapPage';

function renderPage() {
  return render(
    <MemoryRouter>
      <App>
        <LearningMapPage />
      </App>
    </MemoryRouter>,
  );
}

describe('LearningMapPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetReviewEntry.mockResolvedValue({ prompt: '可信知识点复习 prompt' });
  });

  it('展示学习地图节点、行动建议和关联资源', () => {
    const response = {
      student_id: 2,
      generated_at: '2026-07-07T10:00:00',
      summary: { weak: 1, reviewing: 0, stable: 0, unknown: 0 },
      total_count: 1,
      has_more: false,
      nodes: [
        {
          tag: '分数应用题',
          status: 'weak',
          error_count: 3,
          note_count: 1,
          material_count: 1,
          plan_item_count: 0,
          last_wrong_at: '2026-07-07T09:00:00',
          next_actions: ['先选 1 道错题整理复盘笔记。'],
          resources: [
            { id: 11, type: 'error', title: '分数应用题错题', status: '错 3 次', summary: '题干摘要' },
            { id: 12, type: 'note', title: '分数复盘笔记', status: 'confirmed', summary: '复盘摘要' },
          ],
        },
      ],
    };
    mockGetLearningMap.mockReturnValue({
      then(onFulfilled: (value: typeof response) => void) {
        onFulfilled(response);
        return {
          catch() {
            return {
              finally(onFinally: () => void) {
                onFinally();
              },
            };
          },
        };
      },
    });

    const { container } = renderPage();

    expect(mockGetLearningMap).toHaveBeenCalledWith(2);
    expect(screen.getAllByText('分数应用题').length).toBeGreaterThan(0);
    expect(screen.getByText('先选 1 道错题整理复盘笔记。')).toBeInTheDocument();
    expect(screen.getByText('分数复盘笔记')).toBeInTheDocument();
    expect(container.querySelector('.sb-learning-map-path')).toBeInTheDocument();
    expect(container.querySelector('.sb-learning-map-node-index')).toHaveTextContent('01');
    expect(container.querySelector('.sb-learning-map-detail-stat-grid')).toBeInTheDocument();
  });

  it('知识点使用唯一开始复习入口进入主会话', async () => {
    const response = {
      student_id: 2,
      generated_at: '2026-07-07T10:00:00',
      summary: { weak: 1, reviewing: 0, stable: 0, unknown: 0 },
      total_count: 1,
      has_more: false,
      nodes: [{
        tag: '分数应用题', status: 'weak', error_count: 3, note_count: 1,
        material_count: 0, plan_item_count: 0, last_wrong_at: null,
        next_actions: ['旧的泛化建议一', '旧的泛化建议二'], resources: [],
      }],
    };
    mockGetLearningMap.mockResolvedValue(response);
    renderPage();

    fireEvent.click((await screen.findAllByRole('button', { name: '开始复习分数应用题' }))[0]);

    await waitFor(() => expect(mockGetReviewEntry).toHaveBeenCalledWith({ studentId: 2, knowledgeTag: '分数应用题' }));
    const target = mockNavigate.mock.calls[0][0] as string;
    const params = new URLSearchParams(target.slice(target.indexOf('?') + 1));
    expect(params.get('student_id')).toBe('2');
    expect(params.get('prompt')).toBe('可信知识点复习 prompt');
    expect(screen.queryByText('旧的泛化建议二')).not.toBeInTheDocument();
  });
});
