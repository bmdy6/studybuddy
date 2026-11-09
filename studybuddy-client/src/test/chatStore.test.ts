/**
 * chatStore 单元测试。
 *
 * mock 依赖：chatApi（sendMessage 流式 / createSession / listSessions / getMessages）、noteApi.get
 * 测：runSend 流式追加 + loading 复位、tool_result 落草案/批改、切会话中断旧流、
 *     init 同身份跳过、init 学生变化 reset、reset 全清
 *
 * 关键：store 是真单例，beforeEach 必须 reset，否则跨用例污染。
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useChatStore, type ChatInitCtx } from '@/features/chat/store';
import { saveNavState, loadNavState, clearNavState } from '@/features/chat/sessionNav';
import type { PlanDraftState } from '@/features/chat/components/PlanDraftPanel';

const {
  mockSendMessage,
  mockCreateSession,
  mockListSessions,
  mockGetMessages,
  mockRenameSession,
  mockDeleteSession,
  mockResetContext,
  mockNoteGet,
  mockGetPlanDraft,
  mockConfirmPlanDraft,
  mockContinueTaskItem,
  mockCarryOverStudyPlan,
} = vi.hoisted(() => ({
  mockSendMessage: vi.fn(),
  mockCreateSession: vi.fn().mockResolvedValue({ id: 1 }),
  mockListSessions: vi.fn().mockResolvedValue([]),
  mockGetMessages: vi.fn().mockResolvedValue([]),
  mockRenameSession: vi.fn().mockResolvedValue(undefined),
  mockDeleteSession: vi.fn().mockResolvedValue(undefined),
  mockResetContext: vi.fn().mockResolvedValue(undefined),
  mockNoteGet: vi.fn().mockResolvedValue({ status: 'confirmed' }),
  mockGetPlanDraft: vi.fn().mockResolvedValue({ status: 'pending', is_expired: false, chat_session_id: null }),
  mockConfirmPlanDraft: vi.fn().mockResolvedValue({ plan_id: 1 }),
  mockContinueTaskItem: vi.fn(),
  mockCarryOverStudyPlan: vi.fn().mockResolvedValue({ id: 20 }),
}));

vi.mock('@/features/chat/api', () => ({
  chatApi: {
    sendMessage: mockSendMessage,
    createSession: mockCreateSession,
    listSessions: mockListSessions,
    getMessages: mockGetMessages,
    renameSession: mockRenameSession,
    deleteSession: mockDeleteSession,
    resetContext: mockResetContext,
    continueTaskItem: mockContinueTaskItem,
  },
}));
vi.mock('@/features/note/api', () => ({
  noteApi: { get: mockNoteGet, update: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/features/p2/api', () => ({
  p2Api: {
    getPlanDraft: mockGetPlanDraft,
    confirmPlanDraft: mockConfirmPlanDraft,
    carryOverStudyPlan: mockCarryOverStudyPlan,
  },
}));

async function* streamFrom(events: Array<Record<string, unknown>>) {
  for (const event of events) {
    yield event;
  }
}

function ctx(over: Partial<ChatInitCtx> = {}): ChatInitCtx {
  return {
    token: 't',
    role: 'parent',
    userId: 1,
    requestedStudentId: 2,
    activeChildId: 2,
    ...over,
  };
}

describe('sessionNav', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('save/load 按学生隔离', () => {
    saveNavState(1, { sessionId: 100, activeTaskSessionId: 200, mainSessionId: 100 });
    saveNavState(2, { sessionId: 300, activeTaskSessionId: null, mainSessionId: 300 });
    expect(loadNavState(1)?.sessionId).toBe(100);
    expect(loadNavState(1)?.activeTaskSessionId).toBe(200);
    expect(loadNavState(2)?.sessionId).toBe(300);
    expect(loadNavState(2)?.activeTaskSessionId).toBeNull();
  });

  it('clear 只清指定学生', () => {
    saveNavState(1, { sessionId: 100, activeTaskSessionId: null, mainSessionId: 100 });
    saveNavState(2, { sessionId: 200, activeTaskSessionId: null, mainSessionId: 200 });
    clearNavState(1);
    expect(loadNavState(1)).toBeNull();
    expect(loadNavState(2)?.sessionId).toBe(200);
  });

  it('load 无数据返回 null', () => {
    expect(loadNavState(999)).toBeNull();
  });
});

describe('chatStore', () => {
  beforeEach(() => {
    localStorage.clear();
    useChatStore.getState().reset();
    mockSendMessage.mockReset();
    mockCreateSession.mockReset();
    mockListSessions.mockReset();
    mockGetMessages.mockReset();
    mockRenameSession.mockReset();
    mockDeleteSession.mockReset();
    mockResetContext.mockReset();
    mockNoteGet.mockReset();
    mockGetPlanDraft.mockReset();
    mockConfirmPlanDraft.mockReset();
    mockCarryOverStudyPlan.mockReset();
    mockCreateSession.mockResolvedValue({ id: 1 });
    mockListSessions.mockResolvedValue([]);
    mockGetMessages.mockResolvedValue([]);
    mockNoteGet.mockResolvedValue({ status: 'confirmed' });
    mockGetPlanDraft.mockResolvedValue({ status: 'pending', is_expired: false, chat_session_id: null });
    mockConfirmPlanDraft.mockResolvedValue({ plan_id: 1 });
    mockCarryOverStudyPlan.mockResolvedValue({ id: 20 });
  });

  it('resetContext：通知后端并清空当前会话消息', async () => {
    mockListSessions.mockResolvedValue([
      { id: 10, user_id: 1, student_id: 1, title: '学习对话', session_type: 'main' },
    ]);
    mockGetMessages.mockResolvedValue([
      { id: 1, role: 'user', content: '旧话题', created_at: '' },
      { id: 2, role: 'assistant', content: '旧回复', created_at: '' },
    ]);
    await useChatStore.getState().init(ctx({ role: 'student', userId: 1, requestedStudentId: null }));

    await useChatStore.getState().resetContext();

    expect(mockResetContext).toHaveBeenCalledWith(10);
    expect(useChatStore.getState().messages).toEqual([]);
  });

  it('runSend：查询历史计划后展示可沿用的非今日计划', async () => {
    mockCreateSession.mockResolvedValue({ id: 10 });
    await useChatStore.getState().init(ctx());

    mockSendMessage.mockImplementation(() =>
      streamFrom([
        { type: 'tool_call', id: 'tc-old', name: 'query_study_plans', input: {}, started_at: 1 },
        {
          type: 'tool_result',
          id: 'tc-old',
          name: 'query_study_plans',
          output: JSON.stringify({
            as_of_date: '2026-08-19',
            plans: [
              { id: 12, title: '旧计划', planned_date: '2026-08-17', status: 'archived', overdue_days: 2, items: [{ title: '补做', minutes: 20, status: 'todo' }] },
              { id: 13, title: '今日计划', planned_date: '2026-08-19', status: 'active', overdue_days: 0, items: [{ title: '今天学', minutes: 20, status: 'todo' }] },
            ],
          }),
        },
        { type: 'done' },
      ]),
    );

    await useChatStore.getState().runSend('我想继续之前的英语计划');

    expect(useChatStore.getState().pendingPlanCarryOver).toEqual({
      asOfDate: '2026-08-19',
      plans: [expect.objectContaining({ id: 12, title: '旧计划' })],
    });
  });

  it('carryOverStudyPlan：成功后清卡并刷新今天计划', async () => {
    mockCreateSession.mockResolvedValue({ id: 10 });
    await useChatStore.getState().init(ctx());
    useChatStore.setState({
      pendingPlanCarryOver: { asOfDate: '2026-08-19', plans: [{ id: 12, title: '旧计划', planned_date: '2026-08-17', status: 'archived', overdue_days: 2, items: [{ title: '补做', minutes: 20, status: 'todo' }] }] },
    });

    await useChatStore.getState().carryOverStudyPlan(12);

    expect(mockCarryOverStudyPlan).toHaveBeenCalledWith(12);
    expect(useChatStore.getState().pendingPlanCarryOver).toBeNull();
    expect(useChatStore.getState().planVersion).toBe(1);
  });
  it('runSend：追加 user 气泡 + 流式追加 agent 文本，结束后 loading 复位', async () => {
    mockCreateSession.mockResolvedValue({ id: 10 });
    await useChatStore.getState().init(ctx());

    mockSendMessage.mockImplementation(() =>
      streamFrom([{ type: 'text', content: '你好' }, { type: 'done' }]),
    );
    await useChatStore.getState().runSend('hi');

    const s = useChatStore.getState();
    expect(s.loading).toBe(false);
    expect(s.messages.find((m) => m.role === 'user')?.content).toBe('hi');
    expect(s.messages.find((m) => m.role === 'assistant')?.content).toBe('你好');
    // sendMessage 收到 sessionId 与 content
    expect(mockSendMessage.mock.calls[0][0]).toBe(10);
    expect(mockSendMessage.mock.calls[0][1]).toBe('hi');
  });

  it('runSend：tool_result(save_note) 落 pendingNoteDraft', async () => {
    mockCreateSession.mockResolvedValue({ id: 10 });
    await useChatStore.getState().init(ctx());

    mockSendMessage.mockImplementation(() =>
      streamFrom([
        { type: 'tool_call', id: 'tc1', name: 'save_note', input: {}, started_at: 1 },
        {
          type: 'tool_result',
          id: 'tc1',
          name: 'save_note',
          output: JSON.stringify({
            note_draft: true,
            id: 5,
            title: '二次函数',
            subject: '数学',
            status: 'draft',
          }),
        },
        { type: 'done' },
      ]),
    );
    await useChatStore.getState().runSend('存个笔记');

    expect(useChatStore.getState().pendingNoteDraft).toMatchObject({
      id: 5,
      title: '二次函数',
      status: 'draft',
    });
  });

  it('runSend：tool_result(recognize_homework_photo_markdown) 落 pendingAnswerReview', async () => {
    mockCreateSession.mockResolvedValue({ id: 10 });
    await useChatStore.getState().init(ctx());

    mockSendMessage.mockImplementation(() =>
      streamFrom([
        {
          type: 'tool_call',
          id: 'tc1',
          name: 'recognize_homework_photo_markdown',
          input: {},
          started_at: 1,
        },
        {
          type: 'tool_result',
          id: 'tc1',
          name: 'recognize_homework_photo_markdown',
          output: JSON.stringify({
            answer_review_state: {
              batch_id: 7,
              items: [{ question: '1+1=?', answer: '2' }],
            },
          }),
        },
        { type: 'done' },
      ]),
    );
    await useChatStore.getState().runSend('帮我批改');

    expect(useChatStore.getState().pendingAnswerReview).toMatchObject({
      batch_id: 7,
    });
    expect(useChatStore.getState().pendingAnswerReview?.items.length).toBe(1);
  });

  it('switchSession 中断旧流：切走后旧流不再往 messages 推', async () => {
    mockCreateSession.mockResolvedValue({ id: 10 });
    await useChatStore.getState().init(ctx());

    const gate: { release: (() => void) | null } = { release: null };
    async function* slowStream() {
      yield { type: 'text', content: '前半' };
      await new Promise<void>((r) => {
        gate.release = r;
      });
      yield { type: 'text', content: '后半' }; // 切走后不应被追加
      yield { type: 'done' };
    }
    mockSendMessage.mockImplementation(() => slowStream());

    const sendP = useChatStore.getState().runSend('hi');
    // 等首块落地
    await new Promise((r) => setTimeout(r, 10));
    const msgs = useChatStore.getState().messages;
    expect(msgs[msgs.length - 1]?.content).toBe('前半');

    // 切到新会话 20
    mockGetMessages.mockResolvedValue([]);
    void useChatStore.getState().switchSession(20);
    // 放行旧流的第二块
    gate.release?.();
    await sendP;

    expect(useChatStore.getState().sessionId).toBe(20);
    // 旧流「后半」不应出现在新会话的 messages 里
    expect(useChatStore.getState().messages.some((m) => m.content.includes('后半'))).toBe(false);
  });

  it('init：同身份已有会话 -> 跳过重 init，保留进行中的流', async () => {
    mockListSessions.mockResolvedValue([{ id: 10, student_id: 2 }]);
    mockGetMessages.mockResolvedValue([]);
    await useChatStore.getState().init(ctx());
    expect(useChatStore.getState().sessionId).toBe(10);

    const callsBefore = mockListSessions.mock.calls.length;
    // 再次 init，身份（token/学生）未变 -> 不重选会话
    await useChatStore.getState().init(ctx());
    expect(useChatStore.getState().sessionId).toBe(10);
    expect(mockListSessions.mock.calls.length).toBe(callsBefore);
  });

  it('init：学生优先选 session_type=main 的主会话，不选 task', async () => {
    // task 在前（updated_at 最新），main 在后；学生应选 main 不选 task
    mockListSessions.mockResolvedValue([
      { id: 200, user_id: 1, student_id: 1, title: '学习任务', created_at: '', session_type: 'task', plan_id: 10, plan_item_id: 5, status: 'active' },
      { id: 100, user_id: 1, student_id: 1, title: '学习对话', created_at: '', session_type: 'main', plan_id: null, plan_item_id: null, status: 'active' },
    ]);
    await useChatStore.getState().init(ctx({ role: 'student', userId: 1, requestedStudentId: null, activeChildId: null }));
    expect(useChatStore.getState().sessionId).toBe(100);
  });

  it('init：同身份并发初始化只创建一个会话', async () => {
    let release!: (value: unknown[]) => void;
    const pending = new Promise<unknown[]>((resolve) => { release = resolve; });
    mockListSessions.mockReturnValue(pending);
    const first = useChatStore.getState().init(ctx());
    const second = useChatStore.getState().init(ctx());
    release([]);
    await Promise.all([first, second]);
    expect(mockCreateSession).toHaveBeenCalledTimes(1);
    expect(useChatStore.getState().sessionId).toBe(1);
  });

  it('init：身份变化后旧列表返回不能覆盖新学生会话', async () => {
    let release!: (value: unknown[]) => void;
    mockListSessions.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
    const first = useChatStore.getState().init(ctx({ requestedStudentId: 2 }));
    mockListSessions.mockResolvedValue([{ id: 20, student_id: 3 }]);
    await useChatStore.getState().init(ctx({ requestedStudentId: 3 }));
    release([{ id: 10, student_id: 2 }]);
    await first;
    expect(useChatStore.getState().sessionId).toBe(20);
    expect(useChatStore.getState().sessions.map((session) => session.id)).toEqual([20]);
  });

  it('init：身份变化后旧建会话返回不能接管新身份', async () => {
    let release!: (value: { id: number }) => void;
    mockCreateSession.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
    const first = useChatStore.getState().init(ctx({ requestedStudentId: 2 }));
    await vi.waitFor(() => expect(mockCreateSession).toHaveBeenCalledTimes(1));
    mockListSessions.mockResolvedValue([{ id: 20, student_id: 3 }]);
    await useChatStore.getState().init(ctx({ requestedStudentId: 3 }));
    release({ id: 10 });
    await first;
    expect(useChatStore.getState().sessionId).toBe(20);
  });

  it('init：重置后旧历史返回不能恢复旧消息', async () => {
    let release!: (value: unknown[]) => void;
    mockListSessions.mockResolvedValue([{ id: 10, student_id: 2 }]);
    mockGetMessages.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
    const pending = useChatStore.getState().init(ctx());
    await vi.waitFor(() => expect(mockGetMessages).toHaveBeenCalledTimes(1));
    useChatStore.getState().reset();
    release([{ id: 1, role: 'assistant', content: '旧身份消息', created_at: '' }]);
    await pending;
    expect(useChatStore.getState().sessionId).toBeNull();
    expect(useChatStore.getState().messages).toEqual([]);
  });

  it('init：恢复持久化的 task session 位置（刷新回原处，不踢回主会话）', async () => {
    saveNavState(1, { sessionId: 200, activeTaskSessionId: 200, mainSessionId: 100 });
    mockListSessions.mockResolvedValue([
      { id: 200, user_id: 1, student_id: 1, title: '学习任务', created_at: '', session_type: 'task', plan_id: 10, plan_item_id: 5, status: 'active' },
      { id: 100, user_id: 1, student_id: 1, title: '学习对话', created_at: '', session_type: 'main', plan_id: null, plan_item_id: null, status: 'active' },
    ]);
    await useChatStore.getState().init(ctx({ role: 'student', userId: 1, requestedStudentId: null, activeChildId: null }));
    expect(useChatStore.getState().sessionId).toBe(200);
    expect(useChatStore.getState().activeTaskSessionId).toBe(200);
    expect(useChatStore.getState().mainSessionId).toBe(100);
  });

  it('switchSession 后写持久化', async () => {
    mockListSessions.mockResolvedValue([
      { id: 100, user_id: 1, student_id: 1, title: '学习对话', created_at: '', session_type: 'main', plan_id: null, plan_item_id: null, status: 'active' },
    ]);
    await useChatStore.getState().init(ctx({ role: 'student', userId: 1, requestedStudentId: null, activeChildId: null }));
    await useChatStore.getState().switchSession(100);
    expect(loadNavState(1)?.sessionId).toBe(100);
  });

  it('init：学生变化 -> reset 旧会话并重选', async () => {
    mockListSessions.mockResolvedValue([{ id: 10, student_id: 2 }]);
    mockGetMessages.mockResolvedValue([]);
    await useChatStore.getState().init(ctx({ requestedStudentId: 2 }));
    expect(useChatStore.getState().sessionId).toBe(10);

    // 换学生
    mockListSessions.mockResolvedValue([{ id: 20, student_id: 3 }]);
    await useChatStore.getState().init(ctx({ requestedStudentId: 3 }));
    expect(useChatStore.getState().sessionId).toBe(20);
  });

  it('reset：清空全部运行态与绑定身份', async () => {
    mockCreateSession.mockResolvedValue({ id: 10 });
    await useChatStore.getState().init(ctx());
    // 模拟运行中状态
    useChatStore.setState({
      loading: true,
      pendingNoteDraft: {
        id: 1,
        title: 'x',
        subject: '其他',
        category: '未分类',
        content: '',
        knowledge_tags: [],
        source: '其他',
        status: 'draft',
      },
    });
    expect(useChatStore.getState()._boundToken).toBe('t');

    useChatStore.getState().reset();

    const s = useChatStore.getState();
    expect(s.messages).toEqual([]);
    expect(s.loading).toBe(false);
    expect(s.sessionId).toBeNull();
    expect(s.sessions).toEqual([]);
    expect(s.pendingNoteDraft).toBeNull();
    expect(s._boundToken).toBeNull();
    expect(s._boundStudentId).toBeNull();
  });

  it('done 使用服务端最终正文：非空 done.content 替换流式追加的临时文本', async () => {
    mockCreateSession.mockResolvedValue({ id: 10 });
    await useChatStore.getState().init(ctx());

    mockSendMessage.mockImplementation(() =>
      streamFrom([
        { type: 'text', content: '今天是 2026-07-23，开始复习。' },
        { type: 'done', content: '今天是 2026-08-03，开始复习。' },
      ]),
    );
    await useChatStore.getState().runSend('今天帮我安排');

    const assistant = useChatStore.getState().messages.find((m) => m.role === 'assistant');
    expect(assistant?.content).toBe('今天是 2026-08-03，开始复习。');
  });

  it('done 使用服务端最终正文：done.content 为空时保留已有流式文本', async () => {
    mockCreateSession.mockResolvedValue({ id: 10 });
    await useChatStore.getState().init(ctx());

    mockSendMessage.mockImplementation(() =>
      streamFrom([{ type: 'text', content: '流式内容' }, { type: 'done', content: '' }]),
    );
    await useChatStore.getState().runSend('hi');

    const assistant = useChatStore.getState().messages.find((m) => m.role === 'assistant');
    expect(assistant?.content).toBe('流式内容');
  });

  it('done 使用服务端最终正文：空 done.content 不清空工具卡', async () => {
    mockCreateSession.mockResolvedValue({ id: 10 });
    await useChatStore.getState().init(ctx());

    mockSendMessage.mockImplementation(() =>
      streamFrom([
        { type: 'tool_call', id: 'tc1', name: 'query_diagnosis', input: {}, started_at: 1 },
        { type: 'tool_result', id: 'tc1', name: 'query_diagnosis', output: '{}', elapsed_ms: 5 },
        { type: 'done', content: '' },
      ]),
    );
    await useChatStore.getState().runSend('查诊断');

    const assistant = useChatStore.getState().messages.find((m) => m.role === 'assistant');
    expect(assistant?.tools?.length).toBe(1);
  });

  it('recordErrorReport / clearErrorReport：写与清 latestErrorReport', () => {
    useChatStore.getState().recordErrorReport({
      context: 'chat:test',
      message: 'boom',
    });
    expect(useChatStore.getState().latestErrorReport?.message).toBe('boom');
    expect(useChatStore.getState().latestErrorReport?.id).toBeTruthy();

    useChatStore.getState().clearErrorReport();
    expect(useChatStore.getState().latestErrorReport).toBeNull();
  });
});

// ===== M1：计划草案关联性（方案 2.3 B 当前卡/历史草案分层） =====

function planDraftState(over: Partial<PlanDraftState> = {}): PlanDraftState {
  return {
    draftId: 1,
    revision: 1,
    title: '今日语文',
    focus: null,
    planned_date: null,
    items: [{ title: '练一篇记叙文阅读', minutes: 20 }],
    expiresAt: null,
    chatSessionId: null,
    createdAt: null,
    ...over,
  };
}

function draftToolOutput(draftId: number, title: string, chatSessionId: number | null = null) {
  return JSON.stringify({
    drafted: true,
    draft_id: draftId,
    revision: 1,
    title,
    items: [{ title: '任务1', minutes: 20 }],
    chat_session_id: chatSessionId,
    created_at: '2026-08-04T10:00:00Z',
  });
}

/** 构造历史：user -> draft 工具调用/结果 -> assistant 收尾；可选在草案后追加一条 user 消息。 */
function draftHistory(
  draftId: number,
  title: string,
  opts: { userAfterDraft?: boolean; chatSessionId?: number | null } = {},
) {
  const msgs: Array<Record<string, unknown>> = [
    { id: 1, role: 'user', content: '帮我做个语文计划', created_at: '' },
    {
      id: 2,
      role: 'assistant',
      content: '',
      tool_calls: [
        {
          id: 'tc1',
          type: 'function',
          function: { name: 'draft_study_plan', arguments: JSON.stringify({ student_id: 2, title }) },
        },
      ],
      created_at: '',
    },
    {
      id: 3,
      role: 'tool',
      content: draftToolOutput(draftId, title, opts.chatSessionId ?? null),
      tool_result: { tool_call_id: 'tc1', name: 'draft_study_plan' },
      created_at: '',
    },
    { id: 4, role: 'assistant', content: '已生成草案卡，请确认。', created_at: '' },
  ];
  if (opts.userAfterDraft) {
    msgs.push({ id: 5, role: 'user', content: '不要这个，改学古诗词', created_at: '' });
    msgs.push({ id: 6, role: 'assistant', content: '好的。', created_at: '' });
  }
  return msgs;
}

