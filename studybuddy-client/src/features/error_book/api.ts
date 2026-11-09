import client from '@/shared/api/client';
import type { ErrorSubjectGroup } from '@/types';

/**
 * 错题本：学科 → 题型两级分组。
 * 学生查自己（后端从 token 推断），老师传 studentId 查指定学生。
 */
export const errorBookApi = {
  list: (studentId?: number): Promise<ErrorSubjectGroup[]> =>
    client
      .get<ErrorSubjectGroup[]>('/api/error-book/by-subject', {
        params: { student_id: studentId },
      })
      .then((r) => r.data),
};
