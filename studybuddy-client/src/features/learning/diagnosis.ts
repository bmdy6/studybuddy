import client from '@/shared/api/client';
import type { DiagnosisResponse } from '@/types';

export const diagnosisApi = {
  get: (studentId: number, topN = 10) =>
    client
      .get<DiagnosisResponse>(`/api/diagnosis/${studentId}`, { params: { top_n: topN } })
      .then((r) => r.data),
};
