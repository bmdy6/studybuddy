import { useEffect, useRef, useState } from 'react';
import { answerApi } from '@/features/exams/answer';
import type { PendingGradeItem } from '@/types';

interface UsePollingOptions {
  /** 考试记录 ID，null 则不轮询 */
  examRecordId: number | null;
  /** 轮询间隔 ms，默认 5s */
  intervalMs?: number;
  /** 是否启用，默认 true */
  enabled?: boolean;
}

interface PollingState {
  /** 是否仍在等待人工判分 */
  isGrading: boolean;
  /** 该记录下待批改条目数 */
  pendingCount: number;
  /** 最近一次轮询错误 */
  error: string | null;
}

/**
 * 轮询判分状态。
 *
 * 后端无专用"学生查自己判分进度"端点，复用 /api/answers/pending
 * 按 exam_record_id 客户端过滤：该记录在 pending 列表中消失即判分完成。
 */
export function usePolling({ examRecordId, intervalMs = 5000, enabled = true }: UsePollingOptions) {
  const [state, setState] = useState<PollingState>({
    isGrading: false,
    pendingCount: 0,
    error: null,
  });
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!enabled || !examRecordId) {
      setState({ isGrading: false, pendingCount: 0, error: null });
      return;
    }

    let cancelled = false;

    const poll = async () => {
      try {
        const pending: PendingGradeItem[] = await answerApi.pending(100);
        if (cancelled) return;
        const mine = pending.filter((p) => p.exam_record_id === examRecordId);
        const stillGrading = mine.length > 0;
        setState({
          isGrading: stillGrading,
          pendingCount: mine.length,
          error: null,
        });
      } catch (err: unknown) {
        if (cancelled) return;
        setState((prev) => ({
          ...prev,
          error: err instanceof Error ? err.message : '轮询失败',
        }));
      }
    };

    // 立即跑一次
    poll();
    timerRef.current = setInterval(poll, intervalMs);

    return () => {
      cancelled = true;
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [examRecordId, intervalMs, enabled]);

  return state;
}
