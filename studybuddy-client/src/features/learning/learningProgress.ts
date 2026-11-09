import client from '@/shared/api/client';
import type { LearningProgressMetrics } from '@/types';

export const learningProgressApi = {
  get: (studentId: number, asOf?: string) =>
    client
      .get<LearningProgressMetrics>('/api/learning-progress', {
        params: { student_id: studentId, ...(asOf ? { as_of: asOf } : {}) },
      })
      .then((response) => response.data),
};
