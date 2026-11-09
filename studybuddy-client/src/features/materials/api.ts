import client from '@/shared/api/client';
import { API_TIMEOUTS } from '@/shared/constants';
import type { MaterialExtraction, MaterialItem, MaterialUploadResponse } from '@/types';
import { normalizeMaterialTags } from '@/shared/utils/material';

export const materialApi = {
  upload: (file: File, name: string, type: string, knowledgeTags: string[] = []) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('name', name);
    formData.append('type', type);
    formData.append('knowledge_tags', JSON.stringify(normalizeMaterialTags(knowledgeTags)));
    // 上传只落库+去重，不再同步识别；用文件上传超时档即可
    return client
      .post<MaterialUploadResponse>('/api/material/upload', formData, {
        timeout: API_TIMEOUTS.PHOTO_UPLOAD,
      })
      .then((r) => r.data);
  },
  list: (source?: string, type?: string) =>
    client.get<MaterialItem[]>('/api/material', { params: { source, type } }).then((r) => r.data),
  previewUrl: (id: number) =>
    client
      .get<{ url: string; ext: string; name: string }>(`/api/material/${id}/preview-url`)
      .then((r) => r.data),
  recognize: (id: number) =>
    client
      .post<MaterialExtraction>(`/api/material/${id}/recognize`, undefined, {
        timeout: API_TIMEOUTS.VISION_PARSE,
      })
      .then((r) => r.data),
  getExtraction: (id: number) =>
    client.get<MaterialExtraction>(`/api/material/${id}/extraction`).then((r) => r.data),
  confirmExtraction: (id: number, confirmedMarkdown: string) =>
    client
      .put<MaterialExtraction>(`/api/material/${id}/extraction/confirm`, {
        confirmed_markdown: confirmedMarkdown,
      })
      .then((r) => r.data),
  delete: (id: number) => client.delete(`/api/material/${id}`).then((r) => r.data),
};
// agg-1 materials
