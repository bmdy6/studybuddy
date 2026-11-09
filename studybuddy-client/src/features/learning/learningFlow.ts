import client from '@/shared/api/client';
import type { LearningFlowEntry } from '@/types';

export const learningFlowApi = {
  getEntry: (studentId: number) =>
    client
      .get<LearningFlowEntry>('/api/learning-flow/entry', {
        params: { student_id: studentId },
      })
      .then((response) => response.data),
  getReviewEntry: ({
    studentId,
    errorId,
    knowledgeTag,
  }: {
    studentId: number;
    errorId?: number;
    knowledgeTag?: string;
  }) =>
    client
      .get<LearningFlowEntry>('/api/learning-flow/review-entry', {
        params: {
          student_id: studentId,
          ...(errorId ? { error_id: errorId } : {}),
          ...(knowledgeTag ? { knowledge_tag: knowledgeTag } : {}),
        },
      })
      .then((response) => response.data),
};
