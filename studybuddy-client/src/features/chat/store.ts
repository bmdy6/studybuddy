import { create } from 'zustand';
import { chatApi } from '@/features/chat/api';
import { noteApi } from '@/features/note/api';
import { p2Api } from '@/features/p2/api';
import { getRequestErrorMessage } from '@/shared/api/client';
import { saveNavState, loadNavState, clearNavState } from '@/features/chat/sessionNav';
import type { Role } from '@/shared/constants';
import type {
  ChatMessage,
  ChatSession,
  NoteDraftState,
  PhotoAnswerReviewState,
} from '@/types';
import type { PlanDraftState } from '@/features/chat/components/PlanDraftPanel';
import type { PlanCarryOverState } from '@/features/chat/components/PlanCarryOverPanel';
import type { RenderMessage } from '@/features/chat/components/MessageBubble';

/**
 * Chat 运行态 store —— 单例，与组件生命周期解耦。
 *
 * 把 ChatPage 里“AI 流式输出 / 工具执行”相关的状态从组件 useState 搬到这里，
 * 流式 generator 在 store action 里跑。这样用户切到别的路由再切回来
 * （ChatPage 卸载/重挂载）时，进行中的消息、工具卡、loading、待确认草案都保留；
 * 后台 SSE 流继续更新 store，组件重挂载后订阅到最新状态。
 *
 * 不用 persist：运行态不该跨刷新缓存（刷新后流已断、需重新拉历史）。
 * 切页不丢靠的是内存单例，不是 localStorage。
 */

export interface ErrorReportInfo {
  id: string;
  context: string;
  message: string;
  details?: string;
  sessionId?: number | null;
  studentId?: number | null;
}

const TOOL_RUNNING_TIMEOUT_MS = 120_000;

function extractAnswerReviewStateFromToolOutput(output: string): PhotoAnswerReviewState | null {
  try {
    const data = JSON.parse(output) as { answer_review_state?: unknown };
    const state = data.answer_review_state as PhotoAnswerReviewState | undefined;
    if (!state || typeof state.batch_id !== 'number' || !Array.isArray(state.items)) {
      return null;
    }
    return state;
  } catch {
    return null;
  }
}

function extractNoteDraftStateFromToolOutput(output: string | undefined): NoteDraftState | null {
  if (!output) return null;
  try {
    const data = JSON.parse(output) as {
      note_draft?: boolean;
      id?: number;
      title?: string;
      subject?: string;
      category?: string;
      content?: string;
      knowledge_tags?: string[];
      source?: string;
      status?: string;
    };
    if (!data.note_draft || typeof data.id !== 'number') return null;
    return {
      id: data.id,
      title: data.title ?? '',
      subject: data.subject ?? '其他',
      category: data.category ?? '未分类',
      content: data.content ?? '',
      knowledge_tags: data.knowledge_tags ?? [],
      source: data.source ?? '其他',
      status: data.status ?? 'draft',
    };
  } catch {
    return null;
  }
}

/** 刷新/切会话后从历史 tool 结果恢复最后一个未确认草案，避免对话中途的草稿丢失。 */
function extractNoteDraftFromHistory(messages: RenderMessage[]): NoteDraftState | null {
  let draft: NoteDraftState | null = null;
  for (const m of messages) {
    for (const t of m.tools || []) {
      const d = extractNoteDraftStateFromToolOutput(t.output);
      if (d) draft = d; // 取最后一个 save_note 草案
    }
  }
  return draft;
}

function extractPlanDraftFromToolOutput(output: string | undefined): PlanDraftState | null {
  if (!output) return null;
  try {
    const data = JSON.parse(output) as {
      drafted?: boolean;
      draft_id?: number;
      revision?: number;
      title?: string;
      items?: PlanDraftState['items'];
      focus?: string | null;
      planned_date?: string | null;
      expires_at?: string | null;
      chat_session_id?: number | null;
      created_at?: string | null;
    };
    if (!data.drafted || typeof data.draft_id !== 'number') return null;
    return {
      draftId: data.draft_id,
      revision: data.revision ?? 1,
      title: data.title ?? '',
      items: data.items ?? [],
      focus: data.focus ?? null,
      planned_date: data.planned_date ?? null,
      expiresAt: data.expires_at ?? null,
      chatSessionId: data.chat_session_id ?? null,
      createdAt: data.created_at ?? null,
    };
  } catch {
    return null;
  }
}

/** 取会话历史里最后一个 draft 工具结果及其所在消息的位置（判断是否晚于最新 user 消息）。 */
function extractPlanDraftFromHistory(
  messages: RenderMessage[],
): { draft: PlanDraftState; index: number } | null {
  let found: { draft: PlanDraftState; index: number } | null = null;
  for (let i = 0; i < messages.length; i++) {
    for (const t of messages[i].tools || []) {
      const d = extractPlanDraftFromToolOutput(t.output);
      if (d) found = { draft: d, index: i };
    }
  }
  return found;
}