function pendingDraftDetail(title: string, chatSessionId: number | null, isExpired = false) {
  return {
    id: 5,
    status: 'pending',
    created_plan_id: null,
    revision: 1,
    title,
    focus: null,
    planned_date: null,
    items: [],
    expires_at: isExpired ? '2026-08-04T09:30:00Z' : null,
    chat_session_id: chatSessionId,
    created_at: '2026-08-04T09:00:00Z',
    is_expired: isExpired,
  };
}

describe('计划草案关联性', () => {
  beforeEach(() => {
    localStorage.clear();
    useChatStore.getState().reset();
    mockSendMessage.mockReset();
    mockCreateSession.mockReset();
    mockListSessions.mockReset();
    mockGetMessages.mockReset();
    mockNoteGet.mockReset();
    mockGetPlanDraft.mockReset();
    mockConfirmPlanDraft.mockReset();
    mockCreateSession.mockResolvedValue({ id: 1 });
    mockListSessions.mockResolvedValue([]);
    mockGetMessages.mockResolvedValue([]);
    mockNoteGet.mockResolvedValue({ status: 'confirmed' });
    mockGetPlanDraft.mockResolvedValue({ status: 'pending', is_expired: false, chat_session_id: null });
    mockConfirmPlanDraft.mockResolvedValue({ plan_id: 1 });
  });

  it('发送即清：发新消息立即清掉当前确认卡并转为历史提示', async () => {
    mockCreateSession.mockResolvedValue({ id: 10 });
    await useChatStore.getState().init(ctx());
    useChatStore.setState({ pendingPlanDraft: planDraftState({ draftId: 1, title: '道德与法治' }) });

    mockSendMessage.mockImplementation(() =>
      streamFrom([
        { type: 'text', content: '想先确认：你想练现代文还是文言文？' },
        { type: 'done' },
      ]),
    );
    await useChatStore.getState().runSend('我语文要学习阅读理解');

    const s = useChatStore.getState();
    expect(s.pendingPlanDraft).toBeNull();
    expect(s.historicalPlanDraftNotice?.title).toBe('道德与法治');
  });

  it('追问期间不复活：只文字追问不生成新卡，旧卡不重新出现', async () => {
    mockCreateSession.mockResolvedValue({ id: 10 });
    await useChatStore.getState().init(ctx());
    useChatStore.setState({ pendingPlanDraft: planDraftState({ draftId: 1, title: '道德与法治' }) });

    mockSendMessage.mockImplementation(() =>
      streamFrom([
        { type: 'text', content: '想先确认：现代文还是文言文？' },
        { type: 'done' },
      ]),
    );
    await useChatStore.getState().runSend('我语文要学习阅读理解');
    expect(useChatStore.getState().pendingPlanDraft).toBeNull();

    mockSendMessage.mockImplementation(() =>
      streamFrom([{ type: 'text', content: '现代文阅读理解，练记叙文，对吗？' }, { type: 'done' }]),
    );
    await useChatStore.getState().runSend('对');
    expect(useChatStore.getState().pendingPlanDraft).toBeNull();
  });

  it('新工具结果替换：成功新 draft 设为当前卡并清掉历史提示', async () => {
    mockCreateSession.mockResolvedValue({ id: 10 });
    await useChatStore.getState().init(ctx());
    useChatStore.setState({
      pendingPlanDraft: planDraftState({ draftId: 1, title: '道德与法治' }),
      historicalPlanDraftNotice: planDraftState({ draftId: 1, title: '道德与法治' }),
    });

    mockSendMessage.mockImplementation(() =>
      streamFrom([
        { type: 'tool_call', id: 'tc2', name: 'draft_study_plan', input: {}, started_at: 1 },
        {
          type: 'tool_result',
          id: 'tc2',
          name: 'draft_study_plan',
          output: draftToolOutput(9, '语文阅读理解训练'),
          elapsed_ms: 5,
        },
        { type: 'done' },
      ]),
    );
    await useChatStore.getState().runSend('记叙文，20分钟，练典型题型');

    const s = useChatStore.getState();
    expect(s.pendingPlanDraft?.draftId).toBe(9);
    expect(s.pendingPlanDraft?.title).toBe('语文阅读理解训练');
    expect(s.historicalPlanDraftNotice).toBeNull();
  });

  it('刷新恢复当前：同会话 + draft 晚于最新 user + pending + 未过期才恢复当前卡', async () => {
    mockListSessions.mockResolvedValue([{ id: 10, student_id: 2 }]);
    mockGetMessages.mockResolvedValue(draftHistory(5, '今日语文·现代文阅读', { chatSessionId: 10 }));
    mockGetPlanDraft.mockResolvedValue(pendingDraftDetail('今日语文·现代文阅读', 10));

    await useChatStore.getState().init(ctx());

    const s = useChatStore.getState();
    expect(s.pendingPlanDraft?.draftId).toBe(5);
    expect(s.historicalPlanDraftNotice).toBeNull();
  });

  it('后续 user 使其降级：draft 被后续 user 消息越过时只降级为历史提示', async () => {
    mockListSessions.mockResolvedValue([{ id: 10, student_id: 2 }]);
    mockGetMessages.mockResolvedValue(
      draftHistory(5, '道德与法治', { userAfterDraft: true, chatSessionId: 10 }),
    );
    mockGetPlanDraft.mockResolvedValue(pendingDraftDetail('道德与法治', 10));

    await useChatStore.getState().init(ctx());

    const s = useChatStore.getState();
    expect(s.pendingPlanDraft).toBeNull();
    expect(s.historicalPlanDraftNotice?.title).toBe('道德与法治');
  });

  it('legacy null 归属：chat_session_id=null 的 pending 草案只降级为历史提示', async () => {
    mockListSessions.mockResolvedValue([{ id: 10, student_id: 2 }]);
    mockGetMessages.mockResolvedValue(draftHistory(5, '道德与法治', { chatSessionId: null }));
    mockGetPlanDraft.mockResolvedValue(pendingDraftDetail('道德与法治', null));

    await useChatStore.getState().init(ctx());

    const s = useChatStore.getState();
    expect(s.pendingPlanDraft).toBeNull();
    expect(s.historicalPlanDraftNotice?.title).toBe('道德与法治');
  });

  it('跨会话不带卡：切到无草案历史的会话不泄漏当前卡与历史提示', async () => {
    mockListSessions.mockResolvedValue([{ id: 10, student_id: 2 }]);
    mockGetMessages.mockResolvedValue(draftHistory(5, '今日语文·现代文阅读', { chatSessionId: 10 }));
    mockGetPlanDraft.mockResolvedValue(pendingDraftDetail('今日语文·现代文阅读', 10));
    await useChatStore.getState().init(ctx());
    expect(useChatStore.getState().pendingPlanDraft?.draftId).toBe(5);

    mockGetMessages.mockResolvedValue([
      { id: 1, role: 'user', content: 'hi', created_at: '' },
      { id: 2, role: 'assistant', content: '你好', created_at: '' },
    ]);
    await useChatStore.getState().switchSession(20);

    const s = useChatStore.getState();
    expect(s.sessionId).toBe(20);
    expect(s.pendingPlanDraft).toBeNull();
    expect(s.historicalPlanDraftNotice).toBeNull();
  });

  it('过期不恢复：is_expired=true 时不恢复当前卡也不显示历史提示', async () => {
    mockListSessions.mockResolvedValue([{ id: 10, student_id: 2 }]);
    mockGetMessages.mockResolvedValue(draftHistory(5, '今日语文·现代文阅读', { chatSessionId: 10 }));
    mockGetPlanDraft.mockResolvedValue(pendingDraftDetail('今日语文·现代文阅读', 10, true));

    await useChatStore.getState().init(ctx());

    const s = useChatStore.getState();
    expect(s.pendingPlanDraft).toBeNull();
    expect(s.historicalPlanDraftNotice).toBeNull();
  });

  it('testnew 同型状态机：旧卡标题发消息后 0 次、历史提示 1、补齐信息后新卡匹配新意图 1', async () => {
    mockCreateSession.mockResolvedValue({ id: 10 });
    await useChatStore.getState().init(ctx());
    useChatStore.setState({ pendingPlanDraft: planDraftState({ draftId: 1, title: '道德与法治' }) });

    // 发"我语文要学习阅读理解"：旧卡立即清空，转为历史提示
    mockSendMessage.mockImplementation(() =>
      streamFrom([{ type: 'text', content: '想先确认：现代文还是文言文？' }, { type: 'done' }]),
    );
    await useChatStore.getState().runSend('我语文要学习阅读理解');
    // 旧卡标题不再作为当前卡出现（0 次）；历史提示出现（1）
    expect(useChatStore.getState().pendingPlanDraft).toBeNull();
    expect(useChatStore.getState().historicalPlanDraftNotice?.title).toBe('道德与法治');

    // 补齐信息（记叙文 + 20 分钟 + 典型题型）：新卡标题匹配新意图
    mockSendMessage.mockImplementation(() =>
      streamFrom([
        { type: 'tool_call', id: 'tc3', name: 'draft_study_plan', input: {}, started_at: 1 },
        {
          type: 'tool_result',
          id: 'tc3',
          name: 'draft_study_plan',
          output: draftToolOutput(7, '今日语文·阅读理解训练'),
          elapsed_ms: 5,
        },
        { type: 'done' },
      ]),
    );
    await useChatStore.getState().runSend('记叙文，20分钟，练典型题型');

    const s = useChatStore.getState();
    expect(s.pendingPlanDraft?.title ?? null).not.toBe('道德与法治');
    expect(s.historicalPlanDraftNotice).toBeNull();
    expect(s.pendingPlanDraft?.title).toBe('今日语文·阅读理解训练');
  });
});

