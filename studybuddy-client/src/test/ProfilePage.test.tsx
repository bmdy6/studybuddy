/**
 * ProfilePage 组件测试。
 *
 * mock：authStore + p2Api
 * 测：未初始化渲染引导文案、初始化后渲染雷达图/属性条、兴趣登记
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';

const { mockAuth } = vi.hoisted(() => ({
  mockAuth: { role: 'parent', activeChildId: 2 as number | null, userId: 2 as number | null },
}));

vi.mock('@/features/auth/store', () => ({
  useAuthStore: () => ({
    token: 't',
    role: mockAuth.role,
    activeChildId: mockAuth.activeChildId,
    userId: mockAuth.userId,
  }),
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return { ...actual, App: ({ children }: { children: ReactNode }) => <>{children}</> };
});

// mock recharts 避免 jsdom 渲染 SVG 报错
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  RadarChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Radar: () => <div />,
  PolarGrid: () => <div />,
  PolarAngleAxis: () => <div />,
  PolarRadiusAxis: () => <div />,
  LineChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Line: () => <div />,
  XAxis: () => <div />,
  YAxis: () => <div />,
  CartesianGrid: () => <div />,
  Tooltip: () => <div />,
  Legend: () => <div />,
}));

const {
  mockGetAttributes,
  mockGetAttributeHistory,
  mockListInterests,
  mockAddInterest,
  mockConfirmInterest,
  mockRemoveInterest,
  mockGetRecommendationBoundary,
  mockUpdateRecommendationBoundary,
  mockGetProfileSummary,
  mockSaveProfileOnboarding,
} = vi.hoisted(() => ({
  mockGetAttributes: vi.fn(),
  mockGetAttributeHistory: vi.fn(),
  mockListInterests: vi.fn(),
  mockAddInterest: vi.fn(),
  mockConfirmInterest: vi.fn(),
  mockRemoveInterest: vi.fn(),
  mockGetRecommendationBoundary: vi.fn(),
  mockUpdateRecommendationBoundary: vi.fn(),
  mockGetProfileSummary: vi.fn(),
  mockSaveProfileOnboarding: vi.fn(),
}));
vi.mock('@/features/p2/api', () => ({
  p2Api: {
    getAttributes: mockGetAttributes,
    getAttributeHistory: mockGetAttributeHistory,
    listInterests: mockListInterests,
    addInterest: mockAddInterest,
    confirmInterest: mockConfirmInterest,
    removeInterest: mockRemoveInterest,
    getRecommendationBoundary: mockGetRecommendationBoundary,
    updateRecommendationBoundary: mockUpdateRecommendationBoundary,
    getProfileSummary: mockGetProfileSummary,
    saveProfileOnboarding: mockSaveProfileOnboarding,
  },
}));

import ProfilePage from '@/features/family/pages/ProfilePage';

describe('ProfilePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuth.role = 'parent';
    mockAuth.activeChildId = 2;
    mockAuth.userId = 2;
    mockGetRecommendationBoundary.mockResolvedValue({
      student_id: 2,
      allowed_platforms: ['bilibili'],
      blocked_keywords: [],
      daily_limit: 3,
      allow_entertainment_interests: false,
    });
    mockUpdateRecommendationBoundary.mockResolvedValue({
      student_id: 2,
      allowed_platforms: ['bilibili'],
      blocked_keywords: [],
      daily_limit: 3,
      allow_entertainment_interests: false,
    });
    mockGetProfileSummary.mockResolvedValue({
      student_id: 2,
      needs_onboarding: false,
      missing_fields: [],
      summary: { grade: '八年级', semester: '上册', interests: [] },
    });
    mockSaveProfileOnboarding.mockResolvedValue({
      student_id: 2,
      needs_onboarding: false,
      missing_fields: [],
      summary: { grade: '八年级', semester: '上册', interests: [] },
    });
  });

  it('未初始化时渲染引导文案', async () => {
    mockGetAttributes.mockResolvedValue({ current: null });
    mockGetAttributeHistory.mockResolvedValue({ history: [] });
    mockListInterests.mockResolvedValue([]);

    render(<ProfilePage />);
    await waitFor(() => {
      expect(screen.getByText(/学习档案尚未初始化|初始化/)).toBeInTheDocument();
    });
  });

  it('初始化后渲染属性值', async () => {
    mockGetAttributes.mockResolvedValue({
      current: {
        id: 1,
        source: 'init',
        trigger_ref: null,
        created_at: '2026-06-28',
        snapshot: {
          chinese: 85,
          math: 90,
          english: 78,
          pe: 80,
          engagement: 50,
          mastered_count: 3,
          subject_sources: {
            chinese: 'exam_score',
            math: 'exam_score',
            english: 'exam_score',
            pe: 'exam_score',
          },
        },
      },
    });
    mockGetAttributeHistory.mockResolvedValue({ history: [] });
    mockListInterests.mockResolvedValue([{ id: 1, tag: '篮球', source: 'manual', approved: true }]);

    render(<ProfilePage />);
    await waitFor(() => {
      expect(screen.getByText('85')).toBeInTheDocument();
      expect(screen.getByText('90')).toBeInTheDocument();
      expect(screen.getByText('篮球')).toBeInTheDocument();
    });
  });

  it('无证据科目显示数据不足而非假分', async () => {
    mockGetAttributes.mockResolvedValue({
      current: {
        id: 1,
        source: 'init',
        trigger_ref: null,
        created_at: '2026-06-28',
        snapshot: {
          math: 90,
          mastered_count: 0,
          subject_sources: { math: 'exam_score' },
        },
      },
    });
    mockGetAttributeHistory.mockResolvedValue({ history: [] });
    mockListInterests.mockResolvedValue([]);

    render(<ProfilePage />);
    await waitFor(() => {
      // math 有证据，显示真实分
      expect(screen.getByText('90')).toBeInTheDocument();
      // 语文/英语/体育/投入度无证据，显示数据不足
      expect(screen.getAllByText('数据不足').length).toBeGreaterThanOrEqual(4);
    });
  });

  it('历史曲线加载慢时先显示核心档案内容', async () => {
    mockGetAttributes.mockResolvedValue({
      current: {
        id: 1,
        source: 'init',
        trigger_ref: null,
        created_at: '2026-06-28',
        snapshot: {
          chinese: 85,
          math: 90,
          english: 78,
          pe: 80,
          engagement: 50,
          mastered_count: 3,
          subject_sources: {
            chinese: 'exam_score',
            math: 'exam_score',
            english: 'exam_score',
            pe: 'exam_score',
          },
        },
      },
    });
    mockGetAttributeHistory.mockImplementation(() => new Promise(() => undefined));
    mockListInterests.mockResolvedValue([{ id: 1, tag: '篮球', source: 'manual', approved: true }]);

    render(<ProfilePage />);

    expect(await screen.findByText('学习档案')).toBeInTheDocument();
    expect(await screen.findByText('85')).toBeInTheDocument();
    expect(screen.getByText('成长曲线加载中')).toBeInTheDocument();
  });

  it('兴趣标签渲染', async () => {
    mockGetAttributes.mockResolvedValue({ current: null });
    mockGetAttributeHistory.mockResolvedValue({ history: [] });
    mockListInterests.mockResolvedValue([
      { id: 1, tag: '天文', source: 'manual', approved: true },
      { id: 2, tag: '音乐', source: 'inferred', approved: false },
    ]);

    const { container } = render(<ProfilePage />);
    await waitFor(() => {
      expect(container.textContent).toContain('天文');
      expect(container.textContent).toContain('音乐');
      expect(container.textContent).toContain('待学生确认');
    });
  });

  it('学生可以确认推断兴趣', async () => {
    mockAuth.role = 'student';
    mockGetAttributes.mockResolvedValue({ current: null });
    mockGetAttributeHistory.mockResolvedValue({ history: [] });
    mockListInterests.mockResolvedValue([
      { id: 2, tag: '音乐', source: 'inferred', approved: false },
    ]);
    mockConfirmInterest.mockResolvedValue({ id: 2, tag: '音乐', source: 'inferred', approved: true });

    render(<ProfilePage />);
    fireEvent.click(await screen.findByRole('button', { name: /确认/ }));
    await waitFor(() => expect(mockConfirmInterest).toHaveBeenCalledWith(2));
  });

  it('学生可以移除推断兴趣', async () => {
    mockAuth.role = 'student';
    mockGetAttributes.mockResolvedValue({ current: null });
    mockGetAttributeHistory.mockResolvedValue({ history: [] });
    mockListInterests.mockResolvedValue([
      { id: 2, tag: '音乐', source: 'inferred', approved: false },
    ]);
    mockRemoveInterest.mockResolvedValue({});

    render(<ProfilePage />);
    fireEvent.click(await screen.findByRole('button', { name: /移除/ }));
    await waitFor(() => expect(mockRemoveInterest).toHaveBeenCalledWith(2));
  });

  it('家长可以保存推荐边界', async () => {
    mockGetAttributes.mockResolvedValue({ current: null });
    mockGetAttributeHistory.mockResolvedValue({ history: [] });
    mockListInterests.mockResolvedValue([]);

    render(<ProfilePage />);
    fireEvent.click(await screen.findByRole('button', { name: /保存推荐边界/ }));

    await waitFor(() => {
      expect(mockUpdateRecommendationBoundary).toHaveBeenCalledWith(2, {
        allowed_platforms: ['bilibili'],
        blocked_keywords: [],
        daily_limit: 3,
        allow_entertainment_interests: false,
      });
    });
  });

  it('添加兴趣后只刷新兴趣列表，避免整页重新加载', async () => {
    mockAuth.role = 'student';
    mockGetAttributes.mockResolvedValue({ current: null });
    mockGetAttributeHistory.mockResolvedValue({ history: [] });
    mockListInterests.mockResolvedValue([]);
    mockAddInterest.mockResolvedValue({ id: 3, tag: '篮球', source: 'manual', approved: true });

    render(<ProfilePage />);

    const input = await screen.findByPlaceholderText('添加兴趣，如 篮球');
    fireEvent.change(input, { target: { value: '篮球' } });
    fireEvent.click(screen.getByRole('button', { name: /添加/ }));

    await waitFor(() => expect(mockAddInterest).toHaveBeenCalledWith(2, '篮球'));
    await waitFor(() => expect(mockListInterests).toHaveBeenCalledTimes(2));
    expect(mockGetAttributes).toHaveBeenCalledTimes(1);
    expect(mockGetAttributeHistory).toHaveBeenCalledTimes(1);
    expect(mockGetProfileSummary).toHaveBeenCalledTimes(1);
  });

  it('画像不完整时显示冷启动补全入口', async () => {
    mockAuth.role = 'student';
    mockGetAttributes.mockResolvedValue({ current: null });
    mockGetAttributeHistory.mockResolvedValue({ history: [] });
    mockListInterests.mockResolvedValue([]);
    mockGetProfileSummary.mockResolvedValue({
      student_id: 2,
      needs_onboarding: true,
      missing_fields: ['grade', 'semester'],
      summary: { interests: [] },
    });

    render(<ProfilePage />);

    expect(await screen.findByText('补全学习画像')).toBeInTheDocument();
  });

  it('属性接口不可用时仍显示冷启动补全入口', async () => {
    mockAuth.role = 'student';
    mockGetAttributes.mockRejectedValue(new Error('profile not initialized'));
    mockGetAttributeHistory.mockResolvedValue({ history: [] });
    mockListInterests.mockResolvedValue([]);
    mockGetProfileSummary.mockResolvedValue({
      student_id: 2,
      needs_onboarding: true,
      missing_fields: ['grade', 'semester'],
      summary: { interests: [] },
    });

    render(<ProfilePage />);

    expect(await screen.findByText('补全学习画像')).toBeInTheDocument();
    expect(screen.getByText(/学习档案尚未初始化/)).toBeInTheDocument();
  });

  it('保存冷启动画像后调用补全接口', async () => {
    mockAuth.role = 'student';
    mockGetAttributes.mockResolvedValue({ current: null });
    mockGetAttributeHistory.mockResolvedValue({ history: [] });
    mockListInterests.mockResolvedValue([]);
    mockGetProfileSummary.mockResolvedValue({
      student_id: 2,
      needs_onboarding: true,
      missing_fields: ['grade'],
      summary: { interests: [] },
    });
    mockSaveProfileOnboarding.mockResolvedValue({
      student_id: 2,
      needs_onboarding: false,
      missing_fields: [],
      summary: { grade: '八年级', semester: '上册', interests: [] },
    });

    render(<ProfilePage />);

    fireEvent.click(await screen.findByRole('button', { name: /补全学习画像/ }));
    fireEvent.change(await screen.findByLabelText('年级'), { target: { value: '八年级' } });
    fireEvent.change(await screen.findByLabelText('学期'), { target: { value: '上册' } });
    fireEvent.click(screen.getByRole('button', { name: /保存画像/ }));

    await waitFor(() => expect(mockSaveProfileOnboarding).toHaveBeenCalled());
  });

  it('未选中学生时不请求默认测试学生数据', async () => {
    mockAuth.role = 'parent';
    mockAuth.activeChildId = null;
    mockAuth.userId = 1;

    render(<ProfilePage />);

    await waitFor(() => {
      expect(mockGetAttributes).not.toHaveBeenCalled();
      expect(mockGetProfileSummary).not.toHaveBeenCalled();
      expect(mockListInterests).not.toHaveBeenCalled();
    });
  });
});
