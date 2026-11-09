import type { QuestionBankPaperStatus, SearchPaperSourcesRequest } from '@/types';

export const STATUS_META: Record<QuestionBankPaperStatus, { color: string; label: string }> = {
  candidate: { color: 'processing', label: '待确认' },
  confirmed: { color: 'green', label: '可信来源' },
  rejected: { color: 'default', label: '不合适' },
  internal_style: { color: 'gold', label: '风格参考' },
};

export const RISK_META: Record<string, { color: string; label: string }> = {
  low: { color: 'green', label: '低风险' },
  medium: { color: 'orange', label: '需确认' },
  high: { color: 'red', label: '高风险' },
};

export const ADAPTER_META: Record<string, { color: string; label: string }> = {
  yidianedu: { color: 'blue', label: '一点升学' },
  education_bureau: { color: 'green', label: '教育局' },
  school_official: { color: 'cyan', label: '学校官网' },
  official_edu: { color: 'green', label: '官方教育' },
  public_pdf: { color: 'purple', label: '公开 PDF' },
  web_search: { color: 'default', label: '网页搜索' },
  manual_entry: { color: 'default', label: '人工录入' },
  manual_search: { color: 'default', label: '人工搜索' },
  manual_upload: { color: 'geekblue', label: '人工上传' },
};

export const SOURCE_ADAPTER_OPTIONS = [
  { value: 'school_official', label: ADAPTER_META.school_official.label },
  { value: 'education_bureau', label: ADAPTER_META.education_bureau.label },
  { value: 'official_edu', label: ADAPTER_META.official_edu.label },
  { value: 'public_pdf', label: ADAPTER_META.public_pdf.label },
  { value: 'web_search', label: ADAPTER_META.web_search.label },
  { value: 'manual_entry', label: ADAPTER_META.manual_entry.label },
];

export const REVIEW_META: Record<string, { color: string; label: string }> = {
  formal_ready: { color: 'green', label: '可解析' },
  style_only: { color: 'gold', label: '风格参考' },
  needs_manual: { color: 'orange', label: '需复核' },
  reject: { color: 'red', label: '不入库' },
};

export const ITEM_STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: 'processing', label: '待确认' },
  approved: { color: 'green', label: '已入库' },
  rejected: { color: 'default', label: '已拒绝' },
};

export const DEFAULT_SEARCH: SearchPaperSourcesRequest = {
  province: '江苏',
  city: '苏州',
  district: '苏州工业园区',
  school: '示例学校',
  grade: '八年级',
  semester: '上册',
  subject: '数学',
  exam_type: '期中',
  limit: 8,
};

export const formatRate = (value: number | null) =>
  value === null ? '样本不足' : `${Math.round(value * 100)}%`;
