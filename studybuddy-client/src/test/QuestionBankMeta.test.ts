import { describe, expect, it } from 'vitest';
import { DEFAULT_SEARCH, formatRate, STATUS_META } from '@/features/teacher/questionBankMeta';

describe('questionBankMeta', () => {
  it('导出题库页面默认搜索条件和状态文案', () => {
    expect(DEFAULT_SEARCH).toMatchObject({
      province: '江苏',
      city: '苏州',
      grade: '八年级',
      semester: '上册',
      subject: '数学',
    });
    expect(STATUS_META.candidate.label).toBe('待确认');
  });

  it('格式化 AI 审核通过率', () => {
    expect(formatRate(null)).toBe('样本不足');
    expect(formatRate(0.126)).toBe('13%');
  });
});
