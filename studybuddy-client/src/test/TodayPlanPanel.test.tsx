import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { p2Api } from '@/features/p2/api';
import { dailyRecordsApi } from '@/features/growth/dailyRecords';
import TodayPlanPanel, { type TodayLearningTask } from '@/features/chat/components/TodayPlanPanel';
import { useChatStore } from '@/features/chat/store';
import type { DailyLearningRecord, StudyPlan } from '../types';

vi.mock('@/features/p2/api', () => ({
  p2Api: {
    listStudyPlans: vi.fn(),
    updateStudyPlanItem: vi.fn(),
    createStudyPlan: vi.fn(),
    archiveStudyPlan: vi.fn(),
  },
}));

vi.mock('@/features/growth/dailyRecords', () => ({
  dailyRecordsApi: {
    refresh: vi.fn(),
  },
}));

const mockedP2Api = vi.mocked(p2Api);
const mockedDailyRecordsApi = vi.mocked(dailyRecordsApi);

function localDate(offsetDays = 0) {
  const value = new Date();
  value.setDate(value.getDate() + offsetDays);
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(
    value.getDate(),
  ).padStart(2, '0')}`;
}

function plan(overrides: Partial<StudyPlan> = {}): StudyPlan {
  return {
    id: 9,
    student_id: 2,
    title: '今日英语计划',
    focus: null,
    status: 'active',
    planned_date: localDate(),
    is_overdue: false,
    overdue_days: 0,
    reminder_message: null,
    created_by: 2,
    created_at: `${localDate()} 08:00:00`,
    items: [
      { id: 1, title: '背 10 个单词', target: null, minutes: 10, status: 'done', related_tags: [], sort_order: 0, completed_at: null },
      { id: 2, title: '复习一般过去时', target: null, minutes: 15, status: 'todo', related_tags: [], sort_order: 1, completed_at: null },
      { id: 3, title: '完成阅读练习', target: null, minutes: 20, status: 'todo', related_tags: [], sort_order: 2, completed_at: null },
    ],
    ...overrides,
  };
}

function record(overrides: Partial<DailyLearningRecord> = {}): DailyLearningRecord {
  return {
    id: 7,
    student_id: 2,
    record_date: localDate(),
    facts_snapshot: {
      student_id: 2,
      record_date: localDate(),
      period_start: null,
      period_end: null,
      timezone: 'Asia/Shanghai',
      evidence: [{ source_type: 'exam_record', source_id: 3, version: 1, tier: 'verified', title: '数学单元测验' }],
      pending_tasks: [{ plan_title: '今日英语计划', item_title: '完成阅读练习' }],
      self_reported_duration_minutes: 0,
      has_verified_evidence: true,
    },
    summary_text: '今天完成了数学单元测验。',
    evidence_hash: 'hash',
    generation_status: 'ready',
    summary_source: 'ai',
    checkin_status: null,
    checkin_response: null,
    checked_in_at: null,
    generated_at: null,
    finalized_at: null,
    created_at: `${localDate()} 08:00:00`,
    updated_at: `${localDate()} 20:00:00`,
    ...overrides,
  };
}

const baseProps = {
  studentId: 2,
  mode: 'today' as const,
  learningPrompt: '继续今日英语计划',
  onStartLearning: vi.fn<(task: TodayLearningTask, prompt: string) => void>(),
  onReturnToday: vi.fn(),
  onTaskCompleted: vi.fn(),
};

function renderPanel(overrides: Partial<React.ComponentProps<typeof TodayPlanPanel>> = {}) {
  return render(<TodayPlanPanel {...baseProps} {...overrides} />);
}

describe('TodayPlanPanel', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    mockedP2Api.listStudyPlans.mockReset();
    mockedP2Api.updateStudyPlanItem.mockReset();
    mockedP2Api.archiveStudyPlan.mockReset();
    mockedDailyRecordsApi.refresh.mockReset();
    mockedP2Api.listStudyPlans.mockResolvedValue([plan()]);
    mockedP2Api.updateStudyPlanItem.mockResolvedValue(plan().items[1]);
    mockedDailyRecordsApi.refresh.mockRejectedValue({ response: { status: 404 } });
  });

  it('全部完成后可打开总结抽屉查看摘要并继续聊聊', async () => {
    mockedP2Api.listStudyPlans.mockResolvedValue([plan({
      status: 'completed',
      items: plan().items.map((item) => ({ ...item, status: 'done' as const })),
    })]);
    mockedDailyRecordsApi.refresh.mockResolvedValue(record());
    const onContinueConversation = vi.fn();
    renderPanel({ onContinueConversation });

    expect(await screen.findByText('今天的任务做完了')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '今日学习总结' }));
    expect(await screen.findByText('今天完成了数学单元测验。')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '继续聊聊' }));
    expect(onContinueConversation).toHaveBeenCalledOnce();
  });

  it('部分完成时可在总结抽屉看到到目前为止摘要和剩余数量', async () => {
    mockedDailyRecordsApi.refresh.mockResolvedValue(record({ summary_text: '今天到目前为止完成了数学单元测验。' }));
    renderPanel();

    expect(await screen.findByRole('button', { name: '任务列表' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '今日学习总结' }));
    expect(await screen.findByText('今天到目前为止')).toBeInTheDocument();
    expect(screen.getByText('今天到目前为止完成了数学单元测验。')).toBeInTheDocument();
    expect(screen.getByText('还剩 2 项任务')).toBeInTheDocument();
  });

  it('没有每日记录时不阻塞任务栏，总结抽屉显示温和空态', async () => {
    renderPanel();

    expect(await screen.findByText('复习一般过去时')).toBeInTheDocument();
    expect(screen.getByText('继续学习')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '今日学习总结' }));
    expect(await screen.findByText('今天暂时没有新的学习记录')).toBeInTheDocument();
  });

  it('摘要生成中显示骨架，失败时用事实摘要兜底且不写已掌握', async () => {
    mockedDailyRecordsApi.refresh.mockResolvedValueOnce(record({ generation_status: 'generating', summary_text: null }));
    const { unmount } = renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: '今日学习总结' }));
    expect(await screen.findByLabelText('今日学习摘要加载中')).toBeInTheDocument();
    expect(document.querySelector('.sb-daily-recap-skeleton')).toBeInTheDocument();

    unmount();
    mockedDailyRecordsApi.refresh.mockResolvedValueOnce(record({ generation_status: 'failed', summary_text: null }));
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: '今日学习总结' }));
    expect(await screen.findByText(/数学单元测验/)).toBeInTheDocument();
    expect(screen.queryByText(/已掌握/)).not.toBeInTheDocument();
  });

  it('Today 顶部栏展示当前任务和继续学习', async () => {
    const { container } = renderPanel();

    const dockBar = await screen.findByRole('button', { name: '任务列表' });
    expect(dockBar).toBeInTheDocument();
    expect(container.querySelector('.sb-learning-dock-current-title')).toHaveTextContent('复习一般过去时');
    expect(container.querySelector('.sb-learning-dock-current-meta')).toHaveTextContent('今日英语计划');
    expect(container.querySelector('.sb-task-dock-progress')).toHaveTextContent('2/3');
    expect(screen.getByText('继续学习')).toBeInTheDocument();
    expect(mockedP2Api.listStudyPlans).toHaveBeenCalledWith(2, '');
  });

  it('点击继续学习交给页面切换视图但不完成任务', async () => {
    const onStartLearning = vi.fn();
    renderPanel({ onStartLearning });

    fireEvent.click(await screen.findByRole('button', { name: '继续学习' }));

    expect(onStartLearning).toHaveBeenCalledWith(
      expect.objectContaining({
        planId: 9,
        planTitle: '今日英语计划',
        item: expect.objectContaining({ id: 2 }),
      }),
      '继续今日英语计划',
    );
    expect(mockedP2Api.updateStudyPlanItem).not.toHaveBeenCalled();
  });

  it('学习状态只用小箭头返回并保持任务栏单行结构', async () => {
    renderPanel({ mode: 'learning' });

    const back = await screen.findByRole('button', { name: '返回今天' });
    expect(back).toHaveTextContent('');
    expect(document.querySelector('.sb-learning-dock-current-title')).toHaveTextContent('复习一般过去时');
    expect(document.querySelector('.sb-learning-dock-actions')).toBeInTheDocument();
  });

  it('点击任务列表打开状态抽屉', async () => {
    renderPanel({ mode: 'learning' });

    fireEvent.click(await screen.findByRole('button', { name: '任务列表' }));

    expect(await screen.findByRole('dialog', { name: /今天计划/ })).toBeInTheDocument();
    expect(screen.getByText('背 10 个单词')).toBeInTheDocument();
    expect(screen.getByText('当前')).toBeInTheDocument();
    expect(screen.getByText('待开始')).toBeInTheDocument();
  });

  it('today 模式下通过任务列表切换当前任务', async () => {
    const onStartLearning = vi.fn();
    // today 模式顶部栏有任务列表按钮，切换任务需进 learning 模式的任务列表
    renderPanel({ mode: 'learning', onStartLearning });
    fireEvent.click(await screen.findByRole('button', { name: '任务列表' }));
    fireEvent.click(await screen.findByRole('button', { name: '切换到任务 完成阅读练习' }));

    fireEvent.click(screen.getByRole('button', { name: '完成学习' }).closest('section')!.querySelector('.sb-learning-dock-back')!);
    // 切换后 learning 模式标题更新
    expect(document.querySelector('.sb-learning-dock-current-title')).toHaveTextContent('完成阅读练习');
  });

  it('学习中的任务列表可以确认后把单项移出今天', async () => {
    const skippedPlan = plan({
      items: [
        plan().items[0],
        plan().items[1],
        { ...plan().items[2], status: 'skipped' },
      ],
    });
    mockedP2Api.listStudyPlans.mockResolvedValueOnce([plan()]).mockResolvedValueOnce([skippedPlan]);
    mockedP2Api.updateStudyPlanItem.mockResolvedValue(skippedPlan.items[2]);
    renderPanel({ mode: 'learning' });

    fireEvent.click(await screen.findByRole('button', { name: '任务列表' }));
    fireEvent.click(screen.getByRole('button', { name: '移出今天 完成阅读练习' }));
    expect(await screen.findByText('移出这个任务？')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认移出' }));

    await waitFor(() => expect(mockedP2Api.updateStudyPlanItem).toHaveBeenCalledWith(3, 'skipped'));
  });

  it('learning 模式归档计划后返回空态', async () => {
    mockedP2Api.listStudyPlans.mockResolvedValueOnce([plan()]).mockResolvedValueOnce([]);
    mockedP2Api.archiveStudyPlan.mockResolvedValue(plan({ status: 'archived' }));
    renderPanel({ mode: 'learning' });

    // learning 模式下打开任务列表，通过 Drawer 归档
    fireEvent.click(await screen.findByRole('button', { name: '任务列表' }));
    // 任务列表 Drawer 里的归档入口
    const archiveBtn = await screen.findByRole('button', { name: '删除计划 今日英语计划' });
    fireEvent.click(archiveBtn);
    expect(await screen.findByText('删除这个计划？')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }));

    await waitFor(() => expect(mockedP2Api.archiveStudyPlan).toHaveBeenCalledWith(9));
  });

  it('最后一项完成后显示今天的任务做完了而不是空计划', async () => {
    const lastTodo = plan({
      items: [
        { id: 2, title: '复习一般过去时', target: null, minutes: 15, status: 'todo', related_tags: [], sort_order: 0, completed_at: null },
      ],
    });
    const completed = plan({
      status: 'completed',
      items: [
        { id: 2, title: '复习一般过去时', target: null, minutes: 15, status: 'done', related_tags: [], sort_order: 0, completed_at: `${localDate()} 20:00:00` },
      ],
    });
    mockedP2Api.listStudyPlans.mockResolvedValueOnce([lastTodo]).mockResolvedValueOnce([completed]);
    mockedDailyRecordsApi.refresh.mockResolvedValue(record());
    const onTaskCompleted = vi.fn();
    renderPanel({ mode: 'learning', onTaskCompleted });

    fireEvent.click(await screen.findByRole('button', { name: '完成学习' }));

    // P0 门禁：先弹证据输入框，无证据不请求 PATCH
    const textarea = await screen.findByPlaceholderText(/背出了不规则动词的过去式/);
    fireEvent.change(textarea, { target: { value: '背出了动词过去式' } });
    fireEvent.click(await screen.findByRole('button', { name: '确认完成' }));

    await waitFor(() => expect(mockedP2Api.updateStudyPlanItem).toHaveBeenCalledWith(2, 'done', '背出了动词过去式'));
    await waitFor(() => expect(mockedDailyRecordsApi.refresh).toHaveBeenCalledWith(2));
    expect(await screen.findByText('今天的任务做完了')).toBeInTheDocument();
    expect(screen.queryByText('今天还没有计划')).not.toBeInTheDocument();
    expect(onTaskCompleted).toHaveBeenCalledOnce();
  });

  it('完成态可再排一份计划', async () => {
    const completed = plan({
      status: 'completed',
      items: [
        { id: 2, title: '复习一般过去时', target: null, minutes: 15, status: 'done', related_tags: [], sort_order: 0, completed_at: `${localDate()} 20:00:00` },
      ],
    });
    mockedP2Api.listStudyPlans.mockResolvedValue([completed]);
    mockedDailyRecordsApi.refresh.mockResolvedValue(record());
    const onAskAiToPlan = vi.fn();
    renderPanel({ onAskAiToPlan });

    expect(await screen.findByText('今天的任务做完了')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '再排一份计划' }));
    expect(onAskAiToPlan).toHaveBeenCalledOnce();
  });

  it('没有今日计划时显示空态顶部栏', async () => {
    mockedP2Api.listStudyPlans.mockResolvedValue([]);
    const onAskAiToPlan = vi.fn();
    const conversationActions = <button aria-label="对话选项">对话选项</button>;
    const { container } = renderPanel({ onAskAiToPlan, conversationActions });

    expect(await screen.findByText('今天还没有计划')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '对话选项' })).toBeInTheDocument();
    expect(container.querySelector('.sb-learning-dock--empty')).toBeInTheDocument();
    expect(container.querySelector('.sb-learning-dock-current-title')).toHaveTextContent('今天还没有计划');
    // 主按钮交给 AI 制定计划
    fireEvent.click(screen.getByRole('button', { name: '让 AI 帮我定' }));
    expect(onAskAiToPlan).toHaveBeenCalledOnce();
    // 任务列表入口仍可进抽屉手动添加
    fireEvent.click(screen.getByRole('button', { name: '任务列表' }));
    expect(await screen.findByRole('dialog', { name: /今天计划/ })).toBeInTheDocument();
  });

  it('未来计划不冒充今日任务', async () => {
    mockedP2Api.listStudyPlans.mockResolvedValue([plan({ planned_date: localDate(1) })]);
    renderPanel();

    expect(await screen.findByText('今天还没有计划')).toBeInTheDocument();
    expect(screen.queryByText('复习一般过去时')).not.toBeInTheDocument();
  });

  it('AI 经对话新建计划后（planVersion 自增）自动刷新计划列表，无需手动刷新', async () => {
    mockedP2Api.listStudyPlans.mockResolvedValue([]);
    renderPanel();
    expect(await screen.findByText('今天还没有计划')).toBeInTheDocument();

    // 模拟 AI 经对话调用 create_study_plan：store planVersion 自增触发刷新
    mockedP2Api.listStudyPlans.mockResolvedValueOnce([plan()]);
    useChatStore.setState((s) => ({ planVersion: s.planVersion + 1 }));

    expect(await screen.findByText('复习一般过去时')).toBeInTheDocument();
  });

  it('任务列表手动选任务进入对应 task session（调 onStartLearning，不预填 prompt）', async () => {
    const onStartLearning = vi.fn();
    renderPanel({ mode: 'learning', onStartLearning });

    fireEvent.click(await screen.findByRole('button', { name: '任务列表' }));
    fireEvent.click(await screen.findByRole('button', { name: '切换到任务 完成阅读练习' }));

    await waitFor(() =>
      expect(onStartLearning).toHaveBeenCalledWith(
        expect.objectContaining({
          planId: 9,
          planTitle: '今日英语计划',
          item: expect.objectContaining({ id: 3, title: '完成阅读练习' }),
        }),
        '',
      ),
    );
  });

  it('首次请求 401 时延迟重试，重试成功不闪错误态', async () => {
    mockedP2Api.listStudyPlans
      .mockRejectedValueOnce({ response: { status: 401 } })
      .mockResolvedValueOnce([plan()]);
    renderPanel();

    await waitFor(() => expect(mockedP2Api.listStudyPlans).toHaveBeenCalledTimes(1));
    // 401 后保持 loading，不显示错误态也不显示空态
    expect(screen.queryByText('暂时没拿到今日计划')).not.toBeInTheDocument();
    expect(screen.queryByText('今天还没有计划')).not.toBeInTheDocument();
    // 延迟重试后成功显示任务
    expect(await screen.findByText('复习一般过去时', undefined, { timeout: 3000 })).toBeInTheDocument();
    expect(mockedP2Api.listStudyPlans).toHaveBeenCalledTimes(2);
  });

  it('404 视为空数据显示空态，不显示错误态', async () => {
    mockedP2Api.listStudyPlans.mockRejectedValue({ response: { status: 404 } });
    renderPanel();

    expect(await screen.findByText('今天还没有计划')).toBeInTheDocument();
    expect(screen.queryByText('暂时没拿到今日计划')).not.toBeInTheDocument();
  });

  it('task session 激活但计划逾期时，顶部显示当前任务而非空态', async () => {
    // 跨天后计划逾期（planned_date=昨天），但 task session 仍激活（selectedItemId 指向逾期任务）
    const overduePlan = plan({
      id: 10,
      title: '昨日数学计划',
      planned_date: localDate(-1),
      is_overdue: true,
      overdue_days: 1,
      items: [
        { id: 20, title: '一次函数图像补漏', target: null, minutes: 20, status: 'todo', related_tags: [], sort_order: 0, completed_at: null },
      ],
    });
    mockedP2Api.listStudyPlans.mockResolvedValue([overduePlan]);
    // 模拟 task session 激活：selectedItemId 持久化指向逾期计划的 todo 任务
    localStorage.setItem('sb-selected-item-2', '20');
    renderPanel({ mode: 'learning' });

    // 顶部应显示当前任务标题 + 完成学习，而非「今天还没有计划」空态
    expect(await screen.findByText('一次函数图像补漏')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '完成学习' })).toBeInTheDocument();
    expect(screen.queryByText('今天还没有计划')).not.toBeInTheDocument();
  });

  it('500 错误后自动延迟重试恢复，不卡 error 态', async () => {
    // withRetry 重试 3 次 500（attempt 0/1/2）后仍失败 -> errorRetry 兜底重试恢复
    mockedP2Api.listStudyPlans
      .mockRejectedValueOnce({ response: { status: 500 } })
      .mockRejectedValueOnce({ response: { status: 500 } })
      .mockRejectedValueOnce({ response: { status: 500 } })
      .mockResolvedValueOnce([plan()]);
    renderPanel();

    expect(await screen.findByText('复习一般过去时', undefined, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.queryByText('暂时没拿到今日计划')).not.toBeInTheDocument();
  });
});
