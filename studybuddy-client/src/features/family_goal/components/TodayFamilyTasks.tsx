import { useCallback, useEffect, useState } from 'react';
import { Button, Skeleton, Tag, Typography } from 'antd';
import { CheckCircleOutlined, PlusOutlined, RightOutlined } from '@ant-design/icons';

import { RetryBanner } from '@/shared/components/RetryBanner';
import {
  FAMILY_TASK_STATUS_LABELS,
  familyGoalApi,
  formatRewardAmount,
} from '@/features/family_goal/api';
import GoalCreateDrawer from '@/features/family_goal/components/GoalCreateDrawer';
import RewardRecordsDrawer from '@/features/family_goal/components/RewardRecordsDrawer';
import TaskEvidenceDrawer from '@/features/family_goal/components/TaskEvidenceDrawer';
import { useParentBound } from '@/features/family_goal/hooks';
import type { FamilyRewardSummary, FamilyTodayTask } from '@/types';

const { Text } = Typography;

interface TodayFamilyTasksProps {
  studentId: number;
  /** 嵌在二级页里时不重复渲染「家庭任务」标题（页面壳已有） */
  embedded?: boolean;
}

/** 状态 -> 标签（只用浅底深字，不用 AntD 语义色） */
function statusTagClass(status: FamilyTodayTask['status']): string {
  switch (status) {
    case 'approved':
      return 'sb-family-task-tag sb-family-task-tag--done';
    case 'submitted':
      return 'sb-family-task-tag sb-family-task-tag--waiting';
    case 'rejected':
      return 'sb-family-task-tag sb-family-task-tag--rejected';
    default:
      return 'sb-family-task-tag';
  }
}

/**
 * 今天页的家庭任务区：孩子自己或家长定的目标 -> 今天要做的事 + 奖励金额 + 状态。
 * 只展示与提交证据，不做任何 AI 判断；家长确认入口在个人工作台。
 */
export default function TodayFamilyTasks({ studentId, embedded = false }: TodayFamilyTasksProps) {
  const [tasks, setTasks] = useState<FamilyTodayTask[]>([]);
  const [rewards, setRewards] = useState<FamilyRewardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [goalDrawerOpen, setGoalDrawerOpen] = useState(false);
  const [rewardDrawerOpen, setRewardDrawerOpen] = useState(false);
  const [evidenceTarget, setEvidenceTarget] = useState<FamilyTodayTask | null>(null);
  // 没人能确认作业时得当面说清楚，否则孩子交了也白交
  const parentBound = useParentBound(studentId);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const [taskList, rewardSummary] = await Promise.all([
        familyGoalApi.todayTasks(studentId),
        familyGoalApi.rewards(studentId),
      ]);
      setTasks(taskList);
      setRewards(rewardSummary);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [studentId]);

  useEffect(() => {
    void load();
  }, [load]);

  const totalLabel = formatRewardAmount(familyGoalApi.rewardTotalOf(rewards)) ?? '¥0';

  if (loading) {
    return (
      <section className="sb-family-tasks" aria-label="家庭任务">
        <Skeleton active paragraph={{ rows: 2 }} title={false} />
      </section>
    );
  }

  if (error) {
    return (
      <section className="sb-family-tasks" aria-label="家庭任务">
        <RetryBanner message="家庭任务没加载出来" onRetry={() => void load()} />
      </section>
    );
  }

  return (
    <section className="sb-family-tasks" aria-label="家庭任务">
      <header className="sb-family-tasks-head">
        <div>
          {!embedded && <Text strong>家庭任务</Text>}
          <button
            type="button"
            className="sb-family-tasks-total"
            aria-haspopup="dialog"
            onClick={() => setRewardDrawerOpen(true)}
          >
            <span>已攒 {totalLabel}</span>
            <RightOutlined aria-hidden="true" />
          </button>
        </div>
        <Button type="link" size="small" icon={<PlusOutlined />} onClick={() => setGoalDrawerOpen(true)}>
          新建目标
        </Button>
      </header>

      {tasks.length === 0 ? (
        <div className="sb-family-tasks-empty">
          <Text type="secondary">还没有家庭任务。定一个小目标，做完交照片给家长看。</Text>
        </div>
      ) : (
        <ul className="sb-family-tasks-list">
          {tasks.map((task) => {
            const amount = formatRewardAmount(task.reward_amount);
            const submittable = task.status === 'pending' || task.status === 'rejected';
            return (
              <li key={task.occurrence_id} className="sb-family-task-item">
                <div className="sb-family-task-main">
                  <div className="sb-family-task-title">
                    <Text strong>{task.title}</Text>
                    {task.repeat_type === 'daily' && (
                      <Tag className="sb-family-task-repeat">每天</Tag>
                    )}
                  </div>
                  <div className="sb-family-task-meta">
                    <Text type="secondary">{task.goal_title}</Text>
                    {amount && <Text className="sb-family-task-amount">+{amount}</Text>}
                  </div>
                  {task.status === 'rejected' && task.reject_reason && (
                    <span className="sb-family-task-reason">家长说：{task.reject_reason}</span>
                  )}
                  {parentBound === false && (
                    <div className="sb-family-unbound-hint">
                      <Text type="secondary">还没绑定家长，暂时没人能确认</Text>
                      <Button className="sb-family-bind-link" href="#/family">
                        去绑定
                      </Button>
                    </div>
                  )}
                </div>
                <div className="sb-family-task-action">
                  <span className={statusTagClass(task.status)}>
                    {task.status === 'approved' && <CheckCircleOutlined />}
                    {FAMILY_TASK_STATUS_LABELS[task.status] ?? task.status}
                  </span>
                  {submittable && (
                    <Button
                      type="primary"
                      size="small"
                      icon={<RightOutlined />}
                      onClick={() => setEvidenceTarget(task)}
                    >
                      {task.status === 'rejected' ? '重新交' : '交作业'}
                    </Button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <GoalCreateDrawer
        open={goalDrawerOpen}
        studentId={studentId}
        onClose={() => setGoalDrawerOpen(false)}
        onCreated={() => void load()}
      />
      <RewardRecordsDrawer
        open={rewardDrawerOpen}
        studentId={studentId}
        onClose={() => setRewardDrawerOpen(false)}
      />
      <TaskEvidenceDrawer
        open={evidenceTarget !== null}
        task={evidenceTarget}
        onClose={() => setEvidenceTarget(null)}
        onSubmitted={() => void load()}
      />
    </section>
  );
}
