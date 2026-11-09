import client from '@/shared/api/client';
import type { DailyLearningRecord } from '@/types';

export const dailyRecordsApi = {
  refresh: (studentId?: number) =>
    client
      .post<DailyLearningRecord>('/api/daily-records/refresh', undefined, {
        params: studentId ? { student_id: studentId } : undefined,
      })
      .then((response) => response.data),

  list: (studentId: number, startDate: string, endDate: string) =>
    client
      .get<DailyLearningRecord[]>('/api/daily-records', {
        params: { student_id: studentId, start_date: startDate, end_date: endDate },
      })
      .then((response) => response.data),

  getByDate: (studentId: number, recordDate: string) =>
    client
      .get<DailyLearningRecord>('/api/daily-records', {
        params: { student_id: studentId, date: recordDate },
      })
      .then((response) => response.data),
};
