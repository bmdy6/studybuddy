import { useCallback } from 'react';
import { Input } from 'antd';
import { examBatchApi } from '@/features/exams/examBatch';
import { noteApi } from '@/features/note/api';
import { getRequestErrorMessage } from '@/shared/api/client';
import { useChatStore, type ErrorReportInfo } from '@/features/chat/store';
import type { NoteDraftState, PhotoAnswerReviewItem } from '@/types';

interface MessageApi {
  success: (content: string) => void;
  error: (content: string) => void;
}

interface UseChatSessionsOptions {
  token: string | null;
  message: MessageApi;
  resolveStudentId: () => number | null;
  sessionId: number | null;
  onSend: (content: string) => Promise<void>;
  pendingAnswerReview: { batch_id: number } | null;
  pendingNoteDraft: NoteDraftState | null;
}

export function useChatSessions({
  token,
  message,
  resolveStudentId,
  sessionId,
  onSend,
  pendingAnswerReview,
  pendingNoteDraft,
}: UseChatSessionsOptions) {
  const newSession = useCallback(async () => {
    if (!token) return;
    try {
      await useChatStore.getState().newSession();
    } catch {
      message.error('创建会话失败');
    }
  }, [token, message]);

  const resetContext = useCallback(async () => {
    const { Modal } = await import('antd');
    Modal.confirm({
      title: '开始新上下文？',
      content: '将清空当前会话的所有消息，开始全新对话。计划、错题、笔记和学习档案不受影响。',
      okText: '开始',
      cancelText: '取消',
      centered: true,
      zIndex: 1200,
      onOk: async () => {
        try {
          await useChatStore.getState().resetContext();
          message.success('已清空，开始新对话');
        } catch {
          message.error('开始新上下文失败');
        }
      },
    });
  }, [message]);

  const renameSession = useCallback(
    async (sid: number, oldTitle: string) => {
      let newTitle: string | null = null;
      const { Modal } = await import('antd');
      const modal = Modal.confirm({
        title: '重命名会话',
        content: (
          <Input
            defaultValue={oldTitle}
            autoFocus
            onChange={(event) => {
              newTitle = event.target.value;
            }}
            onPressEnter={() => {
              modal.destroy();
            }}
          />
        ),
        onOk: async () => {
          const title = (newTitle ?? '').trim();
          if (!title || title === oldTitle) return;
          try {
            await useChatStore.getState().renameSession(sid, title);
            message.success('已重命名');
          } catch {
            message.error('重命名失败');
          }
        },
      });
    },
    [message],
  );

  const deleteSession = useCallback(
    async (sid: number) => {
      const { Modal } = await import('antd');
      Modal.confirm({
        title: '删除该会话？',
        content: '删除后无法恢复，会话内所有消息将一并清除。',
        okText: '删除',
        okType: 'danger',
        cancelText: '取消',
        onOk: async () => {
          try {
            await useChatStore.getState().deleteSession(sid);
            message.success('已删除');
          } catch {
            message.error('删除失败');
          }
        },
      });
    },
    [message],
  );

  const switchSession = useCallback((sid: number) => {
    void useChatStore.getState().switchSession(sid);
  }, []);

  const confirmAnswerReview = useCallback(
    async (items: PhotoAnswerReviewItem[]) => {
      if (!pendingAnswerReview) return;
      const store = useChatStore.getState();
      store.setAnswerReviewConfirming(true);
      try {
        await examBatchApi.confirmAnswerReview(pendingAnswerReview.batch_id, { items });
        store.clearPendingAnswerReview();
        message.success('已确认作答，开始批改');
        await onSend(
          `[拍题批改] 我已确认批次 #${pendingAnswerReview.batch_id} 的逐题作答，请基于我刚确认的逐题作答进行批改，逐题给正确答案、错因和知识点。`,
        );
      } catch (error) {
        const errorMessage = `确认作答失败：${getRequestErrorMessage(error)}`;
        store.recordErrorReport({
          context: 'chat:answer-review-confirm',
          message: errorMessage,
          details: `batch_id=${pendingAnswerReview.batch_id}`,
          sessionId,
          studentId: resolveStudentId(),
        } satisfies Omit<ErrorReportInfo, 'id'>);
        message.error(errorMessage);
      } finally {
        store.setAnswerReviewConfirming(false);
      }
    },
    [message, onSend, pendingAnswerReview, resolveStudentId, sessionId],
  );

  const confirmNoteDraft = useCallback(
    async (edits: Partial<NoteDraftState>) => {
      if (!pendingNoteDraft) return;
      const store = useChatStore.getState();
      store.setNoteDraftConfirming(true);
      try {
        await noteApi.update(pendingNoteDraft.id, edits);
        const edited = !!(edits.title || edits.content || edits.category);
        store.clearPendingNoteDraft();
        message.success('已保存为正式笔记');
        await onSend(
          `[笔记确认] 我已确认笔记「${pendingNoteDraft.title}」（id ${pendingNoteDraft.id}）${edited ? '并做了修改' : ''}，现在作为正式笔记，你后续可以参考它。`,
        );
      } catch (error) {
        const errorMessage = `保存笔记失败：${getRequestErrorMessage(error)}`;
        store.recordErrorReport({
          context: 'chat:note-draft-confirm',
          message: errorMessage,
          details: `note_id=${pendingNoteDraft.id}`,
          sessionId,
          studentId: resolveStudentId(),
        } satisfies Omit<ErrorReportInfo, 'id'>);
        message.error(errorMessage);
      } finally {
        store.setNoteDraftConfirming(false);
      }
    },
    [message, onSend, pendingNoteDraft, resolveStudentId, sessionId],
  );

  return {
    newSession,
    resetContext,
    renameSession,
    deleteSession,
    switchSession,
    confirmAnswerReview,
    confirmNoteDraft,
  };
}
