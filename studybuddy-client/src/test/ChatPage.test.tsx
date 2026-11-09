/**
 * ChatPage 组件测试。
 *
 * mock 依赖：authStore（提供 token/role）、chatApi（createSession/sendMessage 流式）
 * 测：渲染引导文案、输入消息、发送后 user 气泡出现、SSE 流追加 agent 回复
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';

let mockRole = 'parent';

// mock authStore
vi.mock('@/features/auth/store', () => ({
  useAuthStore: () => ({
    token: 'mock-token',
    role: mockRole,
    activeChildId: 2,
    userId: 1,
  }),
}));

// mock antd App wrapper（App.useApp 需要 context，测试里 stub 成空 message）
vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  const AppMock = ({ children }: { children: ReactNode }) => <>{children}</>;
  AppMock.useApp = () => ({
    message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
    modal: { confirm: vi.fn(), info: vi.fn() },
    notification: { info: vi.fn() },
  });
  return {
    ...actual,
    App: AppMock,
  };
});

// mock chatApi（用 hoisted 避免 TDZ）
const {
  mockCreateSession,
  mockSendMessage,
  mockListSessions,
  mockGetMessages,
  mockGetProfileSummary,
  mockListStudyPlans,
  mockCreateStudyPlan,
  mockUpdateStudyPlanItem,
  mockGetLearningFlowEntry,
  mockCreateBatch,
  mockUploadPhotos,
  mockDeleteEmptyBatch,
  mockConfirmAnswerReview,
  mockContinueTaskItem,
} = vi.hoisted(
  () => ({
    mockCreateSession: vi.fn().mockResolvedValue({ id: 1 }),
    mockSendMessage: vi.fn(),
    // 默认返回空列表 → ChatPage 会走 createSession 新建会话
    mockListSessions: vi.fn().mockResolvedValue([]),
    mockGetMessages: vi.fn().mockResolvedValue([]),
    mockGetProfileSummary: vi.fn(),
    mockListStudyPlans: vi.fn(),
    mockCreateStudyPlan: vi.fn(),
    mockUpdateStudyPlanItem: vi.fn(),
    mockGetLearningFlowEntry: vi.fn(),
    mockCreateBatch: vi.fn(),
    mockUploadPhotos: vi.fn(),
    mockDeleteEmptyBatch: vi.fn(),
    mockConfirmAnswerReview: vi.fn(),
    // U-042：继续学习 -> 后端建 task session + 触发 agent（mock 成 async generator）
    mockContinueTaskItem: vi.fn().mockImplementation(async function* () {
      yield {
        type: 'session',
        session: {
          id: 2,
          user_id: 1,
          student_id: 1,
          title: '学习任务',
          created_at: '',
          session_type: 'task',
          plan_id: 10,
          plan_item_id: 100,
          status: 'active',
        },
      };
      yield { type: 'text', content: '我们开始这个任务吧。' };
      yield { type: 'done', content: '我们开始这个任务吧。' };
    }),
  }),
);
vi.mock('@/features/chat/api', () => ({
  chatApi: {
    createSession: mockCreateSession,
    sendMessage: mockSendMessage,
    listSessions: mockListSessions,
    getMessages: mockGetMessages,
    continueTaskItem: mockContinueTaskItem,
  },
}));
vi.mock('@/features/p2/api', () => ({
  p2Api: {
    getProfileSummary: mockGetProfileSummary,
    listStudyPlans: mockListStudyPlans,
    createStudyPlan: mockCreateStudyPlan,
    updateStudyPlanItem: mockUpdateStudyPlanItem,
  },
}));
vi.mock('@/features/learning/learningFlow', () => ({
  learningFlowApi: {
    getEntry: mockGetLearningFlowEntry,
  },
}));
vi.mock('@/features/exams/examBatch', () => ({
  examBatchApi: {
    createBatch: mockCreateBatch,
    uploadPhotos: mockUploadPhotos,
    deleteEmptyBatch: mockDeleteEmptyBatch,
    confirmAnswerReview: mockConfirmAnswerReview,
  },
}));
vi.mock('@/features/materials/api', () => ({
  materialApi: {
    upload: vi.fn(),
  },
}));

vi.mock('@/features/family_goal/api', async () => {
  const actual = await vi.importActual<typeof import('@/features/family_goal/api')>(
    '@/features/family_goal/api',
  );
  return {
    ...actual,
    familyGoalApi: { ...actual.familyGoalApi, todayTasks: vi.fn().mockResolvedValue([]) },
  };
});

import ChatPage from '@/features/chat/pages/ChatPage';
import { MarkdownContent } from '@/shared/components/MarkdownContent';
import { useChatStore } from '@/features/chat/store';
import { familyGoalApi } from '@/features/family_goal/api';
import type { FamilyTodayTask } from '@/types';

const mockTodayTasks = vi.mocked(familyGoalApi.todayTasks);

function familyTask(overrides: Partial<FamilyTodayTask> = {}): FamilyTodayTask {
  return {
    occurrence_id: 11,
    task_id: 21,
    goal_id: 31,
    student_id: 1,
    title: '默写英语单词',
    description: null,
    goal_title: '英语默写',
    repeat_type: 'once',
    status: 'pending',
    occurrence_date: '2026-09-30',
    reward_amount: '5.00',
    submit_note: null,
    reject_reason: null,
    submitted_at: null,
    reviewed_at: null,
    evidence: [],
    ...overrides,
  };
}

async function* streamFrom(events: Array<Record<string, unknown>>) {
  for (const event of events) {
    yield event;
  }
}

async function sendUserMessage(content: string) {
  fireEvent.change(screen.getByPlaceholderText(/输入消息/), { target: { value: content } });
  fireEvent.click(screen.getByRole('button', { name: /send|发送/ }));
}

describe('ChatPage', () => {
  beforeEach(() => {
    useChatStore.getState().reset();
    mockRole = 'parent';
    mockCreateSession.mockReset();
    mockSendMessage.mockReset();
    mockListSessions.mockReset();
    mockGetMessages.mockReset();
    mockGetProfileSummary.mockReset();
    mockListStudyPlans.mockReset();
    mockCreateStudyPlan.mockReset();
    mockUpdateStudyPlanItem.mockReset();
    mockGetLearningFlowEntry.mockReset();
    mockCreateBatch.mockReset();
    mockUploadPhotos.mockReset();
    mockDeleteEmptyBatch.mockReset();
    mockConfirmAnswerReview.mockReset();
    mockContinueTaskItem.mockReset();
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });
    window.location.hash = '';
    localStorage.removeItem('sb_profile_prompt_snooze_until');
    mockTodayTasks.mockResolvedValue([]);
    mockCreateSession.mockResolvedValue({ id: 1 });
    mockSendMessage.mockImplementation(() => streamFrom([]));
    mockListSessions.mockResolvedValue([]);
    mockContinueTaskItem.mockImplementation(async function* () {
      yield {
        type: 'session',
        session: {
          id: 2,
          user_id: 1,
          student_id: 1,
          title: '学习任务',
          created_at: '',
          session_type: 'task',
          plan_id: 10,
          plan_item_id: 100,
          status: 'active',
        },
      };
      yield { type: 'text', content: '我们开始这个任务吧。' };
      yield { type: 'done', content: '我们开始这个任务吧。' };
    });
    mockGetMessages.mockResolvedValue([]);
    mockGetProfileSummary.mockResolvedValue({
      student_id: 2,
      needs_onboarding: false,
      missing_fields: [],
      summary: { interests: [] },
    });
    mockListStudyPlans.mockResolvedValue([]);
    mockCreateStudyPlan.mockResolvedValue({});
    mockUpdateStudyPlanItem.mockResolvedValue({});
    mockGetLearningFlowEntry.mockResolvedValue({
      kind: 'empty',
      title: '今天想先学什么',
      description: '告诉助手一道不会的题、一个知识点，或者今天的计划。',
      primary_label: '开始学习',
      prompt: '',
      source_type: null,
      source_id: null,
      evidence: [],
    });
    mockCreateBatch.mockResolvedValue({ id: 88 });
    mockUploadPhotos.mockResolvedValue({ photo_material_ids: [101] });
    mockDeleteEmptyBatch.mockResolvedValue(undefined);
    mockConfirmAnswerReview.mockResolvedValue({ status: 'confirmed', items: [] });
  });

  it('渲染会话工具条（parent 角色）', async () => {
    render(<ChatPage />);
    // ChatPage 初始化会调 listSessions → 空列表则 createSession 新建
    await waitFor(
      () => {
        expect(mockListSessions).toHaveBeenCalled();
      },
      { timeout: 3000 },
    );
    // 会话工具条出现（新对话按钮）
    await waitFor(
      () => {
        expect(screen.getByText('新对话')).toBeInTheDocument();
      },
      { timeout: 3000 },
    );
  });

  it('学生打开 Today 时显示任务折叠浮条和聊天输入框', async () => {
    mockRole = 'student';
    const scrollIntoView = vi.mocked(Element.prototype.scrollIntoView);
    scrollIntoView.mockClear();
    render(<ChatPage />);

    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());
    expect(await screen.findByText('今天还没有计划')).toBeInTheDocument();
    expect(scrollIntoView).not.toHaveBeenCalled();
    // Stitch 设计：today 模式也显示对话输入框
    expect(await screen.findByTestId('chat-message-input')).toBeInTheDocument();
  });

  it('学生点击继续学习后才显示同一会话的聊天，并可返回后恢复', async () => {
    mockRole = 'student';
    mockListStudyPlans.mockResolvedValue([
      {
        id: 9,
        student_id: 1,
        title: '今日英语计划',
        focus: null,
        status: 'active',
        planned_date: new Date().toLocaleDateString('sv-SE'),
        is_overdue: false,
        overdue_days: 0,
        reminder_message: null,
        created_by: 1,
        created_at: '2026-07-13 08:00:00',
        items: [
          {
            id: 90,
            title: '复习一般过去时',
            target: null,
            minutes: 20,
            status: 'todo',
            related_tags: [],
            sort_order: 0,
            completed_at: null,
          },
        ],
      },
    ]);
    mockGetLearningFlowEntry.mockResolvedValue({
      kind: 'continue_plan',
      title: '继续「今日英语计划」',
      description: '先完成「复习一般过去时」',
      primary_label: '继续学习',
      prompt: '我想继续今日英语计划',
      source_type: 'study_plan',
      source_id: 9,
      evidence: ['今天', '1 个待完成任务', '20 分钟'],
    });
    render(<ChatPage />);

    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());
    expect((await screen.findAllByText('复习一般过去时')).length).toBeGreaterThan(0);
    // Stitch 设计：today 模式也显示输入框，点击浮条进入 learning 模式
    expect(screen.getByTestId('chat-message-input')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '继续学习' }));

    // U-042：点继续学习 -> 调 continueTaskItem 建 task session + 触发 agent，不再预填输入框
    await waitFor(() => expect(mockContinueTaskItem).toHaveBeenCalled());
    expect(mockSendMessage).not.toHaveBeenCalled();
  });

  it('学习建议暂时不可用时仍按当前计划预填任务', async () => {
    mockRole = 'student';
    mockGetLearningFlowEntry.mockRejectedValue(new Error('network'));
    mockListStudyPlans.mockResolvedValue([
      {
        id: 10,
        student_id: 1,
        title: '今日数学计划',
        focus: null,
        status: 'active',
        planned_date: new Date().toLocaleDateString('sv-SE'),
        is_overdue: false,
        overdue_days: 0,
        reminder_message: null,
        created_by: 1,
        created_at: '2026-07-13 08:00:00',
        items: [
          {
            id: 100,
            title: '复习函数',
            target: null,
            minutes: 20,
            status: 'todo',
            related_tags: [],
            sort_order: 0,
            completed_at: null,
          },
        ],
      },
    ]);

    render(<ChatPage />);
    fireEvent.click(await screen.findByRole('button', { name: '继续学习' }));

    // U-042：继续学习调 continueTaskItem，不再预填输入框
    await waitFor(() => expect(mockContinueTaskItem).toHaveBeenCalled());
    expect(mockSendMessage).not.toHaveBeenCalled();
  });

  it('完成任务后清除旧草稿并为下一项刷新预填内容', async () => {
    mockRole = 'student';
    const basePlan = {
      id: 11,
      student_id: 1,
      title: '英语复习计划',
      focus: null,
      status: 'active',
      planned_date: new Date().toLocaleDateString('sv-SE'),
      is_overdue: false,
      overdue_days: 0,
      reminder_message: null,
      created_by: 1,
      created_at: '2026-07-13 08:00:00',
      items: [
        {
          id: 110,
          title: '复习一般过去时',
          target: null,
          minutes: 20,
          status: 'todo',
          related_tags: [],
          sort_order: 0,
          completed_at: null,
        },
        {
          id: 111,
          title: '整理两道英语错题',
          target: null,
          minutes: 15,
          status: 'todo',
          related_tags: [],
          sort_order: 1,
          completed_at: null,
        },
      ],
    };
    mockListStudyPlans
      .mockResolvedValueOnce([basePlan])
      .mockResolvedValueOnce([
        {
          ...basePlan,
          items: [
            { ...basePlan.items[0], status: 'done', completed_at: '2026-07-13 09:00:00' },
            basePlan.items[1],
          ],
        },
      ]);
    mockGetLearningFlowEntry
      .mockResolvedValueOnce({
        kind: 'continue_plan',
        title: '继续英语复习计划',
        description: '先复习一般过去时',
        primary_label: '继续学习',
        prompt: '开始复习一般过去时',
        source_type: 'study_plan',
        source_id: 11,
        evidence: [],
      })
      .mockResolvedValueOnce({
        kind: 'continue_plan',
        title: '继续英语复习计划',
        description: '接着整理英语错题',
        primary_label: '继续学习',
        prompt: '开始整理两道英语错题',
        source_type: 'study_plan',
        source_id: 11,
        evidence: [],
      });

    render(<ChatPage />);
    fireEvent.click(await screen.findByRole('button', { name: '继续学习' }));

    // U-042：继续学习调 continueTaskItem
    await waitFor(() => expect(mockContinueTaskItem).toHaveBeenCalled());
    fireEvent.change(await screen.findByTestId('chat-message-input'), {
      target: { value: '上一项未发送草稿' },
    });
    // U-044：点完成学习 -> 先弹证据框（P0 门禁，无证据不完成）
    fireEvent.click(screen.getByRole('button', { name: '完成学习' }));
    const evidenceInput = await screen.findByPlaceholderText(/背出了不规则动词的过去式/);
    fireEvent.change(evidenceInput, { target: { value: '复习了时态并说出错因' } });
    fireEvent.click(screen.getByRole('button', { name: '确认完成' }));
    // 完成后发消息让 AI 评估收尾（completeTask）
    await waitFor(() => expect(mockSendMessage).toHaveBeenCalled());
  });

  it('学生打开已有历史会话时看到真实今日计划任务而不是大推荐横幅', async () => {
    mockRole = 'student';
    mockListSessions.mockResolvedValue([
      { id: 42, user_id: 1, student_id: 1, title: '昨天的学习', created_at: '2026-07-12 19:00:00' },
    ]);
    mockGetMessages.mockResolvedValue([
      {
        id: 88,
        role: 'assistant',
        content: '这是昨天的学习记录',
        created_at: '2026-07-12 19:01:00',
      },
    ]);
    mockListStudyPlans.mockResolvedValue([
      {
        id: 10,
        student_id: 1,
        title: '今日数学计划',
        focus: null,
        status: 'active',
        planned_date: new Date().toLocaleDateString('sv-SE'),
        is_overdue: false,
        overdue_days: 0,
        reminder_message: null,
        created_by: 1,
        created_at: '2026-07-13 08:00:00',
        items: [
          {
            id: 100,
            title: '复习函数',
            target: null,
            minutes: 20,
            status: 'todo',
            related_tags: [],
            sort_order: 0,
            completed_at: null,
          },
        ],
      },
    ]);

    render(<ChatPage />);

    // Stitch 设计：today 模式显示任务折叠浮条 + 对话区
    expect((await screen.findAllByText('复习函数')).length).toBeGreaterThan(0);
    // U-042：点继续学习 -> 切 task session，显示 agent 回复（不再显示主会话历史）
    fireEvent.click(screen.getByRole('button', { name: '继续学习' }));
    await waitFor(() => expect(mockContinueTaskItem).toHaveBeenCalled());
    expect(await screen.findByText('我们开始这个任务吧。')).toBeInTheDocument();
  });

  it('学生只恢复自己的长期会话，不会误用其他学生的会话', async () => {
    mockRole = 'student';
    mockListSessions.mockResolvedValue([
      { id: 41, user_id: 1, student_id: 99, title: '其他学生', created_at: '2026-07-12 19:00:00' },
      { id: 42, user_id: 1, student_id: 1, title: '我的学习', created_at: '2026-07-12 20:00:00' },
    ]);

    render(<ChatPage />);

    await waitFor(() => expect(mockGetMessages).toHaveBeenCalledWith(42));
    expect(mockGetMessages).not.toHaveBeenCalledWith(41);
    expect(mockCreateSession).not.toHaveBeenCalled();
    expect(screen.queryByText('新对话')).not.toBeInTheDocument();
  });

  it('辅导者空会话工作台保持原有入口', async () => {
    render(<ChatPage />);

    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());
    expect(await screen.findByText('今天先处理哪件学习任务？')).toBeInTheDocument();
    expect(screen.getByText('查学情')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '开始学习' })).not.toBeInTheDocument();
    expect(mockGetLearningFlowEntry).not.toHaveBeenCalled();
  });

  it('画像缺失时在聊天空态提示补全学习画像', async () => {
    mockGetProfileSummary.mockResolvedValue({
      student_id: 2,
      needs_onboarding: true,
      missing_fields: ['grade', 'semester', 'study_preferences'],
      summary: { interests: [] },
    });

    render(<ChatPage />);

    await waitFor(() => expect(mockGetProfileSummary).toHaveBeenCalledWith(2));
    expect(await screen.findByText('学习画像待补全')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '编辑画像' })).toBeInTheDocument();
  });

  it('学生空会话且画像缺年级时自动触发冷启动（不发用户气泡）', async () => {
    mockRole = 'student';
    mockGetProfileSummary.mockResolvedValue({
      student_id: 1,
      needs_onboarding: true,
      missing_fields: ['grade', 'semester', 'study_preferences'],
      summary: { interests: [] },
    });
    mockSendMessage.mockImplementation(() => streamFrom([]));

    render(<ChatPage />);

    await waitFor(() => expect(mockSendMessage).toHaveBeenCalled(), { timeout: 3000 });
    // 冷启动触发：content 为空字符串、不发用户气泡（skipUserMessage）
    const call = mockSendMessage.mock.calls[0];
    expect(call[1]).toBe('');
  });

  it('点击稍后持久 snooze 画像提示（写入 localStorage 并隐藏）', async () => {
    localStorage.removeItem('sb_profile_prompt_snooze_until');
    mockGetProfileSummary.mockResolvedValue({
      student_id: 2,
      needs_onboarding: true,
      missing_fields: ['grade', 'semester', 'study_preferences'],
      summary: { interests: [] },
    });

    render(<ChatPage />);
    await waitFor(() => expect(mockGetProfileSummary).toHaveBeenCalledWith(2));
    expect(await screen.findByText('学习画像待补全')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '稍后' }));

    await waitFor(() => {
      expect(Number(localStorage.getItem('sb_profile_prompt_snooze_until') || 0)).toBeGreaterThan(Date.now());
    });
    expect(screen.queryByText('学习画像待补全')).not.toBeInTheDocument();
  });

  it('输入框存在且可输入', async () => {
    render(<ChatPage />);
    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());
    const input = screen.getByPlaceholderText(/输入消息/);
    expect(input).toBeInTheDocument();
    fireEvent.change(input, { target: { value: '测试消息' } });
    expect(input).toHaveValue('测试消息');
  });

  it('支持从 URL 预填复盘问题', async () => {
    const prompt = '帮我复盘逾期学习计划';
    window.location.hash = `#/chat?student_id=2&prompt=${encodeURIComponent(prompt)}`;

    render(<ChatPage />);
    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());

    expect(screen.getByPlaceholderText(/输入消息/)).toHaveValue(prompt);
  });

  it('学习页继续卡片带 continue_task_item 时自动进入 task session', async () => {
    mockRole = 'student';
    window.location.hash = '#/chat?continue_task_item=100';
    mockListStudyPlans.mockResolvedValue([
      {
        id: 10,
        student_id: 1,
        title: '今日计划',
        focus: null,
        status: 'active',
        planned_date: new Date().toLocaleDateString('sv-SE'),
        is_overdue: false,
        overdue_days: 0,
        reminder_message: null,
        created_by: 1,
        created_at: '2026-07-13 08:00:00',
        items: [
          {
            id: 100,
            title: '任务一',
            target: null,
            minutes: 20,
            status: 'todo',
            related_tags: [],
            sort_order: 0,
            completed_at: null,
          },
        ],
      },
    ]);
    mockGetLearningFlowEntry.mockResolvedValue({
      kind: 'continue_plan',
      title: '继续今日计划',
      description: '先完成任务一',
      primary_label: '继续学习',
      prompt: '开始任务一',
      source_type: 'study_plan',
      source_id: 10,
      item_id: 100,
      evidence: [],
    });

    render(<ChatPage />);

    // init 完成后自动调 continueTaskItem 建/恢复 task session，不再预填主会话
    await waitFor(() => expect(mockContinueTaskItem).toHaveBeenCalled());
    expect(mockContinueTaskItem.mock.calls[0][0]).toBe(1);
    expect(mockContinueTaskItem.mock.calls[0][1]).toBe(100);
    expect(mockSendMessage).not.toHaveBeenCalled();
  });

  it('从试卷结果返回任务后自动读取正式结果复盘', async () => {
    mockRole = 'student';
    localStorage.setItem(
      'studybuddy-nav-1',
      JSON.stringify({ sessionId: 2, activeTaskSessionId: 2, mainSessionId: 1 }),
    );
    window.location.hash = '#/chat?continue_task_item=100&practice_exam_record=955';
    mockListSessions.mockResolvedValue([
      {
        id: 1,
        user_id: 1,
        student_id: 1,
        title: '主会话',
        created_at: '',
        session_type: 'main',
        status: 'active',
      },
      {
        id: 2,
        user_id: 1,
        student_id: 1,
        title: '任务一',
        created_at: '',
        session_type: 'task',
        plan_id: 10,
        plan_item_id: 100,
        status: 'active',
      },
    ]);
    mockListStudyPlans.mockResolvedValue([
      {
        id: 10,
        student_id: 1,
        title: '今日计划',
        focus: null,
        status: 'active',
        planned_date: new Date().toLocaleDateString('sv-SE'),
        is_overdue: false,
        overdue_days: 0,
        reminder_message: null,
        created_by: 1,
        created_at: '2026-08-19 08:00:00',
        items: [
          {
            id: 100,
            title: '任务一',
            target: null,
            minutes: 20,
            status: 'in_progress',
            related_tags: [],
            sort_order: 0,
            completed_at: null,
          },
        ],
      },
    ]);
    mockGetLearningFlowEntry.mockResolvedValue({
      kind: 'continue_plan',
      title: '继续今日计划',
      description: '先完成任务一',
      primary_label: '继续学习',
      prompt: '开始任务一',
      source_type: 'study_plan',
      source_id: 10,
      item_id: 100,
      evidence: [],
    });
    mockSendMessage.mockImplementation(() => streamFrom([{ type: 'done', content: '' }]));

    render(<ChatPage />);

    await waitFor(() =>
      expect(mockSendMessage).toHaveBeenCalledWith(
        2,
        expect.stringContaining('exam_record_id=955'),
        '我已经完成这次练习，请根据正式结果帮我复盘。',
        expect.any(AbortSignal),
      ),
    );
  });

  it('活动任务与结果来源不同时先切回正确任务再复盘', async () => {
    mockRole = 'student';
    localStorage.setItem(
      'studybuddy-nav-1',
      JSON.stringify({ sessionId: 3, activeTaskSessionId: 3, mainSessionId: 1 }),
    );
    window.location.hash = '#/chat?continue_task_item=100&practice_exam_record=955';
    mockListSessions.mockResolvedValue([
      { id: 1, user_id: 1, student_id: 1, title: '主会话', created_at: '', session_type: 'main', status: 'active' },
      { id: 3, user_id: 1, student_id: 1, title: '另一个任务', created_at: '', session_type: 'task', plan_id: 11, plan_item_id: 999, status: 'active' },
    ]);
    mockListStudyPlans.mockResolvedValue([
      {
        id: 10,
        student_id: 1,
        title: '今日计划',
        status: 'active',
        planned_date: new Date().toLocaleDateString('sv-SE'),
        items: [{ id: 100, title: '正确任务', minutes: 20, status: 'in_progress', related_tags: [], sort_order: 0, completed_at: null }],
      },
    ]);
    mockGetLearningFlowEntry.mockResolvedValue({ kind: 'continue_plan', item_id: 100, evidence: [] });
    mockSendMessage.mockImplementation(() => streamFrom([{ type: 'done', content: '' }]));

    render(<ChatPage />);

    await waitFor(() => expect(mockGetMessages).toHaveBeenCalledWith(3));
    await waitFor(() => expect(mockContinueTaskItem).toHaveBeenCalled());
    expect(mockContinueTaskItem.mock.calls.at(-1)?.[1]).toBe(100);
    await waitFor(() =>
      expect(mockSendMessage).toHaveBeenCalledWith(
        2,
        expect.stringContaining('exam_record_id=955'),
        '我已经完成这次练习，请根据正式结果帮我复盘。',
        expect.any(AbortSignal),
      ),
    );
  });

  it('当前会话标题为新对话时不和新建按钮重名', async () => {
    mockListSessions.mockResolvedValue([
      { id: 42, user_id: 1, student_id: 2, title: '新对话', created_at: '2026-07-06 19:00:00' },
    ]);
    mockGetMessages.mockResolvedValue([]);

    render(<ChatPage />);

    await waitFor(() => expect(mockGetMessages).toHaveBeenCalledWith(42));
    expect(screen.getAllByText('新对话')).toHaveLength(1);
    expect(screen.getByText('当前对话')).toBeInTheDocument();
  });

  it('发送消息后出现 user 气泡', async () => {
    // mock sendMessage 返回空 async generator（立即结束）
    async function* emptyStream() {}
    mockSendMessage.mockReturnValue(emptyStream());

    render(<ChatPage />);
    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());

    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '你好' } });

    // 发送按钮：用 aria-label 或最后含 send 图标的按钮
    const sendButton = screen.getByRole('button', { name: /send|发送/ });
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(screen.getByText('你好')).toBeInTheDocument();
    });
  });

  it('拍题批改上传后先发送 Markdown 识别意图，不走普通素材总结', async () => {
    async function* emptyStream() {}
    mockSendMessage.mockReturnValue(emptyStream());

    render(<ChatPage />);
    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());

    fireEvent.click(screen.getByTitle('上传：错题或素材'));
    await waitFor(() =>
      expect(document.querySelector('input[type="file"][accept="image/*"]')).toBeInTheDocument(),
    );
    const fileInput = document.querySelector('input[type="file"][accept="image/*"]') as HTMLInputElement;
    const file = new File(['fake image'], 'physics-homework.jpg', { type: 'image/jpeg' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    expect(await screen.findByText(/已选 1 张题目照片/)).toBeInTheDocument();
    expect(screen.queryByLabelText('学科')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '上传 1 张并识别' }));

    await waitFor(() => expect(mockCreateBatch).toHaveBeenCalledTimes(1));
    expect(mockCreateBatch.mock.calls[0][0]).toMatchObject({ subject: 'auto' });
    await waitFor(() => expect(mockSendMessage).toHaveBeenCalledTimes(1));
    const [, content] = mockSendMessage.mock.calls[0];
    expect(content).toContain('[拍题批改]');
    expect(content).toContain('请先把照片识别成 Markdown');
    expect(content).toContain('确认识别稿后');
    expect(content).toContain('正确答案、错因和知识点');
    expect(content).toContain('如果识别错了，可以直接告诉我第几题哪里错了');
    expect(content).toContain('我会按你修正后的作答再批改');
    expect(content).not.toContain('我上传了一份素材');
  });

  it('选择素材文件后上传菜单立即关闭，不与素材弹窗重叠', async () => {
    render(<ChatPage />);
    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());

    // 打开上传菜单
    fireEvent.click(screen.getByTitle('上传：错题或素材'));
    await waitFor(() => expect(screen.getByText('拍题批改')).toBeInTheDocument());

    // 选择素材文件（Upload 组件内部的 input）
    const uploadInput = document.querySelector('.ant-upload input[type="file"]') as HTMLInputElement;
    expect(uploadInput).toBeInTheDocument();
    const file = new File(['fake'], 'words.png', { type: 'image/png' });
    fireEvent.change(uploadInput, { target: { files: [file] } });

    // 素材弹窗出现
    expect(await screen.findByLabelText('素材名称')).toBeInTheDocument();

    // 上传菜单（拍题批改）应已关闭，不再遮挡弹窗
    await waitFor(() => expect(screen.queryByText('拍题批改')).not.toBeInTheDocument());
  });

  it('聊天输入框粘贴图片后打开拍题批改确认弹窗', async () => {
    render(<ChatPage />);
    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());

    const input = screen.getByPlaceholderText(/输入消息/);
    const file = new File(['fake image'], 'wechat-photo.png', { type: 'image/png' });
    fireEvent.paste(input, {
      clipboardData: {
        files: [file],
        items: [
          {
            kind: 'file',
            type: 'image/png',
            getAsFile: () => file,
          },
        ],
      },
    });

    expect(await screen.findByText(/已选 1 张题目照片/)).toBeInTheDocument();
    expect(screen.getByDisplayValue(/wechat-photo/)).toBeInTheDocument();
  });

  it('工具调用执行中显示耗时和阶段进度', async () => {
    async function* toolProgressStream() {
      yield {
        type: 'tool_call' as const,
        id: 'tool-1',
        name: 'grade_homework_photo',
        input: { batch_id: 12 },
        started_at: 1000,
      };
      yield {
        type: 'tool_progress' as const,
        id: 'tool-1',
        name: 'grade_homework_photo',
        elapsed_ms: 15000,
        message: '正在识别图片，已等待 15 秒',
      };
    }
    mockSendMessage.mockReturnValue(toolProgressStream());

    render(<ChatPage />);
    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText(/输入消息/), { target: { value: '批改 batch 12' } });
    fireEvent.click(screen.getByRole('button', { name: /send|发送/ }));

    expect(await screen.findByText('拍题批改')).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText(/15 秒/).length).toBeGreaterThan(0));
    expect(screen.getByText(/正在识别图片/)).toBeInTheDocument();
  });

  it('工具调用收到 error 事件后显示失败原因', async () => {
    async function* toolErrorStream() {
      yield {
        type: 'tool_call' as const,
        id: 'tool-1',
        name: 'create_exam',
        input: { subject: 'english' },
      };
      yield { type: 'error' as const, message: '后端异常' };
    }
    mockSendMessage.mockReturnValue(toolErrorStream());

    render(<ChatPage />);
    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());

    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '出题' } });
    fireEvent.click(screen.getByRole('button', { name: /send|发送/ }));

    await waitFor(() => {
      expect(screen.getAllByText('出题').length).toBeGreaterThan(0);
      expect(screen.getByText(/工具执行失败：后端异常/)).toBeInTheDocument();
      expect(screen.getByText(/^失败：后端异常$/)).toBeInTheDocument();
    });
  });

  it('拍题 Markdown 识别后显示逐题作答核对并确认批改', async () => {
    mockSendMessage
      .mockReturnValueOnce(
        streamFrom([
          {
            type: 'tool_call',
            id: 'tool-1',
            name: 'recognize_homework_photo_markdown',
            input: { batch_id: 88 },
          },
          {
            type: 'tool_result',
            id: 'tool-1',
            name: 'recognize_homework_photo_markdown',
            output: JSON.stringify({
              batch_id: 88,
              recognized_markdown: '1. 题目\\n学生作答：D',
              answer_review_state: {
                batch_id: 88,
                recognized_markdown: '1. 题目\\n学生作答：D',
                status: 'pending_review',
                items: [
                  {
                    question_no: '1',
                    detected_answer: 'D',
                    confirmed_answer: null,
                    confidence: 'low',
                    needs_review: true,
                    review_reason: '圈选痕迹太淡',
                    answer_type: 'choice',
                    source_excerpt: '1. 题目',
                    skipped: false,
                  },
                ],
              },
            }),
          },
        ]),
      )
      .mockReturnValueOnce(streamFrom([]));

    render(<ChatPage />);
    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());

    await sendUserMessage('识别批次 88');

    expect(await screen.findByText('核对学生作答')).toBeInTheDocument();
    const answerInput = await screen.findByLabelText('第1题确认作答');
    fireEvent.change(answerInput, { target: { value: 'B' } });
    fireEvent.click(screen.getByRole('button', { name: '确认后批改' }));

    await waitFor(() => expect(mockConfirmAnswerReview).toHaveBeenCalledTimes(1));
    expect(mockConfirmAnswerReview.mock.calls[0][0]).toBe(88);
    expect(mockConfirmAnswerReview.mock.calls[0][1].items[0].confirmed_answer).toBe('B');
    await waitFor(() => expect(mockSendMessage).toHaveBeenCalledTimes(2));
    expect(mockSendMessage.mock.calls[1][1]).toContain('请基于我刚确认的逐题作答进行批改');
  });

  it('工具调用失败后展示可复制错误信息', async () => {
    mockSendMessage.mockReturnValue(
      streamFrom([
        {
          type: 'tool_call',
          id: 'tool-1',
          name: 'create_exam',
          input: { subject: 'english' },
        },
        { type: 'error', message: '后端异常' },
      ]),
    );

    render(<ChatPage />);
    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());

    await sendUserMessage('出题');

    expect(await screen.findByText('出错了，可以复制给开发者')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '复制错误信息' }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(1));
    const copied = (navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(copied).toContain('context: chat:sse-error');
    expect(copied).toContain('message: 后端异常');
    expect(copied).toContain('path:');
    expect(copied).not.toContain('mock-token');
  });

  it('拍题上传失败后展示可复制错误信息', async () => {
    mockCreateBatch.mockRejectedValueOnce(new Error('network error'));

    render(<ChatPage />);
    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());

    fireEvent.click(screen.getByTitle('上传：错题或素材'));
    await waitFor(() =>
      expect(document.querySelector('input[type="file"][accept="image/*"]')).toBeInTheDocument(),
    );
    const fileInput = document.querySelector('input[type="file"][accept="image/*"]') as HTMLInputElement;
    const file = new File(['fake image'], 'physics-homework.jpg', { type: 'image/jpeg' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    fireEvent.click(await screen.findByRole('button', { name: '上传 1 张并识别' }));

    expect(await screen.findByText('出错了，可以复制给开发者')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '复制错误信息' }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(1));
    const copied = (navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(copied).toContain('context: chat:homework-upload');
    expect(copied).toContain('message: 上传失败');
    expect(copied).not.toContain('mock-token');
  });

  it('长历史默认只渲染最近消息，可手动展开更早消息', async () => {
    mockListSessions.mockResolvedValue([
      { id: 42, user_id: 1, student_id: 2, title: '长会话', created_at: '2026-07-02 12:00:00' },
    ]);
    mockGetMessages.mockResolvedValue(
      Array.from({ length: 90 }, (_, index) => ({
        id: index + 1,
        role: 'user',
        content: `历史消息 ${index}`,
        created_at: '2026-07-02 12:00:00',
      })),
    );

    render(<ChatPage />);

    await waitFor(() => expect(mockGetMessages).toHaveBeenCalledWith(42));
    await waitFor(() => {
      expect(screen.queryByText('历史消息 0')).not.toBeInTheDocument();
      expect(screen.getByText('历史消息 89')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /显示更早/ })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /显示更早/ }));

    await waitFor(() => {
      expect(screen.getByText('历史消息 0')).toBeInTheDocument();
    });
  });

  it('历史工具调用和最终回复合并为同一条 agent 消息', async () => {
    mockListSessions.mockResolvedValue([
      { id: 43, user_id: 1, student_id: 2, title: '工具会话', created_at: '2026-07-02 12:00:00' },
    ]);
    mockGetMessages.mockResolvedValue([
      {
        id: 1,
        role: 'user',
        content: '查诊断',
        created_at: '2026-07-02 12:00:00',
      },
      {
        id: 2,
        role: 'assistant',
        content: '查询中',
        tool_calls: [
          {
            id: 'c1',
            type: 'function',
            function: { name: 'query_diagnosis', arguments: '{"student_id":2,"top_n":5}' },
          },
        ],
        created_at: '2026-07-02 12:00:00',
      },
      {
        id: 3,
        role: 'tool',
        content: '{"summary":"暂无历史错题"}',
        tool_result: { tool_call_id: 'c1', name: 'query_diagnosis' },
        created_at: '2026-07-02 12:00:00',
      },
      {
        id: 4,
        role: 'assistant',
        content: '暂无错题',
        created_at: '2026-07-02 12:00:00',
      },
    ]);

    render(<ChatPage />);

    await waitFor(() => expect(mockGetMessages).toHaveBeenCalledWith(43));
    await waitFor(() => {
      expect(screen.getByText('查询学情')).toBeInTheDocument();
      expect(screen.getByText(/暂无历史错题/)).toBeInTheDocument();
      expect(screen.getByText('查询中暂无错题')).toBeInTheDocument();
    });
  });

  it('历史工具回复只合并紧邻的一轮，不吞掉后续普通助手消息', async () => {
    mockListSessions.mockResolvedValue([
      { id: 44, user_id: 1, student_id: 2, title: '多轮会话', created_at: '2026-07-02 12:00:00' },
    ]);
    mockGetMessages.mockResolvedValue([
      {
        id: 1,
        role: 'user',
        content: '查诊断',
        created_at: '2026-07-02 12:00:00',
      },
      {
        id: 2,
        role: 'assistant',
        content: '查询中',
        tool_calls: [
          {
            id: 'c1',
            type: 'function',
            function: { name: 'query_diagnosis', arguments: '{"student_id":2,"top_n":5}' },
          },
        ],
        created_at: '2026-07-02 12:00:00',
      },
      {
        id: 3,
        role: 'tool',
        content: '{"summary":"暂无历史错题"}',
        tool_result: { tool_call_id: 'c1', name: 'query_diagnosis' },
        created_at: '2026-07-02 12:00:00',
      },
      {
        id: 4,
        role: 'assistant',
        content: '暂无错题',
        created_at: '2026-07-02 12:00:00',
      },
      {
        id: 5,
        role: 'user',
        content: '我想制定一个计划',
        created_at: '2026-07-02 12:01:00',
      },
      {
        id: 6,
        role: 'assistant',
        content: '可以，先说说你有多长时间。',
        created_at: '2026-07-02 12:01:01',
      },
    ]);

    render(<ChatPage />);

    await waitFor(() => expect(mockGetMessages).toHaveBeenCalledWith(44));
    await waitFor(() => {
      expect(screen.getByText('查询中暂无错题')).toBeInTheDocument();
      expect(screen.getByText('我想制定一个计划')).toBeInTheDocument();
      expect(screen.getByText('可以，先说说你有多长时间。')).toBeInTheDocument();
    });
  });

  it('对话页渲染相机上传按钮（两角色都可见，点开选错题/素材）', async () => {
    render(<ChatPage />);
    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());
    // 相机按钮（title 标识），学生和家长都能上传
    await waitFor(() => {
      expect(screen.getByTitle('上传：错题或素材')).toBeInTheDocument();
    });
  });

  it('聊天 Markdown 展示组件从独立消息模块导出', () => {
    render(<MarkdownContent content="**重点**：先确认学习时间" />);

    expect(screen.getByText('重点')).toBeInTheDocument();
    expect(screen.getByText(/先确认学习时间/)).toBeInTheDocument();
  });

  it('今天页有待完成家庭任务时显示一行轻提示，点击跳家庭任务页', async () => {
    mockRole = 'student';
    mockTodayTasks.mockResolvedValue([familyTask({ status: 'pending' })]);
    render(<ChatPage />);

    const hint = await screen.findByRole('button', { name: '今天还有 1 件家庭任务待完成' });
    fireEvent.click(hint);

    expect(mockTodayTasks).toHaveBeenCalledWith(1);
    expect(window.location.hash).toBe('#/family-tasks');
  });

  it('没有待完成家庭任务时不渲染提示行', async () => {
    mockRole = 'student';
    mockTodayTasks.mockResolvedValue([
      familyTask({ status: 'approved' }),
      familyTask({ status: 'submitted', occurrence_id: 12 }),
    ]);
    render(<ChatPage />);

    await waitFor(() => expect(mockTodayTasks).toHaveBeenCalled());
    expect(screen.queryByText(/件家庭任务待完成/)).not.toBeInTheDocument();
  });
});
