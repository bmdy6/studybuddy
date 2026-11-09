import client from '@/shared/api/client';
import type { DailyCheckinStatus, CheckinChoiceKey } from '@/types';

export const dailyCheckinApi = {
  getStatus: (studentId?: number) =>
    client
      .get<DailyCheckinStatus>('/api/daily-checkin', {
        params: studentId ? { student_id: studentId } : undefined,
      })
      .then((response) => response.data),

  submit: (choice: CheckinChoiceKey) =>
    client
      .post<DailyCheckinStatus>('/api/daily-checkin', { choice })
      .then((response) => response.data),
};
