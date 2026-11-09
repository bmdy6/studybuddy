import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { familyGoalApi } from '@/features/family_goal/api';
import TodayFamilyTasks from '@/features/family_goal/components/TodayFamilyTasks';
import type { FamilyRewardRecord, FamilyRewardSummary, FamilyTodayTask } from '@/types';

vi.mock('@/features/family_goal/api', async () => {
  const actual = await vi.importActual<typeof import('@/features/family_goal/api')>(
    '@/features/family_goal/api',
  );
  return {
    ...actual,
    familyGoalApi: {
      todayTasks: vi.fn(),
      rewards: vi.fn(),
      submitOccurrence: vi.fn(),
      uploadEvidence: vi.fn(),
      createGoal: vi.fn(),
      createTask: vi.fn(),
      listGoals: vi.fn(),
      parentBound: vi.fn(),
      rewardTotalOf: actual.familyGoalApi.rewardTotalOf,
    },
  };
});

const mockedApi = vi.mocked(familyGoalApi);

function task(overrides: Partial<FamilyTodayTask> = {}): FamilyTodayTask {
  return {
    occurrence_id: 11,
    task_id: 21,
    goal_id: 31,
    student_id: 2,
    title: '默写英语单词',
    description: null,
    goal_title: '英语默写',
    repeat_type: 'once',
    status: 'pending',
    occurrence_date: '2026-09-30',
    reward_amount: '5.00',
    submit_note: null,
    reject_reason: null,
    submitted_at: null,
    reviewed_at: null,
    evidence: [],
    ...overrides,
  };
}

function summary(overrides: Partial<FamilyRewardSummary> = {}): FamilyRewardSummary {
  return { student_id: 2, total_amount: '0.00', records: [], ...overrides };
}

function rewardRecord(overrides: Partial<FamilyRewardRecord> = {}): FamilyRewardRecord {
  return {
    id: 1,
    occurrence_id: 11,
    task_title: '默写英语单词',
    goal_title: '英语默写',
    amount: '4.00',
    confirmed_at: '2026-09-01T10:00:00',
    ...overrides,
  };
}

function renderSection() {
  return render(<TodayFamilyTasks studentId={2} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.todayTasks.mockResolvedValue([]);
  mockedApi.rewards.mockResolvedValue(summary());
  mockedApi.parentBound.mockResolvedValue({ parent_bound: true });
});

