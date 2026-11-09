import client from '@/shared/api/client';
import type { SupervisionSummaryResponse } from '@/types';

export const supervisionApi = {
  summary: (studentId: number) =>
    client
      .get<SupervisionSummaryResponse>(`/api/students/${studentId}/supervision-summary`)
      .then((r) => r.data),
};
