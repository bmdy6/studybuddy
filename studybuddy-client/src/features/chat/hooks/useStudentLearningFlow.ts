import { useCallback, useEffect, useState, type Dispatch, type RefObject, type SetStateAction } from 'react';
import type { InputRef } from 'antd';
import { learningFlowApi } from '@/features/learning/learningFlow';
import type { Role } from '@/shared/constants';
import type { LearningFlowEntry } from '@/types';
import type { TodayLearningTask } from '@/features/chat/components/TodayPlanPanel';

interface UseStudentLearningFlowOptions {
  token: string | null;
  role: Role | null;
  studentId: number | null;
  inputRef: RefObject<InputRef>;
  setInput: Dispatch<SetStateAction<string>>;
  onSend: (content: string) => Promise<void>;
  /** U-042：继续某个计划项 -> 后端建 task session + 触发 agent */
  onContinueTaskItem: (studentId: number, itemId: number) => Promise<void>;
  /** bug3：从 task session 返回主会话 */
  onReturnToMain: () => Promise<void>;
  /** 当前是否在 task session（刷新后从持久化恢复），用于推导初始 mode */
  activeTaskSessionId: number | null;
}

export function useStudentLearningFlow({
  token,
  role,
  studentId,
  inputRef,
  setInput,
  onSend,
  onContinueTaskItem,
  onReturnToMain,
  activeTaskSessionId,
}: UseStudentLearningFlowOptions) {
  const [entry, setEntry] = useState<LearningFlowEntry | null>(null);
  const [entryVersion, setEntryVersion] = useState(0);
  // mode 初始值从持久化恢复的 activeTaskSessionId 推导：刷新后若仍在 task session，
  // 直接显示 learning 模式（含"返回今天"按钮），不重置为 today。
  const [mode, setMode] = useState<'today' | 'learning'>(
    activeTaskSessionId ? 'learning' : 'today',
  );

  // activeTaskSessionId 是 mode 的唯一真相源。useState 初始值只在首次挂载取值，
  // 但首次挂载时 store init 可能还没跑（activeTaskSessionId 仍为 null），
  // init 恢复后才变非 null。这里用 effect 同步，保证刷新后恢复 task session 时
  // mode 跟着切到 learning（返回今天按钮才显示）。
  useEffect(() => {
    setMode(activeTaskSessionId ? 'learning' : 'today');
  }, [activeTaskSessionId]);

  useEffect(() => {
    if (!token || role !== 'student' || !studentId) {
      setEntry(null);
      return;
    }
    let alive = true;
    learningFlowApi
      .getEntry(studentId)
      .then((nextEntry) => {
        if (alive) setEntry(nextEntry);
      })
      .catch(() => {
        if (alive) setEntry(null);
      });
    return () => {
      alive = false;
    };
  }, [entryVersion, role, studentId, token]);

  const startLearning = useCallback(
    (task: TodayLearningTask, _prompt: string) => {
      setMode('learning');
      // U-042：直接让后端建/恢复 task session 并触发 agent，不再预填输入框
      if (studentId) {
        void onContinueTaskItem(studentId, task.item.id);
      }
    },
    [onContinueTaskItem, studentId],
  );

  const completeTask = useCallback(() => {
    void onSend('我做完了这个任务');
    setEntry(null);
    setEntryVersion((version) => version + 1);
  }, [onSend]);

  const continueConversation = useCallback(
    (prompt?: string) => {
      setMode('learning');
      if (prompt) setInput((current) => (current.trim() ? current : prompt));
    },
    [setInput],
  );

  const askAiToPlan = useCallback(async () => {
    setMode('learning');
    await onSend('帮我制定今天的学习计划');
  }, [onSend]);

  useEffect(() => {
    if (role !== 'student' || mode !== 'learning') return;
    inputRef.current?.focus();
  }, [inputRef, mode, role]);

  return {
    mode,
    learningPrompt: entry?.kind === 'continue_plan' ? entry.prompt : '',
    startLearning,
    returnToToday: () => {
      void onReturnToMain();
      setMode('today');
    },
    completeTask,
    continueConversation,
    askAiToPlan,
  };
}
