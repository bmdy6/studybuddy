/**
 * Agent 对话首页（P2 agent 化 F1）。
 *
 * 需求文档 §4.3：流式对话气泡（user 右 / agent 左），底部输入框。
 * 工具调用通过卡片实时可见（§5 learn-claude-code s02 可见性设计的 Web 等价物）。
 *
 * 配色（样式设计文档 + 调研方案）：
 * - user 气泡：苹果蓝 var(--sb-color-primary) 实色，右对齐
 * - agent 气泡：纯白微浮起，左对齐，淡边框
 * - 工具卡片：暖灰底 var(--sb-color-bg-muted)，左侧紫色状态条 var(--sb-color-tool-accent)
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { App, Button } from 'antd';
import { useAuthStore } from '@/features/auth/store';
import { useChatStore, type ErrorReportInfo } from '@/features/chat/store';
import TodayPlanPanel from '@/features/chat/components/TodayPlanPanel';
import { BatchUploadModal } from '@/features/chat/components/BatchUploadModal';
import { MaterialUploadModal } from '@/features/chat/components/MaterialUploadModal';
import {
  ChatSessionToolbar,
  StudentConversationActions,
} from '@/features/chat/components/ChatSessionToolbar';
import { ParentLearningWorkbench } from '@/features/chat/components/ParentLearningWorkbench';
import { ChatMessageList } from '@/features/chat/components/ChatMessageList';
import { ChatComposer } from '@/features/chat/components/ChatComposer';
import { useChatUploads } from '@/features/chat/hooks/useChatUploads';
import { useChatSessions } from '@/features/chat/hooks/useChatSessions';
import { useStudentLearningFlow } from '@/features/chat/hooks/useStudentLearningFlow';
import { useChatProfileSummary } from '@/features/chat/hooks/useChatProfileSummary';
import { useBreakpoint } from '@/shared/theme/breakpoints';
import { buildErrorReportText } from '@/features/chat/errorReport';
import { useOpenFamilyTaskCount } from '@/features/family_goal/hooks';

const PROFILE_PROMPT_SNOOZE_KEY = 'sb_profile_prompt_snooze_until';
const PROFILE_PROMPT_SNOOZE_MS = 7 * 24 * 60 * 60 * 1000;

function readProfilePromptSnoozed(): boolean {
  try {
    const until = Number(localStorage.getItem(PROFILE_PROMPT_SNOOZE_KEY) || 0);
    return until > Date.now();
  } catch {
    return false;
  }
}

function getInitialChatQuery() {
  const hashQuery = window.location.hash.includes('?')
    ? window.location.hash.slice(window.location.hash.indexOf('?') + 1)
    : '';
  return new URLSearchParams(hashQuery || window.location.search);
}

export default function ChatPage() {
  const { message } = App.useApp();
  const initialQuery = useMemo(() => getInitialChatQuery(), []);
  // 运行态从 chatStore 订阅（切页不丢；后台流继续更新 store，组件重挂载后订阅到最新）
  const messages = useChatStore((s) => s.messages);
  const loading = useChatStore((s) => s.loading);
  const sessionId = useChatStore((s) => s.sessionId);
  const sessions = useChatStore((s) => s.sessions);
  const pendingNoteDraft = useChatStore((s) => s.pendingNoteDraft);
  const noteDraftConfirming = useChatStore((s) => s.noteDraftConfirming);
  const pendingAnswerReview = useChatStore((s) => s.pendingAnswerReview);
  const answerReviewConfirming = useChatStore((s) => s.answerReviewConfirming);
  const latestErrorReport = useChatStore((s) => s.latestErrorReport);
  const activeTaskSessionId = useChatStore((s) => s.activeTaskSessionId);
  const [input, setInput] = useState(() => initialQuery.get('prompt')?.trim() ?? '');
  const [profilePromptDismissed, setProfilePromptDismissed] = useState(readProfilePromptSnoozed);
  const snoozeProfilePrompt = useCallback(() => {
    try {
      localStorage.setItem(PROFILE_PROMPT_SNOOZE_KEY, String(Date.now() + PROFILE_PROMPT_SNOOZE_MS));
    } catch {
      /* localStorage 不可用时仅本会话静默 */
    }
    setProfilePromptDismissed(true);
  }, []);
  const inputRef = useRef<import('antd').InputRef>(null);
  const bp = useBreakpoint();
  const authState = useAuthStore();
  const { token, role, activeChildId, userId } = authState;
  const requestedStudentId = useMemo(() => {
    const raw = initialQuery.get('student_id');
    const parsed = raw ? Number(raw) : NaN;
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
  }, [initialQuery]);
  // 学习页继续卡片带过来的计划项 id：init 完成后自动建/恢复对应 task session
  const continueTaskItemId = useMemo(() => {
    const raw = initialQuery.get('continue_task_item');
    const parsed = raw ? Number(raw) : NaN;
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
  }, [initialQuery]);
  const practiceExamRecordId = useMemo(() => {
    const raw = initialQuery.get('practice_exam_record');
    const parsed = raw ? Number(raw) : NaN;
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
  }, [initialQuery]);
  const activeChild = useMemo(() => {
    const list = authState.children ?? [];
    return list.find((child) => child.id === (requestedStudentId ?? activeChildId)) ?? list[0];
  }, [activeChildId, authState.children, requestedStudentId]);

  // 切换会话：交给 chatStore（含中断旧流、加载历史、恢复未确认草案）
  const resolveChatStudentId = useCallback(() => {
    if (role === 'student') return userId;
    return requestedStudentId ?? activeChildId ?? activeChild?.id ?? null;
  }, [activeChild?.id, activeChildId, requestedStudentId, role, userId]);

  const recordErrorReport = useCallback((report: Omit<ErrorReportInfo, 'id'>) => {
    useChatStore.getState().recordErrorReport({ ...report, studentId: report.studentId ?? resolveChatStudentId() });
  }, [resolveChatStudentId]);

  const copyErrorReport = useCallback(
    async (report: ErrorReportInfo) => {
      await navigator.clipboard.writeText(
        buildErrorReportText(report, {
          role,
          userId,
          path: window.location.href,
        }),
      );
      message.success('错误信息已复制');
    },
    [message, role, userId],
  );

  // 初始化：身份（token/学生）变化时 reset+重选会话；切页回来身份未变则保留进行中的流
  useEffect(() => {
    void useChatStore.getState().init({
      token,
      role,
      userId,
      requestedStudentId,
      activeChildId,
    });
  }, [token, role, userId, requestedStudentId, activeChildId]);

  const handleSend = useCallback(
    async (overrideContent?: string, displayContent?: string) => {
      const liveInput = inputRef.current?.input?.value;
      const content = (overrideContent ?? liveInput ?? input).trim();
      if (!content || !sessionId || loading) return;
      if (!overrideContent) setInput('');
      // 流式循环在 chatStore.runSend 里跑，与组件生命周期解耦：
      // 切页卸载不影响后台流，重挂载后订阅到 store 最新状态
      await useChatStore.getState().runSend(content, displayContent);
    },
    [input, sessionId, loading],
  );

  const chatSessions = useChatSessions({
    token,
    message,
    resolveStudentId: resolveChatStudentId,
    sessionId,
    onSend: handleSend,
    pendingAnswerReview,
    pendingNoteDraft,
  });
  const uploads = useChatUploads({
    sessionId,
    resolveStudentId: resolveChatStudentId,
    onSend: handleSend,
    onError: recordErrorReport,
    message,
  });
  const sessionControls = {
    sessions,
    sessionId,
    onSwitch: chatSessions.switchSession,
    onCreate: () => {
      void chatSessions.newSession();
    },
    onResetContext: () => {
      void chatSessions.resetContext();
    },
    onRename: (targetSessionId: number, title: string) => {
      void chatSessions.renameSession(targetSessionId, title);
    },
    onDelete: (targetSessionId: number) => {
      void chatSessions.deleteSession(targetSessionId);
    },
  };
  const currentSession = sessions.find((s) => s.id === sessionId);
  const currentSessionStudentId =
    currentSession?.student_id && currentSession.student_id > 0 ? currentSession.student_id : null;
  const currentChatStudentId =
    requestedStudentId ??
    currentSessionStudentId ??
    (role === 'student' ? userId : (activeChild?.id ?? activeChildId));
  const currentChild = (authState.children ?? []).find(
    (child) => child.id === currentChatStudentId,
  );
  const currentStudentName = currentChatStudentId
    ? (currentChild?.display_name ?? `学生 #${currentChatStudentId}`)
    : '未选择学生';

  const studentLearning = useStudentLearningFlow({
    token,
    role,
    studentId: currentChatStudentId,
    inputRef,
    setInput,
    onSend: handleSend,
    onContinueTaskItem: (sid, itemId) => useChatStore.getState().continueTaskItem(sid, itemId),
    onReturnToMain: () => useChatStore.getState().returnToMainSession(),
    activeTaskSessionId,
  });
  const profileSummary = useChatProfileSummary(token, currentChatStudentId);
  // 今天页轻提示：只提醒学生自己，没有待完成任务就不渲染
  const openFamilyTaskCount = useOpenFamilyTaskCount(
    role === 'student' ? currentChatStudentId : null,
  );

  // 冷启动自动开口：学生空会话 + 画像缺年级（冷启动第一项）+ 未触发过 -> 自动触发 agent 问年级
  const coldStartTriggeredRef = useRef(false);
  useEffect(() => {
    if (role !== 'student' || !sessionId || loading) return;
    if (messages.length > 0) return;
    if (coldStartTriggeredRef.current) return;
    const needsColdStart =
      !!profileSummary?.needs_onboarding && !!profileSummary?.missing_fields?.includes('grade');
    if (!needsColdStart) return;
    coldStartTriggeredRef.current = true;
    void useChatStore.getState().runSend('', undefined, { skipUserMessage: true });
  }, [role, sessionId, loading, messages.length, profileSummary]);

  // 学习页继续卡片：带 continue_task_item 进来时，init 完成后自动建/恢复 task session。
  // 与 TodayPlanPanel 顶部「继续学习」走同一入口（continueTaskItem），不预填主会话输入框。
  // 触发后清掉 query，避免刷新重复拉回 task session（刷新由 persistNav 恢复真实位置）。
  const autoStartTaskItemRef = useRef(false);
  useEffect(() => {
    if (!continueTaskItemId) return;
    if (autoStartTaskItemRef.current) return;
    if (!currentChatStudentId || !sessionId || loading) return;
    autoStartTaskItemRef.current = true;
    // 触发即清 query，无论是否已在 task session，都避免后续刷新重复拉回
    const hash = window.location.hash;
    const qIdx = hash.indexOf('?');
    if (qIdx !== -1) {
      const path = hash.slice(0, qIdx);
      const params = new URLSearchParams(hash.slice(qIdx + 1));
      params.delete('continue_task_item');
      const qs = params.toString();
      window.history.replaceState(null, '', qs ? `${path}?${qs}` : path);
    }
    // 已恢复的正是目标 task session 时不重复触发；若记住的是其他任务，必须切回 URL 指定任务。
    const activeTask = sessions.find((item) => item.id === activeTaskSessionId);
    if (activeTaskSessionId !== null && activeTask?.plan_item_id === continueTaskItemId) return;
    void useChatStore.getState().continueTaskItem(currentChatStudentId, continueTaskItemId);
  }, [continueTaskItemId, currentChatStudentId, sessionId, loading, activeTaskSessionId, sessions]);

  // 计划内自练卷结果页返回后：先恢复 task session，再自动让老师读取正式结果复盘。
  const autoReviewPracticeExamRef = useRef(false);
  useEffect(() => {
    if (!practiceExamRecordId || autoReviewPracticeExamRef.current) return;
    if (
      !sessionId ||
      loading ||
      activeTaskSessionId === null ||
      sessionId !== activeTaskSessionId ||
      currentSession?.plan_item_id !== continueTaskItemId
    ) return;
    autoReviewPracticeExamRef.current = true;
    const hash = window.location.hash;
    const qIdx = hash.indexOf('?');
    if (qIdx !== -1) {
      const path = hash.slice(0, qIdx);
      const params = new URLSearchParams(hash.slice(qIdx + 1));
      params.delete('practice_exam_record');
      const qs = params.toString();
      window.history.replaceState(null, '', qs ? `${path}?${qs}` : path);
    }
    void useChatStore.getState().runSend(
      `我已经完成自练卷（exam_record_id=${practiceExamRecordId}）。请先调用 query_practice_exam_result 读取当前任务的正式逐题结果，再根据真实作答复盘。`,
      '我已经完成这次练习，请根据正式结果帮我复盘。',
    );
  }, [practiceExamRecordId, sessionId, loading, activeTaskSessionId, currentSession?.plan_item_id, continueTaskItemId]);

  return (
    <div className="sb-chat-surface">
      {role !== 'student' ? <ChatSessionToolbar {...sessionControls} /> : null}

      {bp.isMobile && role === 'student' && currentChatStudentId && (
        <TodayPlanPanel
          studentId={currentChatStudentId}
          mode={studentLearning.mode}
          learningPrompt={studentLearning.learningPrompt}
          onStartLearning={studentLearning.startLearning}
          onReturnToday={studentLearning.returnToToday}
          onTaskCompleted={studentLearning.completeTask}
          onContinueConversation={studentLearning.continueConversation}
          onAskAiToPlan={studentLearning.askAiToPlan}
          conversationActions={<StudentConversationActions {...sessionControls} />}
        />
      )}

      {role === 'student' && openFamilyTaskCount > 0 && (
        <div className="sb-learning-dock sb-learning-dock--today">
          <Button
            type="link"
            block
            size="large"
            onClick={() => {
              window.location.hash = '#/family-tasks';
            }}
          >
            今天还有 {openFamilyTaskCount} 件家庭任务待完成
          </Button>
        </div>
      )}

      <ChatMessageList
        messages={messages}
        loading={loading}
        role={role}
        sessionId={sessionId}
        workbench={
          <ParentLearningWorkbench
            studentName={currentStudentName}
            profileSummary={profileSummary}
            profilePromptDismissed={profilePromptDismissed}
            onPrompt={(prompt) => {
              setInput(prompt);
              inputRef.current?.focus();
            }}
            onEditProfile={() => {
              window.location.hash = '#/profile';
            }}
            onSnoozeProfile={snoozeProfilePrompt}
          />
        }
      />

      <ChatComposer
        input={input}
        inputRef={inputRef}
        batchFileInputRef={uploads.batchFileInputRef}
        sessionId={sessionId}
        loading={loading}
        batchUploading={uploads.batchUploading}
        materialUploading={uploads.materialUploading}
        pendingAnswerReview={pendingAnswerReview}
        answerReviewConfirming={answerReviewConfirming}
        pendingNoteDraft={pendingNoteDraft}
        noteDraftConfirming={noteDraftConfirming}
        latestErrorReport={latestErrorReport}
        onInputChange={setInput}
        onSend={handleSend}
        onOpenBatchUpload={uploads.openBatchModal}
        onOpenMaterialUpload={uploads.openMaterialModal}
        onAnswerReviewConfirm={chatSessions.confirmAnswerReview}
        onNoteDraftConfirm={chatSessions.confirmNoteDraft}
        onCopyError={copyErrorReport}
        onCloseError={() => useChatStore.getState().clearErrorReport()}
      />

      <BatchUploadModal
        open={uploads.batchModalOpen}
        files={uploads.pendingPhotos}
        uploading={uploads.batchUploading}
        error={uploads.batchError}
        form={uploads.batchForm}
        onCancel={uploads.cancelBatchModal}
        onConfirm={uploads.confirmBatchUpload}
      />

      <MaterialUploadModal
        open={uploads.materialModalOpen}
        file={uploads.pendingMaterial?.file ?? null}
        uploading={uploads.materialUploading}
        form={uploads.materialForm}
        onCancel={uploads.cancelMaterialModal}
        onConfirm={uploads.confirmMaterialUpload}
      />
    </div>
  );
}
