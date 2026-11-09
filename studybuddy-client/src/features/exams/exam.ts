import client from '@/shared/api/client';
import type {
  ExamListItem,
  ExamDetail,
  StartExamResponse,
  ExamAssignmentItem,
  ExamAssignmentRequest,
} from '@/types';

export const examApi = {
  // ★ 后端返回 ExamListItem[]（直接数组），非 {exams:[]}
  list: () => client.get<ExamListItem[]>('/api/exam').then((r) => r.data),
  detail: (examId: number) => client.get<ExamDetail>(`/api/exam/${examId}`).then((r) => r.data),
  // ★ 后端返回 {exam_record_id, exam_id, status}
  start: (examId: number) =>
    client.post<StartExamResponse>(`/api/exam/${examId}/start`).then((r) => r.data),
  assign: (examId: number, data: ExamAssignmentRequest) =>
    client.post<ExamAssignmentItem[]>(`/api/exam/${examId}/assignments`, data).then((r) => r.data),
  assignments: (examId: number) =>
    client.get<ExamAssignmentItem[]>(`/api/exam/${examId}/assignments`).then((r) => r.data),
};