function extractPlanCarryOverFromToolOutput(output: string | undefined): PlanCarryOverState | null {
  if (!output) return null;
  try {
    const data = JSON.parse(output) as {
      as_of_date?: unknown;
      plans?: Array<{
        id?: unknown;
        title?: unknown;
        planned_date?: unknown;
        status?: unknown;
        overdue_days?: unknown;
        items?: Array<{ title?: unknown; minutes?: unknown; status?: unknown }>;
      }>;
    };
    if (typeof data.as_of_date !== 'string' || !Array.isArray(data.plans)) return null;
    const plans = data.plans
      .filter(
        (plan) =>
          typeof plan.id === 'number' &&
          typeof plan.title === 'string' &&
          plan.planned_date !== data.as_of_date &&
          Array.isArray(plan.items) &&
          plan.items.some((item) => item.status === 'todo' || item.status === 'in_progress'),
      )
      .map((plan) => ({
        id: plan.id as number,
        title: plan.title as string,
        planned_date: typeof plan.planned_date === 'string' ? plan.planned_date : null,
        status: typeof plan.status === 'string' ? plan.status : 'active',
        overdue_days: typeof plan.overdue_days === 'number' ? plan.overdue_days : 0,
        items: (plan.items ?? [])
          .filter((item) => item.status === 'todo' || item.status === 'in_progress')
          .map((item) => ({
            title: typeof item.title === 'string' ? item.title : '',
            minutes: typeof item.minutes === 'number' ? item.minutes : 0,
            status: typeof item.status === 'string' ? item.status : 'todo',
          })),
      }));
    return plans.length ? { asOfDate: data.as_of_date, plans } : null;
  } catch {
    return null;
  }
}

function extractPlanCarryOverFromHistory(messages: RenderMessage[]): PlanCarryOverState | null {
  let state: PlanCarryOverState | null = null;
  for (const message of messages) {
    for (const tool of message.tools || []) {
      if (tool.name === 'query_study_plans') {
        state = extractPlanCarryOverFromToolOutput(tool.output);
      }
    }
  }
  return state;
}

/** 最后一条 user 消息在 RenderMessage 里的下标；没有 user 消息返回 -1。 */
function findLastUserIndex(messages: RenderMessage[]): number {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'user') return i;
  }
  return -1;
}

/** 合并工具前说明；最终回复已包含前文时只保留一份。 */
function mergeToolNarrative(preamble: string | undefined, finalContent: string): string {
  const normalizedPreamble = preamble?.trim() ?? '';
  if (!normalizedPreamble) return finalContent;
  if (!finalContent.trim()) return normalizedPreamble;
  if (finalContent.includes(normalizedPreamble)) return finalContent;
  return `${normalizedPreamble}${finalContent}`;
}

/** 把后端历史 ChatMessage[] 转成前端 RenderMessage[]：
 * assistant tool_calls + role=tool + assistant 最终回复合并为一条带 ToolCard 的消息。 */
function historyToRender(msgs: ChatMessage[]): RenderMessage[] {
  const result: RenderMessage[] = [];
  let pendingToolAssistant: RenderMessage | null = null;
  for (const m of msgs) {
    if (m.role === 'user') {
      if (pendingToolAssistant) {
        pendingToolAssistant.content = mergeToolNarrative(
          pendingToolAssistant.preToolContent,
          pendingToolAssistant.content,
        );
        delete pendingToolAssistant.preToolContent;
      }
      pendingToolAssistant = null;
      result.push({ id: `h-${m.id}`, role: 'user', content: m.content || '' });
    } else if (m.role === 'assistant') {
      const tools: RenderMessage['tools'] = [];
      const calls =
        (m.tool_calls as Array<{
          id: string;
          function: { name: string; arguments: string };
        }> | null) ?? null;
      if (!calls?.length) {
        if (pendingToolAssistant) {
          pendingToolAssistant.content = mergeToolNarrative(
            pendingToolAssistant.preToolContent,
            m.content || '',
          );
          delete pendingToolAssistant.preToolContent;
          pendingToolAssistant = null;
          continue;
        }
        result.push({ id: `h-${m.id}`, role: 'assistant', content: m.content || '' });
        pendingToolAssistant = null;
        continue;
      } else {
        for (const c of calls) {
          const name = c.function?.name ?? 'tool';
          let inputRaw: unknown;
          try {
            inputRaw = JSON.parse(c.function?.arguments || '{}');
          } catch {
            inputRaw = {};
          }
          tools.push({ id: c.id, name, input: inputRaw, status: 'done' });
        }
      }
      const assistantMessage = {
        id: `h-${m.id}`,
        role: 'assistant' as const,
        content: '',
        tools,
        preToolContent: m.content || '',
      };
      result.push(assistantMessage);
      pendingToolAssistant = assistantMessage;
    } else if (m.role === 'tool') {
      // 把 tool 结果填到最近一个 assistant 的对应 ToolCard
      const tr = m.tool_result as { tool_call_id?: string } | null;
      const callId = tr?.tool_call_id;
      const lastAssistant = pendingToolAssistant ?? [...result].reverse().find((r) => r.role === 'assistant');
      if (lastAssistant) {
        const card = lastAssistant.tools?.find((t) => t.id === callId);
        if (card) card.output = m.content || '';
      }
    }
  }
  if (pendingToolAssistant) {
    pendingToolAssistant.content = mergeToolNarrative(
      pendingToolAssistant.preToolContent,
      pendingToolAssistant.content,
    );
    delete pendingToolAssistant.preToolContent;
  }
  return result;
}

export interface ChatInitCtx {
  token: string | null;
  role: Role | null;
  userId: number | null;
  /** URL ?student_id=，家长进指定学生对话时用 */
  requestedStudentId: number | null;
  /** 家长当前选中的孩子 */
  activeChildId: number | null;
}

