import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockList, mockGetByDate, mockNotes } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockGetByDate: vi.fn(),
  mockNotes: vi.fn(),
}));

vi.mock('@/features/growth/dailyRecords', () => ({ dailyRecordsApi: { list: mockList, getByDate: mockGetByDate } }));
vi.mock('@/features/note/api', () => ({ noteApi: { list: mockNotes } }));
vi.mock('@/features/auth/store', () => ({
  useAuthStore: () => ({ role: 'student', userId: 2, activeChildId: null }),
  getActiveStudentId: () => 2,
}));

import DailyRecordsPage from '@/features/growth/pages/DailyRecordsPage';

const record = {
  id: 7,
  student_id: 2,
  record_date: '2026-07-17',
  facts_snapshot: {
    student_id: 2,
    record_date: '2026-07-17',
    period_start: null,
    period_end: null,
    timezone: 'Asia/Shanghai',
    evidence: [{ source_type: 'exam_record', source_id: 3, version: 1, tier: 'verified', title: '数学单元测验' }],
    pending_tasks: [{ plan_title: '今日计划', item_title: '整理错题' }],
    self_reported_duration_minutes: 42,
    has_verified_evidence: true,
  },
  summary_text: '完成数学单元测验，整理了错题。'.repeat(12),
  evidence_hash: 'hash',
  generation_status: 'ready',
  summary_source: 'ai',
  checkin_status: null,
  checkin_response: null,
  checked_in_at: null,
  generated_at: '2026-07-17T21:00:00Z',
  finalized_at: null,
  created_at: '2026-07-17T21:00:00Z',
  updated_at: '2026-07-17T21:00:00Z',
};

function renderPage() {
  return render(<MemoryRouter><DailyRecordsPage /></MemoryRouter>);
}

describe('DailyRecordsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue([record]);
    mockGetByDate.mockResolvedValue(record);
    mockNotes.mockResolvedValue([
      { id: 9, student_id: 2, category: '每日回顾', source: '每日回顾', title: '历史回顾', content: '昨天手写的回顾', created_at: '2026-07-10T12:00:00Z' },
    ]);
  });

  it('展示每日记录、证据来源、未完成项和长摘要折叠', async () => {
    renderPage();

    expect(await screen.findByText('每日学习记录')).toBeInTheDocument();
    expect(screen.getByText('AI 自动整理')).toBeInTheDocument();
    expect(screen.getByText('数学单元测验')).toBeInTheDocument();
    expect(screen.getByText('整理错题')).toBeInTheDocument();
    expect(screen.getByText('真实时长 42 分钟')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '展开摘要' })).toBeInTheDocument();
    expect(screen.getAllByText('历史回顾').length).toBeGreaterThan(0);
  });

  it('支持日期切换并在无记录时显示空态', async () => {
    mockGetByDate.mockRejectedValueOnce({ response: { status: 404 } });
    renderPage();

    const dateInput = await screen.findByLabelText('选择日期');
    fireEvent.input(dateInput, { target: { value: '2026-07-16' } });
    await waitFor(() => expect(mockGetByDate).toHaveBeenCalledWith(2, '2026-07-16'));
    expect(await screen.findByText('这一天还没有自动学习记录')).toBeInTheDocument();
  });

  it('接口失败时给出可重试错误态', async () => {
    mockList.mockRejectedValueOnce(new Error('network'));
    renderPage();
    expect(await screen.findByText('每日记录暂时加载失败')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
    expect(mockList).toHaveBeenCalledTimes(2);
  });

  it('权限不足时明确提示，不把后端错误细节暴露给用户', async () => {
    mockList.mockRejectedValueOnce({ response: { status: 403 } });
    renderPage();
    expect(await screen.findByText('没有权限查看这位学生的学习记录')).toBeInTheDocument();
  });

  it('时间线为空时仍展示成功查询到的历史日期详情', async () => {
    mockList.mockResolvedValueOnce([]);
    renderPage();
    const dateInput = await screen.findByLabelText('选择日期');
    fireEvent.input(dateInput, { target: { value: '2026-06-01' } });
    expect(await screen.findByText('数学单元测验')).toBeInTheDocument();
  });

  it('未记录时长时不显示虚假的零分钟', async () => {
    mockList.mockResolvedValueOnce([{ ...record, facts_snapshot: { ...record.facts_snapshot, self_reported_duration_minutes: 0 } }]);
    renderPage();
    expect(await screen.findByText('真实时长未记录')).toBeInTheDocument();
    expect(screen.queryByText('真实时长 0 分钟')).not.toBeInTheDocument();
  });
});
