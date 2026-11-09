import client from '@/shared/api/client';
import { DEFAULT_PENDING_GRADE_LIMIT } from '@/shared/constants';
import type {
  ExamRecordResult,
  SubmitRequest,
  SubmitResponse,
  PendingGradeItem,
  GradeManualResponse,
} from '@/types';

export const answerApi = {
  submit: (examId: number, data: SubmitRequest) =>
    client.post<SubmitResponse>(`/api/exam/${examId}/submit`, data).then((r) => r.data),
  result: (recordId: number) =>
    client.get<ExamRecordResult>(`/api/exam-record/${recordId}/result`).then((r) => r.data),
  pending: (limit = DEFAULT_PENDING_GRADE_LIMIT) =>
    client
      .get<PendingGradeItem[]>('/api/answers/pending', { params: { limit } })
      .then((r) => r.data),
  grade: (answerId: number, manualScore: number, manualComment: string) =>
    client
      .post<GradeManualResponse>(`/api/answer/${answerId}/grade`, {
        manual_score: manualScore,
        manual_comment: manualComment,
      })
      .then((r) => r.data),
};