interface ChatRuntimeState {
  // —— 运行态（卸载后后台流仍需更新，必须进 store）——
  messages: RenderMessage[];
  loading: boolean;
  sessionId: number | null;
  sessions: ChatSession[];
  /** U-042：当前进入的 task session（点「继续学习」创建/恢复）；返回主会话时清空 */
  activeTaskSessionId: number | null;
  activeTaskItemId: number | null;
  /** bug3：进入 task session 前的主会话 id，供"返回主会话"切回 */
  mainSessionId: number | null;
  pendingNoteDraft: NoteDraftState | null;
  pendingPlanDraft: PlanDraftState | null;
  pendingPlanCarryOver: PlanCarryOverState | null;
  planCarryOverConfirming: number | null;
  planCarryOverError: string | null;
  /** M1：同会话里被后续 user 消息越过、或 legacy 无法证明归属的 pending 草案提示（不可确认） */
  historicalPlanDraftNotice: PlanDraftState | null;
  planDraftConfirming: boolean;
  confirmPlanDraft: () => Promise<void>;
  carryOverStudyPlan: (planId: number) => Promise<void>;
  noteDraftConfirming: boolean;
  pendingAnswerReview: PhotoAnswerReviewState | null;
  answerReviewConfirming: boolean;
  latestErrorReport: ErrorReportInfo | null;
  /** AI 经对话新建学习计划后自增；TodayPlanPanel 订阅它刷新计划列表（手动抽屉在 onCreated 里已刷新） */
  planVersion: number;

  // —— 内部（不暴露 selector）——
  /** 替代组件 activeSessionRef：流循环里判断是否被切换/新建打断 */
  _activeSessionId: number | null;
  /** 当前流式的 AbortController，切会话/重发时 abort 旧流 */
  _activeAbort: AbortController | null;
  /** init 判断身份是否变化、是否要重选会话 */
  _boundToken: string | null;
  _boundRole: Role | null;
  _boundUserId: number | null;
  _boundStudentId: number | null;

  // —— actions ——
  init: (ctx: ChatInitCtx) => Promise<void>;
  runSend: (content: string, displayContent?: string, opts?: { skipUserMessage?: boolean }) => Promise<void>;
  /** U-042：继续某个计划项 -> 后端建/恢复 task session + 触发 agent，流式接收 */
  continueTaskItem: (studentId: number, itemId: number) => Promise<void>;
  /** bug3：从 task session 返回主会话（切回主会话并恢复历史，清 task 状态） */
  returnToMainSession: () => Promise<void>;
  switchSession: (sid: number) => Promise<void>;
  newSession: () => Promise<void>;
  /** 保留消息列表，只让后端从下一条消息开始新的主会话上下文。 */
  resetContext: () => Promise<void>;
  refreshSessions: () => Promise<void>;
  /** 只做 api 调用 + 刷新列表，失败抛错由组件弹 toast */
  renameSession: (sid: number, title: string) => Promise<void>;
  /** 删除 + 若删的是当前会话则切下一个；失败抛错由组件弹 toast */
  deleteSession: (sid: number) => Promise<void>;
  setPendingNoteDraft: (d: NoteDraftState | null) => void;
  setPendingAnswerReview: (r: PhotoAnswerReviewState | null) => void;
  clearPendingNoteDraft: () => void;
  clearPendingAnswerReview: () => void;
  clearHistoricalPlanDraftNotice: () => void;
  setNoteDraftConfirming: (b: boolean) => void;
  setAnswerReviewConfirming: (b: boolean) => void;
  recordErrorReport: (report: Omit<ErrorReportInfo, 'id'>) => void;
  clearErrorReport: () => void;
  /** 全字段归零（登出/切账号/测试 beforeEach 用） */
  reset: () => void;

  // —— 内部 ——
  _markRunningTools: (agentId: string, output: string) => void;
  _resolveStudentId: () => number | null;
}

/** 拉取会话历史并渲染为前端消息；失败返回 null（容错：调用方自行降级，不中断当前操作）。
 * 所有入口（switchSession / continueTaskItem / 连接失败恢复）共用，保证历史加载行为一致。 */
async function loadSessionHistory(sessionId: number): Promise<RenderMessage[] | null> {
  try {
    const history = await chatApi.getMessages(sessionId);
    return historyToRender(history);
  } catch {
    return null;
  }
}

/** SSE 连接失败/中断后从后端历史拉取最后一条 AI 回复。
 * 后端总会完整保存 assistant 回复（即使 SSE 推送中途断开），前端连接失败时
 * 拉历史取回完整内容，避免用户因推送链路中断看不到 AI 已生成的回复。 */
async function fetchLastAssistantFromHistory(sessionId: number): Promise<RenderMessage | null> {
  const rendered = await loadSessionHistory(sessionId);
  if (!rendered) return null;
  const last = [...rendered]
    .reverse()
    .find((m) => m.role === 'assistant' && (m.content || (m.tools && m.tools.length)));
  return last ?? null;
}

/** 把当前导航态（sessionId/activeTaskSessionId/mainSessionId）按学生 id 持久化到 localStorage。
 * 解决刷新后 mainSessionId 丢失、找不到主会话的根因。只在 _boundStudentId 存在时写。 */
function persistNav(get: () => ChatRuntimeState): void {
  const sid = get()._boundStudentId;
  if (!sid) return;
  saveNavState(sid, {
    sessionId: get().sessionId,
    activeTaskSessionId: get().activeTaskSessionId,
    mainSessionId: get().mainSessionId,
  });
}

