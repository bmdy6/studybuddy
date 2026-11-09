import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface ExamRecord {
  exam_id: number;
  exam_record_id: number;
  started_at: number;
}

interface ExamState {
  /** key = exam_record_id，value = 该记录下的草稿答案 */
  drafts: Record<number, Record<number, string>>;
  /** key = exam_record_id，value = 标记的题目 id 列表 */
  marked: Record<number, number[]>;
  /** 当前进行中的考试记录（exam_record_id 为键） */
  activeRecord: ExamRecord | null;

  setDraft: (examRecordId: number, questionId: number, answer: string) => void;
  getDraft: (examRecordId: number, questionId: number) => string | undefined;
  clearDraft: (examRecordId: number) => void;
  toggleMark: (examRecordId: number, questionId: number) => void;
  isMarked: (examRecordId: number, questionId: number) => boolean;
  setActiveRecord: (record: ExamRecord | null) => void;
}

/**
 * 答题草稿 + 标记 store -- persist 到 localStorage，刷新/断网不丢。
 * 提交成功后由调用方 clearDraft 清理（同时清标记）。
 */
export const useExamStore = create<ExamState>()(
  persist(
    (set, get) => ({
      drafts: {},
      marked: {},
      activeRecord: null,

      setDraft: (examRecordId, questionId, answer) =>
        set((state) => ({
          drafts: {
            ...state.drafts,
            [examRecordId]: {
              ...(state.drafts[examRecordId] ?? {}),
              [questionId]: answer,
            },
          },
        })),

      getDraft: (examRecordId, questionId) => get().drafts[examRecordId]?.[questionId],

      clearDraft: (examRecordId) =>
        set((state) => {
          const drafts = { ...state.drafts };
          const marked = { ...state.marked };
          delete drafts[examRecordId];
          delete marked[examRecordId];
          return { drafts, marked };
        }),

      toggleMark: (examRecordId, questionId) =>
        set((state) => {
          const current = state.marked[examRecordId] ?? [];
          const next = current.includes(questionId)
            ? current.filter((id) => id !== questionId)
            : [...current, questionId];
          return { marked: { ...state.marked, [examRecordId]: next } };
        }),

      isMarked: (examRecordId, questionId) =>
        (get().marked[examRecordId] ?? []).includes(questionId),

      setActiveRecord: (record) => set({ activeRecord: record }),
    }),
    { name: 'studybuddy-exam' },
  ),
);
