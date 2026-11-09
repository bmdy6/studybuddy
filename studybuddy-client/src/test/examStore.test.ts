import { describe, it, expect, beforeEach } from 'vitest';
import { useExamStore } from '@/features/exams/store';

describe('examStore 标记题目', () => {
  beforeEach(() => {
    useExamStore.setState({ drafts: {}, marked: {}, activeRecord: null });
  });

  it('toggleMark 标记后再取消', () => {
    const { toggleMark } = useExamStore.getState();
    expect(useExamStore.getState().isMarked(1, 10)).toBe(false);
    toggleMark(1, 10);
    expect(useExamStore.getState().isMarked(1, 10)).toBe(true);
    toggleMark(1, 10);
    expect(useExamStore.getState().isMarked(1, 10)).toBe(false);
  });

  it('标记状态按 examRecordId 隔离', () => {
    const { toggleMark } = useExamStore.getState();
    toggleMark(1, 10);
    expect(useExamStore.getState().isMarked(2, 10)).toBe(false);
  });

  it('clearDraft 同时清理草稿和标记', () => {
    const { toggleMark, setDraft, clearDraft } = useExamStore.getState();
    setDraft(1, 10, 'A');
    toggleMark(1, 10);
    toggleMark(1, 20);
    clearDraft(1);
    expect(useExamStore.getState().isMarked(1, 10)).toBe(false);
    expect(useExamStore.getState().isMarked(1, 20)).toBe(false);
    expect(useExamStore.getState().getDraft(1, 10)).toBeUndefined();
  });
});