// One initialization per identity; an epoch rejects late results after switching
// accounts/students or resetting. The promise is shared across StrictMode effects.
let initGeneration = 0;
let initInFlight: { identity: string; promise: Promise<void> } | null = null;

export const useChatStore = create<ChatRuntimeState>((set, get) => ({
  messages: [],
  loading: false,
  sessionId: null,
  sessions: [],
  activeTaskSessionId: null,
  activeTaskItemId: null,
  mainSessionId: null,
  pendingNoteDraft: null,
  noteDraftConfirming: false,
  pendingPlanDraft: null,
  pendingPlanCarryOver: null,
  planCarryOverConfirming: null,
  planCarryOverError: null,
  historicalPlanDraftNotice: null,
  planDraftConfirming: false,
  pendingAnswerReview: null,
  answerReviewConfirming: false,
  latestErrorReport: null,
  planVersion: 0,
  _activeSessionId: null,
  _activeAbort: null,
  _boundToken: null,
  _boundRole: null,
  _boundUserId: null,
  _boundStudentId: null,

  init: (ctx) => {
    const studentId =
      ctx.role === 'student' ? ctx.userId : (ctx.requestedStudentId ?? ctx.activeChildId);
    const identity = JSON.stringify([ctx.token, ctx.role, ctx.userId, studentId]);
    if (initInFlight?.identity === identity) return initInFlight.promise;
    const tokenChanged = get()._boundToken !== ctx.token;
    const studentChanged = get()._boundStudentId !== studentId;
    const identityChanged = tokenChanged || studentChanged
      || get()._boundRole !== ctx.role || get()._boundUserId !== ctx.userId;
    if (identityChanged) {
      initGeneration += 1;
      initInFlight = null;
      // 中断旧流并清空全部运行态（身份变化，旧会话不能残留）
      get()._activeAbort?.abort();
      set({
        messages: [],
        loading: false,
        sessionId: null,
        sessions: [],
        activeTaskSessionId: null,
        activeTaskItemId: null,
        mainSessionId: null,
        pendingNoteDraft: null,
        noteDraftConfirming: false,
        pendingPlanDraft: null,
        pendingPlanCarryOver: null,
        planCarryOverConfirming: null,
        planCarryOverError: null,
        historicalPlanDraftNotice: null,
        planDraftConfirming: false,
        pendingAnswerReview: null,
        answerReviewConfirming: false,
        latestErrorReport: null,
        _activeSessionId: null,
        _activeAbort: null,
      });
    }
    set({
      _boundToken: ctx.token,
      _boundRole: ctx.role,
      _boundUserId: ctx.userId,
      _boundStudentId: studentId,
    });
    // 身份未变且已有会话 -> 不重 init，保留进行中的流（切页回来恢复 running 态）
    if (get().sessionId || !ctx.token) return Promise.resolve();
    const generation = initGeneration;
    const entry = { identity, promise: Promise.resolve() };
    entry.promise = (async () => {
      await get().refreshSessions();
      if (generation !== initGeneration) return;
      try {
        const list = get().sessions;
        // 1. 优先恢复持久化位置（刷新回到原处，不踢回主会话）
        const navStudentId = ctx.role === 'student' ? ctx.userId : (ctx.requestedStudentId ?? ctx.activeChildId);
        const saved = navStudentId ? loadNavState(navStudentId) : null;
        const savedExists = saved?.sessionId != null && list.some((s) => s.id === saved.sessionId);
        if (savedExists) {
          set({
            sessionId: saved!.sessionId,
            _activeSessionId: saved!.sessionId,
            activeTaskSessionId: saved!.activeTaskSessionId,
            mainSessionId: saved!.mainSessionId,
          });
          await get().switchSession(saved!.sessionId!);
          return;
        }
        // 2. 记不住 -> 学生优先选 session_type=main 的主会话（不选 task，避免落到 task 出不来）
        const preferredSession =
          ctx.role === 'student'
            ? list.find((s) => s.student_id === ctx.userId && s.session_type === 'main')
              ?? list.find((s) => s.student_id === ctx.userId)
            : ctx.requestedStudentId
              ? list.find((s) => s.student_id === ctx.requestedStudentId)
              : list[0];
        if (preferredSession) {
          await get().switchSession(preferredSession.id);
        } else {
          await get().newSession();
        }
      } catch {
        // 忽略初始化错误
      }
    })().finally(() => {
      if (initInFlight === entry) initInFlight = null;
    });
    initInFlight = entry;
    return entry.promise;
  },

  runSend: async (content, displayContent, opts) => {
    const sessionId = get().sessionId;
    if (!sessionId || get().loading) return;
    // M1：发任意新消息立即把当前确认卡移到历史提示并清空当前卡；
    // 只有本轮成功生成新 draft 才恢复当前卡（工具失败/只追问不复活）。
    const currentPlanDraft = get().pendingPlanDraft;
    if (!opts?.skipUserMessage && currentPlanDraft) {
      set({ pendingPlanDraft: null, historicalPlanDraftNotice: currentPlanDraft });
    }
    const currentPlanCarryOver = get().pendingPlanCarryOver;
    if (!opts?.skipUserMessage && currentPlanCarryOver) {
      set({ pendingPlanCarryOver: null, planCarryOverError: null });
    }
    // 中断上一条仍在进行的流（防御）
    get()._activeAbort?.abort();
    const ac = new AbortController();
    const agentId = `a-${Date.now()}`;
    const newMessages = [...get().messages];
    if (!opts?.skipUserMessage) {
      newMessages.push({ id: `u-${Date.now()}`, role: 'user', content: displayContent ?? content });
    }
    newMessages.push({ id: agentId, role: 'assistant', content: '', tools: [] });
    set({
      _activeAbort: ac,
      _activeSessionId: sessionId,
      loading: true,
      messages: newMessages,
    });

    const sendSessionId = sessionId;
    const toolTimeout = window.setTimeout(() => {
      if (get()._activeSessionId !== sendSessionId) return;
      get()._markRunningTools(agentId, '工具执行超过 120 秒，已停止等待。可以重试这一步。');
      // 超时兜底：复位 loading，避免按钮永久灰色
      set({ loading: false });
    }, TOOL_RUNNING_TIMEOUT_MS);
    try {
      const stream = chatApi.sendMessage(sendSessionId, content, displayContent, ac.signal);
      for await (const evt of stream) {
        // 会话已切换/新建 -> 丢弃旧流，不再往 messages 推
        if (get()._activeSessionId !== sendSessionId) break;
        switch (evt.type) {
          case 'text':
            set((state) => ({
              messages: state.messages.map((m) =>
                m.id === agentId ? { ...m, content: m.content + evt.content } : m,
              ),
            }));
            break;
          case 'reasoning':
            set((state) => ({
              messages: state.messages.map((m) =>
                m.id === agentId ? { ...m, reasoning: (m.reasoning || '') + evt.content } : m,
              ),
            }));
            break;
          case 'tool_call':
            set((state) => ({
              messages: state.messages.map((m) =>
                m.id === agentId
                  ? {
                      ...m,
                      preToolContent: m.preToolContent ?? m.content,
                      content: '',
                      tools: [
                        ...(m.tools || []),
                        {
                          id: evt.id,
                          name: evt.name,
                          input: evt.input,
                          status: 'running',
                          startedAt: evt.started_at ?? Date.now(),
                        },
                      ],
                    }
                  : m,
              ),
            }));
            break;
          case 'tool_progress':
            set((state) => ({
              messages: state.messages.map((m) =>
                m.id === agentId
                  ? {
                      ...m,
                      tools: (m.tools || []).map((t) =>
                        t.id === evt.id
                          ? {
                              ...t,
                              elapsedMs: evt.elapsed_ms,
                              progress: evt.message || t.progress,
                            }
                          : t,
                      ),
                    }
                  : m,
              ),
            }));
            break;
          case 'tool_result':
            if (evt.name === 'recognize_homework_photo_markdown') {
              const reviewState = extractAnswerReviewStateFromToolOutput(evt.output);
              if (reviewState?.items.length) set({ pendingAnswerReview: reviewState });
            }
            if (evt.name === 'save_note') {
              const draft = extractNoteDraftStateFromToolOutput(evt.output);
              if (draft) set({ pendingNoteDraft: draft });
            }
            if (evt.name === 'query_study_plans') {
              set({ pendingPlanCarryOver: extractPlanCarryOverFromToolOutput(evt.output), planCarryOverError: null });
            }
            if (evt.name === 'draft_study_plan') {
              const planDraft = extractPlanDraftFromToolOutput(evt.output);
              if (planDraft) {
                // M1：成功新 draft 设为当前卡并清除对应历史提示
                set({ pendingPlanDraft: planDraft, historicalPlanDraftNotice: null });
              }
            }
            if (evt.name === 'create_study_plan') {
              // 仅在真正创建成功时刷新计划列表；被 guard 拦截的不刷新
              try {
                const parsed = JSON.parse(evt.output);
                if (parsed.saved === true || parsed.id) {
                  set((state) => ({ planVersion: state.planVersion + 1 }));
                }
              } catch {
                /* 非 JSON 输出忽略 */
              }
            }
            set((state) => ({
              messages: state.messages.map((m) =>
                m.id === agentId
                  ? {
                      ...m,
                      tools: (m.tools || []).map((t) =>
                        t.id === evt.id
                          ? {
                              ...t,
                              output: evt.output,
                              elapsedMs: evt.elapsed_ms ?? t.elapsedMs,
                              status: 'done' as const,
                            }
                          : t,
                      ),
                    }
                  : m,
              ),
            }));
            break;
          case 'error':
            get()._markRunningTools(agentId, `工具执行失败：${evt.message}`);
            get().recordErrorReport({
              context: 'chat:sse-error',
              message: evt.message,
              details: `stream event error: ${evt.message}`,
              sessionId: sendSessionId,
              studentId: get()._resolveStudentId(),
            });
            set((state) => ({
              messages: state.messages.map((m) =>
                m.id === agentId ? { ...m, content: m.content || `失败：${evt.message}` } : m,
              ),
            }));
            // error 事件表示流已结束，主动 return 触发 finally 复位 loading
            return;
          case 'done':
            get()._markRunningTools(agentId, '工具没有返回结果。可以重试这一步。');
            // M1：后端最终正文优先。done.content 非空时用它替换本轮 assistant 最终正文
            // （流式分片可能短暂显示旧日期，最终以服务端校正后正文收敛，与落库一致）；
            // 为空时不清空工具卡或已有文本。
            set((state) => ({
              messages: state.messages.map((m) => {
                if (m.id !== agentId) return m;
                const finalText =
                  typeof evt.content === 'string' && evt.content.length > 0
                    ? evt.content
                    : m.content;
                const next = {
                  ...m,
                  content:
                    m.preToolContent !== undefined
                      ? mergeToolNarrative(m.preToolContent, finalText)
                      : finalText,
                };
                if (m.preToolContent !== undefined) delete next.preToolContent;
                return next;
              }),
            }));
            // 主动 return 触发 finally 复位 loading，不依赖 HTTP 流 EOF
            return;
        }
      }
    } catch (err) {
      // AbortError = 切会话/重发主动中断，视为正常，不报错
      const isAbort = err instanceof DOMException && err.name === 'AbortError';
      // 仅当仍是发起时的会话才更新错误提示（避免切换后污染新会话）
      if (!isAbort && get()._activeSessionId === sendSessionId) {
        // 容错：SSE 连接失败时，先从后端历史恢复完整 AI 回复（后端总会完整保存），
        // 避免因推送链路中断让用户看不到 AI 已生成的回复；恢复失败才显示"连接失败"。
        const last = await fetchLastAssistantFromHistory(sendSessionId);
        const cur = get().messages.find((m) => m.id === agentId);
        const recovered =
          !!last &&
          ((last.content || '').length > (cur?.content || '').length ||
            (last.tools?.length || 0) > (cur?.tools?.length || 0));
        if (recovered && last) {
          set((state) => ({
            messages: state.messages.map((m) =>
              m.id === agentId ? { ...m, content: last.content || m.content, tools: last.tools || m.tools } : m,
            ),
          }));
        } else {
          const errorMessage = `连接失败：${getRequestErrorMessage(err)}`;
          get()._markRunningTools(agentId, errorMessage);
          get().recordErrorReport({
            context: 'chat:sse-connection',
            message: errorMessage,
            details: getRequestErrorMessage(err),
            sessionId: sendSessionId,
            studentId: get()._resolveStudentId(),
          });
          set((state) => ({
            messages: state.messages.map((m) =>
              m.id === agentId ? { ...m, content: errorMessage } : m,
            ),
          }));
        }
      }
    } finally {
      // 仅当仍是发起时的会话才清 loading
      if (get()._activeSessionId === sendSessionId) {
        window.clearTimeout(toolTimeout);
        set({ loading: false });
        void get().refreshSessions();
      } else {
        window.clearTimeout(toolTimeout);
      }
    }
  },

  continueTaskItem: async (studentId, itemId) => {
    if (get().loading) return;
    get()._activeAbort?.abort();
    const ac = new AbortController();
    const agentId = `t-${Date.now()}`;
    // bug3：进入 task session 前记住当前主会话 id，供"返回主会话"切回
    const prevMainSessionId =
      get().activeTaskSessionId === null ? get().sessionId : get().mainSessionId;
    set({
      _activeAbort: ac,
      loading: true,
      activeTaskSessionId: null,
      activeTaskItemId: itemId,
      mainSessionId: prevMainSessionId ?? get().mainSessionId,
      messages: [{ id: agentId, role: 'assistant', content: '', tools: [] }],
    });
    try {
      const stream = chatApi.continueTaskItem(studentId, itemId, ac.signal);
      for await (const evt of stream) {
        if (get()._activeAbort !== ac) break;
        if (evt.type === 'session') {
          // 后端推回 task session 信息 -> 切到 task 会话
          const taskSession = evt.session;
          set({
            activeTaskSessionId: taskSession.id,
            sessionId: taskSession.id,
            _activeSessionId: taskSession.id,
            sessions: get().sessions.some((s) => s.id === taskSession.id)
              ? get().sessions
              : [...get().sessions, taskSession],
          });
          persistNav(get);
          // 补拉该 task session 历史，合并到当前轮之前（与 switchSession 共用 loadSessionHistory）。
          // 失败返回 null 则跳过合并，不影响本轮；仍停留在此 task session 才合并，避免切走/中断后污染其他会话。
          const history = await loadSessionHistory(taskSession.id);
          if (
            history &&
            get().activeTaskSessionId === taskSession.id &&
            get().sessionId === taskSession.id
          ) {
            set((state) => ({ messages: [...history, ...state.messages] }));
          }
        } else if (evt.type === 'text') {
          set((state) => ({ messages: state.messages.map((m) => (m.id === agentId ? { ...m, content: m.content + evt.content } : m)) }));
        } else if (evt.type === 'reasoning') {
          set((state) => ({ messages: state.messages.map((m) => (m.id === agentId ? { ...m, reasoning: (m.reasoning || '') + evt.content } : m)) }));
        } else if (evt.type === 'tool_call') {
          set((state) => ({ messages: state.messages.map((m) => (m.id === agentId ? { ...m, tools: [...(m.tools || []), { id: evt.id, name: evt.name, input: evt.input, status: 'running', startedAt: evt.started_at ?? Date.now() }] } : m)) }));
        } else if (evt.type === 'tool_result') {
          set((state) => ({ messages: state.messages.map((m) => (m.id === agentId ? { ...m, tools: (m.tools || []).map((t) => (t.id === evt.id ? { ...t, output: evt.output, elapsedMs: evt.elapsed_ms ?? t.elapsedMs, status: ((evt as { status?: string }).status ?? 'succeeded') as
                      'running' | 'succeeded' | 'failed' | 'blocked' | 'timed_out' | 'done' | 'error'
                    } : t)) } : m)) }));
        } else if (evt.type === 'error') {
          get()._markRunningTools(agentId, `工具执行失败：${evt.message}`);
          set((state) => ({ messages: state.messages.map((m) => (m.id === agentId ? { ...m, content: m.content || `失败：${evt.message}` } : m)) }));
          return;
        } else if (evt.type === 'done') {
          get()._markRunningTools(agentId, '工具没有返回结果。可以重试这一步。');
          // M1：done.content 非空时用它替换本轮最终正文（与落库一致），为空保留已有文本/工具卡
          set((state) => ({
            messages: state.messages.map((m) => {
              if (m.id !== agentId) return m;
              const finalText =
                typeof evt.content === 'string' && evt.content.length > 0
                  ? evt.content
                  : m.content;
              return { ...m, content: finalText };
            }),
          }));
          return;
        }
      }
    } catch (err) {
      const isAbort = err instanceof DOMException && err.name === 'AbortError';
      if (!isAbort) {
        // 容错：SSE 连接失败时，先从后端历史恢复完整 AI 回复（后端总会完整保存）
        const recoverSid = get().activeTaskSessionId ?? get().sessionId;
        const last = recoverSid ? await fetchLastAssistantFromHistory(Number(recoverSid)) : null;
        const cur = get().messages.find((m) => m.id === agentId);
        const recovered =
          !!last &&
          ((last.content || '').length > (cur?.content || '').length ||
            (last.tools?.length || 0) > (cur?.tools?.length || 0));
        if (recovered && last) {
          set((state) => ({
            messages: state.messages.map((m) =>
              m.id === agentId ? { ...m, content: last.content || m.content, tools: last.tools || m.tools } : m,
            ),
          }));
        } else {
          const errorMessage = `连接失败：${getRequestErrorMessage(err)}`;
          get()._markRunningTools(agentId, errorMessage);
          set((state) => ({ messages: state.messages.map((m) => (m.id === agentId ? { ...m, content: errorMessage } : m)) }));
        }
      }
    } finally {
      if (get()._activeAbort === ac) {
        set({ loading: false });
        void get().refreshSessions();
      }
    }
  },

  /** bug3：从 task session 返回主会话--切回进入任务前的主会话并恢复其历史，清 task 状态 */
  returnToMainSession: async () => {
    const mainId = get().mainSessionId;
    set({ activeTaskSessionId: null, activeTaskItemId: null, mainSessionId: null });
    persistNav(get);
    if (mainId && mainId !== get().sessionId) {
      await get().switchSession(mainId);
    }
  },

  switchSession: async (sid) => {
    const generation = initGeneration;
    const isCurrent = () => generation === initGeneration && get()._activeSessionId === sid;
    // 中断正在进行的旧流（UX bug：切换断流）
    get()._activeAbort?.abort();
    set({ _activeSessionId: sid, sessionId: sid, loading: true });
    try {
      // 历史加载收敛到 loadSessionHistory（continueTaskItem 共用同一函数）
      const rendered = await loadSessionHistory(sid);
      if (!isCurrent()) return;
      if (!rendered) {
        // 拉历史失败：不中断切换，空消息降级（与旧 catch 行为一致）
        set({ messages: [] });
      } else {
        set({
          messages: rendered,
          pendingAnswerReview: null,
          pendingNoteDraft: null,
          pendingPlanDraft: null,
          pendingPlanCarryOver: null,
          planCarryOverConfirming: null,
          planCarryOverError: null,
          historicalPlanDraftNotice: null,
        });
        // 恢复最后一个未确认笔记草案（查 status 避免已确认的重现）
        const draft = extractNoteDraftFromHistory(rendered);
        if (draft) {
          try {
            const note = await noteApi.get(draft.id);
            if (!isCurrent()) return;
            if (note.status === 'draft') set({ pendingNoteDraft: draft });
          } catch {
            /* 笔记可能已删，忽略 */
          }
        }
        if (!isCurrent()) return;
        const carryOver = extractPlanCarryOverFromHistory(rendered);
        if (carryOver) set({ pendingPlanCarryOver: carryOver });
        // M1：恢复计划草案按四条件判定——同会话 + draft 晚于最新 user + pending + 未过期
        // 才恢复当前卡；只差消息顺序/legacy 归属（null/跨会话）仍 pending 的降级为历史提示；
        // created/superseded/过期 不显示当前卡也不显示历史提示。
        const planDraftInfo = extractPlanDraftFromHistory(rendered);
        if (planDraftInfo) {
          const lastUserIndex = findLastUserIndex(rendered);
          const draftAfterLastUser = lastUserIndex < 0 || planDraftInfo.index > lastUserIndex;
          try {
            const detail = await p2Api.getPlanDraft(
              planDraftInfo.draft.draftId,
              get()._boundStudentId ?? undefined,
            );
            if (!isCurrent()) return;
            if (detail.status === 'pending' && detail.is_expired === false) {
              const sameSession = detail.chat_session_id != null && detail.chat_session_id === sid;
              if (sameSession && draftAfterLastUser) {
                set({ pendingPlanDraft: planDraftInfo.draft });
              } else {
                set({ historicalPlanDraftNotice: planDraftInfo.draft });
              }
            }
          } catch {
            /* 草案可能已过期/不存在，忽略 */
          }
        }
      }
    } catch {
      if (isCurrent()) set({ messages: [] });
    } finally {
      if (isCurrent()) set({ loading: false });
    }
    if (isCurrent()) persistNav(get);
  },

  confirmPlanDraft: async () => {
    const draft = get().pendingPlanDraft;
    if (!draft || get().planDraftConfirming) return;
    set({ planDraftConfirming: true });
    try {
      await p2Api.confirmPlanDraft(draft.draftId, draft.revision);
      set({ pendingPlanDraft: null, historicalPlanDraftNotice: null, planVersion: get().planVersion + 1 });
    } catch (err) {
      console.error('确认计划草案失败', err);
    } finally {
      set({ planDraftConfirming: false });
    }
  },

  carryOverStudyPlan: async (planId) => {
    const studentId = get()._resolveStudentId();
    if (!studentId || get().planCarryOverConfirming !== null) return;
    set({ planCarryOverConfirming: planId, planCarryOverError: null });
    try {
      await p2Api.carryOverStudyPlan(planId);
      set({ pendingPlanCarryOver: null, planCarryOverError: null, planVersion: get().planVersion + 1 });
    } catch (err) {
      set({ planCarryOverError: getRequestErrorMessage(err) });
    } finally {
      set({ planCarryOverConfirming: null });
    }
  },
  newSession: async () => {
    const generation = initGeneration;
    get()._activeAbort?.abort();
    const studentId = get()._boundStudentId ?? 0;
    const s = await chatApi.createSession(studentId);
    if (generation !== initGeneration) return;
    set({
      sessionId: s.id,
      _activeSessionId: s.id,
      messages: [],
      pendingAnswerReview: null,
      pendingNoteDraft: null,
      pendingPlanDraft: null,
      pendingPlanCarryOver: null,
      planCarryOverConfirming: null,
      planCarryOverError: null,
      historicalPlanDraftNotice: null,
    });
    await get().refreshSessions();
    if (generation === initGeneration) persistNav(get);
  },

  resetContext: async () => {
    const sessionId = get().sessionId;
    if (!sessionId) return;
    get()._activeAbort?.abort();
    await chatApi.resetContext(sessionId);
    set({
      messages: [],
      pendingNoteDraft: null,
      pendingAnswerReview: null,
      pendingPlanDraft: null,
      pendingPlanCarryOver: null,
      planCarryOverConfirming: null,
      planCarryOverError: null,
      historicalPlanDraftNotice: null,
    });
  },

  refreshSessions: async () => {
    const generation = initGeneration;
    try {
      const list = await chatApi.listSessions();
      if (generation === initGeneration) set({ sessions: list });
    } catch {
      // 忽略
    }
  },

  renameSession: async (sid, title) => {
    await chatApi.renameSession(sid, title);
    await get().refreshSessions();
  },

  deleteSession: async (sid) => {
    await chatApi.deleteSession(sid);
    // 删的是当前会话则切到下一个（或新建）
    if (sid === get().sessionId) {
      try {
        const list = await chatApi.listSessions();
        if (list.length > 0) {
          await get().switchSession(list[0].id);
        } else {
          await get().newSession();
        }
      } catch {
        // 切下一个失败不影响删除结果
      }
    }
    await get().refreshSessions();
  },

  setPendingNoteDraft: (d) => set({ pendingNoteDraft: d }),
  setPendingAnswerReview: (r) => set({ pendingAnswerReview: r }),
  clearPendingNoteDraft: () => set({ pendingNoteDraft: null }),
  clearPendingAnswerReview: () => set({ pendingAnswerReview: null }),
  clearHistoricalPlanDraftNotice: () => set({ historicalPlanDraftNotice: null }),
  setNoteDraftConfirming: (b) => set({ noteDraftConfirming: b }),
  setAnswerReviewConfirming: (b) => set({ answerReviewConfirming: b }),

  recordErrorReport: (report) =>
    set({
      latestErrorReport: {
        ...report,
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      },
    }),
  clearErrorReport: () => set({ latestErrorReport: null }),

  reset: () => {
    initGeneration += 1;
    initInFlight = null;
    get()._activeAbort?.abort();
    const prevStudentId = get()._boundStudentId;
    set({
      messages: [],
      loading: false,
      sessionId: null,
      sessions: [],
      activeTaskSessionId: null,
      activeTaskItemId: null,
      mainSessionId: null,
      pendingNoteDraft: null,
      noteDraftConfirming: false,
      pendingPlanDraft: null,
      pendingPlanCarryOver: null,
      planCarryOverConfirming: null,
      planCarryOverError: null,
      planDraftConfirming: false,
      pendingAnswerReview: null,
      answerReviewConfirming: false,
      historicalPlanDraftNotice: null,
      latestErrorReport: null,
      _activeSessionId: null,
      _activeAbort: null,
      _boundToken: null,
      _boundRole: null,
      _boundUserId: null,
      _boundStudentId: null,
    });
    if (prevStudentId) clearNavState(prevStudentId);
  },

  _markRunningTools: (agentId, output) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === agentId
          ? {
              ...m,
              tools: (m.tools || []).map((t) =>
                t.status === 'running' ? { ...t, status: 'error' as const, output } : t,
              ),
            }
          : m,
      ),
    })),

  _resolveStudentId: () => {
    const s = get();
    if (s._boundRole === 'student') return s._boundUserId;
    return s._boundStudentId;
  },
}));
