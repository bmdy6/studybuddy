import client from '@/shared/api/client';
import { API_TIMEOUTS } from '@/shared/constants';
import type {
  BatchItem,
  ConfirmAnswerReviewRequest,
  CreateBatchRequest,
  ParseResult,
  PhotoAnswerReviewState,
} from '@/types';

/** 错题导入 API：拍照建批次→上传照片→合成PDF→视觉解析（判分由 agent 工具完成，前端不直接调） */
export const examBatchApi = {
  /** 创建考试批次（上传照片前先建批次） */
  createBatch: (req: CreateBatchRequest) =>
    client.post<BatchItem>('/api/exam-batches', req).then((r) => r.data),

  /** 清理上传失败留下的空批次；已有照片/解析结果时后端会拒绝。 */
  deleteEmptyBatch: (batchId: number) =>
    client.delete<void>(`/api/exam-batches/${batchId}`).then((r) => r.data),

  /** 批量上传照片到批次（存子文件夹+重命名+进素材库）。
   *  接受 RcFile（antd Upload 的 originFileObj 类型，继承自 File）或 File。 */
  uploadPhotos: (batchId: number, files: File[], pageType = '试卷') => {
    const formData = new FormData();
    files.forEach((f) => formData.append('files', f));
    formData.append('page_type', pageType);
    return client
      .post<BatchItem>(`/api/exam-batches/${batchId}/photos`, formData, {
        timeout: API_TIMEOUTS.PHOTO_UPLOAD,
      })
      .then((r) => r.data);
  },

  /** img2pdf 合成 PDF（留档预览用，失败不阻塞解析） */
  synthesize: (batchId: number) =>
    client
      .post<{ pdf_ref: string | null; saved: boolean }>(`/api/exam-batches/${batchId}/synthesize`)
      .then((r) => r.data),

  /** MiMo 视觉解析批次照片，返回每题作答 */
  parse: (batchId: number) =>
    client
      .post<ParseResult>(`/api/exam-batches/${batchId}/parse`, undefined, {
        timeout: API_TIMEOUTS.VISION_PARSE,
      })
      .then((r) => r.data),

  /** 读取拍题逐题作答核对状态。 */
  getAnswerReview: (batchId: number) =>
    client
      .get<PhotoAnswerReviewState>(`/api/exam-batches/${batchId}/answer-review`)
      .then((r) => r.data),

  /** 确认或修正拍题识别出的逐题作答。 */
  confirmAnswerReview: (batchId: number, req: ConfirmAnswerReviewRequest) =>
    client
      .post<PhotoAnswerReviewState>(`/api/exam-batches/${batchId}/answer-review/confirm`, req)
      .then((r) => r.data),
};