describe('TodayFamilyTasks', () => {
  it('没有家庭任务时显示引导和累计金额', async () => {
    renderSection();
    expect(await screen.findByText(/还没有家庭任务/)).toBeInTheDocument();
    expect(screen.getByText('新建目标')).toBeInTheDocument();
    expect(screen.getByText(/已攒 ¥0/)).toBeInTheDocument();
  });

  it('展示待完成任务：标题、目标、奖励金额与状态', async () => {
    mockedApi.todayTasks.mockResolvedValue([task()]);
    mockedApi.rewards.mockResolvedValue(summary({ total_amount: '12.50' }));
    renderSection();

    expect(await screen.findByText('默写英语单词')).toBeInTheDocument();
    expect(screen.getByText('英语默写')).toBeInTheDocument();
    expect(screen.getByText('+¥5')).toBeInTheDocument();
    expect(screen.getByText('待完成')).toBeInTheDocument();
    expect(screen.getByText(/已攒 ¥12.50/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /交作业/ })).toBeInTheDocument();
  });

  it('每日任务带「每天」标记', async () => {
    mockedApi.todayTasks.mockResolvedValue([task({ repeat_type: 'daily' })]);
    renderSection();
    expect(await screen.findByText('每天')).toBeInTheDocument();
  });

  it('已驳回显示家长理由并允许重新提交', async () => {
    mockedApi.todayTasks.mockResolvedValue([
      task({ status: 'rejected', reject_reason: '拍糊了，重拍' }),
    ]);
    renderSection();

    expect(await screen.findByText(/家长说：拍糊了，重拍/)).toBeInTheDocument();
    expect(screen.getByText('已驳回')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /重新交/ })).toBeInTheDocument();
  });

  it('已确认只展示状态，不再出现提交按钮', async () => {
    mockedApi.todayTasks.mockResolvedValue([task({ status: 'approved' })]);
    renderSection();

    expect(await screen.findByText('已确认')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /交作业/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /重新交/ })).not.toBeInTheDocument();
  });

  it('待家长确认不再提供提交入口', async () => {
    mockedApi.todayTasks.mockResolvedValue([task({ status: 'submitted', submit_note: '写完了' })]);
    renderSection();

    expect(await screen.findByText('待家长确认')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /交作业/ })).not.toBeInTheDocument();
  });

  it('加载失败显示重试入口', async () => {
    mockedApi.todayTasks.mockRejectedValue(new Error('boom'));
    renderSection();

    expect(await screen.findByText('家庭任务没加载出来')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument();
  });

  it('没绑家长时任务卡片常驻提示并给去绑定入口', async () => {
    mockedApi.parentBound.mockResolvedValue({ parent_bound: false });
    mockedApi.todayTasks.mockResolvedValue([task()]);
    renderSection();

    expect(await screen.findByText('还没绑定家长，暂时没人能确认')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '去绑定' })).toHaveAttribute('href', '#/family');
  });

  it('绑了家长时不显示未绑定提示', async () => {
    mockedApi.todayTasks.mockResolvedValue([task()]);
    renderSection();

    expect(await screen.findByText('默写英语单词')).toBeInTheDocument();
    expect(screen.queryByText(/还没绑定家长/)).not.toBeInTheDocument();
  });

  it('建目标抽屉顶部提示目标没人确认', async () => {
    mockedApi.parentBound.mockResolvedValue({ parent_bound: false });
    mockedApi.todayTasks.mockResolvedValue([task()]);
    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: /新建目标/ }));
    const drawer = await screen.findByRole('dialog');
    expect(within(drawer).getByText('还没绑定家长，建了目标也没人能确认')).toBeInTheDocument();
    expect(within(drawer).getByRole('link', { name: '去绑定' })).toHaveAttribute('href', '#/family');
  });

  it('点「已攒」打开奖励明细抽屉，按时间倒序列出每一笔', async () => {
    mockedApi.rewards.mockResolvedValue(
      summary({
        total_amount: '6.00',
        records: [
          rewardRecord({
            id: 2,
            occurrence_id: 12,
            task_title: '整理书桌',
            goal_title: '收拾房间',
            amount: '2.00',
            confirmed_at: '2026-09-02T10:00:00',
          }),
          rewardRecord(),
        ],
      }),
    );
    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: /已攒/ }));

    const drawer = await screen.findByRole('dialog');
    expect(await within(drawer).findByText('整理书桌')).toBeInTheDocument();
    expect(within(drawer).getByText('收拾房间')).toBeInTheDocument();
    expect(within(drawer).getByText('9月2日 10:00')).toBeInTheDocument();
    expect(within(drawer).getByText('+¥2')).toBeInTheDocument();
    expect(within(drawer).getByText('默写英语单词')).toBeInTheDocument();
    expect(within(drawer).getByText('+¥4')).toBeInTheDocument();

    const rows = within(
      within(drawer).getByRole('list', { name: '奖励记录' }),
    ).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('整理书桌');
  });

  it('一条奖励都没有时说清楚怎么才能有', async () => {
    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: /已攒/ }));

    const drawer = await screen.findByRole('dialog');
    expect(await within(drawer).findByText(/还没有奖励/)).toBeInTheDocument();
    expect(within(drawer).getByText(/完成任务让家长确认/)).toBeInTheDocument();
  });

  it('明细还没回来时先显示加载中', async () => {
    mockedApi.rewards
      .mockResolvedValueOnce(summary({ total_amount: '6.00' }))
      .mockReturnValueOnce(new Promise<FamilyRewardSummary>(() => {}));
    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: /已攒/ }));

    const drawer = await screen.findByRole('dialog');
    expect(await within(drawer).findByText(/正在加载奖励明细/)).toBeInTheDocument();
    expect(within(drawer).queryByRole('list', { name: '奖励记录' })).not.toBeInTheDocument();
  });

  it('明细加载失败给出错误并能重试', async () => {
    mockedApi.rewards
      .mockResolvedValueOnce(summary({ total_amount: '6.00' }))
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce(summary({ total_amount: '6.00', records: [rewardRecord()] }));
    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: /已攒/ }));

    const drawer = await screen.findByRole('dialog');
    expect(await within(drawer).findByText('奖励明细没加载出来')).toBeInTheDocument();

    fireEvent.click(within(drawer).getByRole('button', { name: '重新加载' }));
    expect(await within(drawer).findByText('默写英语单词')).toBeInTheDocument();
  });

  it('提交抽屉在没有证据时禁用提交，填了说明才能交', async () => {
    mockedApi.todayTasks.mockResolvedValue([task()]);
    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: /交作业/ }));

    const submit = await screen.findByRole('button', { name: '提交给家长' });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText(/写一句做了什么/), {
      target: { value: '默写完第 3 单元' },
    });
    await waitFor(() => expect(submit).toBeEnabled());
  });
});
