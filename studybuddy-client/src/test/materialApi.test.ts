import { beforeEach, describe, expect, it, vi } from 'vitest';

const { postMock, getMock, deleteMock } = vi.hoisted(() => ({
  postMock: vi.fn(),
  getMock: vi.fn(),
  deleteMock: vi.fn(),
}));

vi.mock('@/shared/api/client', () => ({
  default: {
    post: postMock,
    get: getMock,
    delete: deleteMock,
  },
}));

import { materialApi } from '@/features/materials/api';
import { API_TIMEOUTS } from '@/shared/constants';

describe('materialApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('上传素材时把知识点标签作为 JSON 数组写入 FormData', async () => {
    const file = new File(['fakepng'], 'card.png', { type: 'image/png' });
    postMock.mockResolvedValue({
      data: {
        material_id: 7,
        name: 'U5单词卡',
        type: 'image',
        source: 'teacher',
        cos_key: 'materials/card.png',
        uploaded_by: '老师',
        created_at: '2026-07-02T12:00:00',
      },
    });

    const result = await materialApi.upload(file, 'U5单词卡', 'image', [
      ' 过去时 ',
      '',
      '过去时',
      '动词',
    ]);

    expect(result.material_id).toBe(7);
    expect(postMock).toHaveBeenCalledTimes(1);

    const [url, body, config] = postMock.mock.calls[0];
    expect(url).toBe('/api/material/upload');
    expect(config).toEqual({ timeout: API_TIMEOUTS.PHOTO_UPLOAD });

    const formData = body as FormData;
    expect(formData.get('file')).toBe(file);
    expect(formData.get('name')).toBe('U5单词卡');
    expect(formData.get('type')).toBe('image');
    expect(formData.get('knowledge_tags')).toBe(JSON.stringify(['过去时', '动词']));
  });

  it('识别素材 Markdown 使用视觉解析超时配置', async () => {
    postMock.mockResolvedValue({
      data: {
        material_id: 7,
        name: 'U5单词卡',
        recognition_status: 'needs_review',
        recognized_markdown: '### U5 单词',
      },
    });

    await materialApi.recognize(7);

    expect(postMock).toHaveBeenCalledWith('/api/material/7/recognize', undefined, {
      timeout: API_TIMEOUTS.VISION_PARSE,
    });
  });
});
// agg-1 P2
