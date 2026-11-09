import client from '@/shared/api/client';
import type {
  CreatePaperSourceRequest,
  QuestionBankPaperItem,
  QuestionBankPaperStatus,
  QuestionBankItem,
  QuestionBankReviewMetrics,
  PaperSourceFullPreviewResponse,
  ParsePaperSourceResponse,
  SearchPaperSourcesRequest,
  UploadedPaperSourceResponse,
  UploadPaperSourceRequest,
  SearchPaperSourcesResponse,
} from '@/types';

const buildUploadPaperSourceFormData = (payload: UploadPaperSourceRequest) => {
  const formData = new FormData();
  formData.append('file', payload.file);
  Object.entries(payload).forEach(([key, value]) => {
    if (key === 'file' || value === undefined || value === null || value === '') return;
    formData.append(key, String(value));
  });
  return formData;
};

export const questionBankApi = {
  listPaperSources: (params?: {
    status?: QuestionBankPaperStatus;
    grade?: string;
    semester?: string;
    subject?: string;
    keyword?: string;
    limit?: number;
  }) =>
    client
      .get<QuestionBankPaperItem[]>('/api/question-bank/paper-sources', { params })
      .then((r) => r.data),

  searchPaperSources: (payload: SearchPaperSourcesRequest) =>
    client
      .post<SearchPaperSourcesResponse>('/api/question-bank/paper-sources/search', payload)
      .then((r) => r.data),

  createPaperSource: (payload: CreatePaperSourceRequest) =>
    client.post<QuestionBankPaperItem>('/api/question-bank/paper-sources', payload).then((r) => r.data),

  uploadPaperSource: (payload: UploadPaperSourceRequest) =>
    client
      .post<UploadedPaperSourceResponse>(
        '/api/question-bank/paper-sources/upload',
        buildUploadPaperSourceFormData(payload),
      )
      .then((r) => r.data),

  updatePaperSourceStatus: (id: number, status: QuestionBankPaperStatus) =>
    client
      .patch<QuestionBankPaperItem>(`/api/question-bank/paper-sources/${id}`, { status })
      .then((r) => r.data),

  reviewPaperSource: (id: number) =>
    client
      .post<QuestionBankPaperItem>(`/api/question-bank/paper-sources/${id}/review`, { use_ai: false })
      .then((r) => r.data),

  parsePaperSource: (id: number) =>
    client
      .post<ParsePaperSourceResponse>(`/api/question-bank/paper-sources/${id}/parse`)
      .then((r) => r.data),

  getPaperSourceFullPreview: (id: number) =>
    client
      .get<PaperSourceFullPreviewResponse>(`/api/question-bank/paper-sources/${id}/full-preview`)
      .then((r) => r.data),

  getReviewMetrics: () =>
    client.get<QuestionBankReviewMetrics>('/api/question-bank/review-metrics').then((r) => r.data),

  listItems: (params?: {
    status?: string;
    subject?: string;
    grade?: string;
    keyword?: string;
    limit?: number;
  }) => client.get<QuestionBankItem[]>('/api/question-bank/items', { params }).then((r) => r.data),

  updateItemStatus: (id: number, status: 'pending' | 'approved' | 'rejected') =>
    client.patch<QuestionBankItem>(`/api/question-bank/items/${id}`, { status }).then((r) => r.data),
};
