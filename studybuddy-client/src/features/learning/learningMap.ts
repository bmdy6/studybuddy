import client from '@/shared/api/client';
import type { LearningMapResponse } from '@/types';

export const learningMapApi = {
  get: (studentId: number, limit = 30) =>
    client
      .get<LearningMapResponse>(`/api/students/${studentId}/learning-map`, { params: { limit } })
      .then((r) => r.data),
};