// ===== task session 历史恢复（continueTaskItem 补拉历史；与 switchSession 双入口统一） =====

function taskSessionEvent(id: number) {
  return {
    type: 'session',
    session: {
      id,
      user_id: 1,
      student_id: 2,
      title: '学习任务',
      created_at: '',
      session_type: 'task',
      plan_id: 1,
      plan_item_id: 5,
      status: 'active',
    },
  };
}

describe('task session 历史恢复', () => {
  beforeEach(() => {
    localStorage.clear();
    useChatStore.getState().reset();
    mockSendMessage.mockReset();
    mockCreateSession.mockReset();
    mockListSessions.mockReset();
    mockGetMessages.mockReset();
    mockContinueTaskItem.mockReset();
    mockRenameSession.mockReset();
    mockDeleteSession.mockReset();
    mockResetContext.mockReset();
    mockNoteGet.mockReset();
    mockGetPlanDraft.mockReset();
    mockConfirmPlanDraft.mockReset();
    mockCreateSession.mockResolvedValue({ id: 1 });
    mockListSessions.mockResolvedValue([]);
    mockGetMessages.mockResolvedValue([]);
    mockNoteGet.mockResolvedValue({ status: 'confirmed' });
    mockGetPlanDraft.mockResolvedValue({ status: 'pending', is_expired: false, chat_session_id: null });
    mockConfirmPlanDraft.mockResolvedValue({ plan_id: 1 });
  });

  it('进入已有历史的 task session：历史渲染在首条，本轮新回复在后，不重复', async () => {
    mockContinueTaskItem.mockImplementation(() =>
      streamFrom([
        taskSessionEvent(50),
        { type: 'text', content: '继续学习英语' },
        { type: 'done', content: '继续学习英语' },
      ]),
    );
    mockGetMessages.mockResolvedValue([
      { id: 1, role: 'user', content: '之前的问题', created_at: '' },
      { id: 2, role: 'assistant', content: '之前的回答', created_at: '' },
    ]);

    await useChatStore.getState().continueTaskItem(2, 5);

    const s = useChatStore.getState();
    // 补拉了该 task session 的历史
    expect(mockGetMessages).toHaveBeenCalledWith(50);
    expect(s.activeTaskSessionId).toBe(50);
    // 历史渲染在首条且不重复
    expect(s.messages[0]).toMatchObject({ id: 'h-1', role: 'user', content: '之前的问题' });
    expect(s.messages[1]).toMatchObject({ id: 'h-2', role: 'assistant', content: '之前的回答' });
    expect(s.messages.filter((m) => m.id === 'h-1').length).toBe(1);
    // 本轮新回复追加在历史之后
    expect(s.messages[s.messages.length - 1]).toMatchObject({
      role: 'assistant',
      content: '继续学习英语',
    });
    expect(s.loading).toBe(false);
  });

  it('进入后发新消息：追加在历史之后，不覆盖不重复', async () => {
    mockContinueTaskItem.mockImplementation(() =>
      streamFrom([
        taskSessionEvent(50),
        { type: 'text', content: '继续学习英语' },
        { type: 'done', content: '继续学习英语' },
      ]),
    );
    mockGetMessages.mockResolvedValue([
      { id: 1, role: 'user', content: '之前的问题', created_at: '' },
      { id: 2, role: 'assistant', content: '之前的回答', created_at: '' },
    ]);
    await useChatStore.getState().continueTaskItem(2, 5);

    mockSendMessage.mockImplementation(() =>
      streamFrom([{ type: 'text', content: '新问题的回复' }, { type: 'done' }]),
    );
    await useChatStore.getState().runSend('新问题');

    const s = useChatStore.getState();
    // 历史仍在首条
    expect(s.messages[0]).toMatchObject({ id: 'h-1', role: 'user', content: '之前的问题' });
    // 新消息追加在历史之后（本轮 user 在前、本轮 assistant 在后）
    expect(s.messages[s.messages.length - 2]).toMatchObject({ role: 'user', content: '新问题' });
    expect(s.messages[s.messages.length - 1]).toMatchObject({
      role: 'assistant',
      content: '新问题的回复',
    });
    expect(s.messages.filter((m) => m.id === 'h-1').length).toBe(1);
  });

  it('首次进入无历史：仍只显示单条任务提示，不受影响', async () => {
    mockContinueTaskItem.mockImplementation(() =>
      streamFrom([
        taskSessionEvent(60),
        { type: 'text', content: '开始学习吧' },
        { type: 'done', content: '开始学习吧' },
      ]),
    );
    mockGetMessages.mockResolvedValue([]);

    await useChatStore.getState().continueTaskItem(2, 6);

    const s = useChatStore.getState();
    expect(mockGetMessages).toHaveBeenCalledWith(60);
    expect(s.messages.length).toBe(1);
    expect(s.messages[0]).toMatchObject({ role: 'assistant', content: '开始学习吧' });
  });

  it('拉历史失败不影响本轮（容错），loading 正常复位', async () => {
    mockContinueTaskItem.mockImplementation(() =>
      streamFrom([
        taskSessionEvent(70),
        { type: 'text', content: '回复' },
        { type: 'done', content: '回复' },
      ]),
    );
    mockGetMessages.mockRejectedValue(new Error('network'));

    await useChatStore.getState().continueTaskItem(2, 7);

    const s = useChatStore.getState();
    expect(s.messages.length).toBe(1);
    expect(s.messages[0]).toMatchObject({ role: 'assistant', content: '回复' });
    expect(s.loading).toBe(false);
  });

  it('双入口统一：switchSession 与 continueTaskItem 都通过 getMessages 拉历史', async () => {
    // switchSession 路径：切会话拉历史
    mockGetMessages.mockResolvedValue([
      { id: 1, role: 'user', content: '主会话历史', created_at: '' },
    ]);
    await useChatStore.getState().switchSession(10);
    expect(mockGetMessages).toHaveBeenCalledWith(10);
    expect(useChatStore.getState().messages[0]).toMatchObject({ content: '主会话历史' });
    mockGetMessages.mockClear();

    // continueTaskItem 路径：同一加载函数（行为断言：同样调 getMessages 拉 task session 历史）
    mockContinueTaskItem.mockImplementation(() =>
      streamFrom([taskSessionEvent(20), { type: 'done', content: '' }]),
    );
    await useChatStore.getState().continueTaskItem(2, 8);
    expect(mockGetMessages).toHaveBeenCalledWith(20);
    expect(useChatStore.getState().messages[0]).toMatchObject({ content: '主会话历史' });
  });
});
