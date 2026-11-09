import { useEffect, useState } from 'react';
import { App, Button, Drawer, Input, InputNumber, Radio, Typography } from 'antd';

import { familyGoalApi } from '@/features/family_goal/api';
import { useParentBound } from '@/features/family_goal/hooks';

const { Text } = Typography;

interface GoalCreateDrawerProps {
  open: boolean;
  studentId: number;
  onClose: () => void;
  onCreated: () => void;
}

/**
 * 新建目标 + 第一个任务：孩子自己想完成的事（家长版在个人工作台里做）。
 * 金额规则与后端一致：任务级为空则继承目标级，两级都空就不给建。
 */
export default function GoalCreateDrawer({ open, studentId, onClose, onCreated }: GoalCreateDrawerProps) {
  const { message } = App.useApp();
  // 建之前就先说：没人能确认，别等交完才发现
  const parentBound = useParentBound(open ? studentId : null);
  const [goalTitle, setGoalTitle] = useState('');
  const [goalAmount, setGoalAmount] = useState<number | null>(5);
  const [taskTitle, setTaskTitle] = useState('');
  const [taskAmount, setTaskAmount] = useState<number | null>(null);
  const [repeatType, setRepeatType] = useState<'once' | 'daily'>('once');
  const [submitting, setSubmitting] = useState(false);
  // 目标已建、任务没建成功时记住 id，重试只补任务，不重复建目标
  const [createdGoalId, setCreatedGoalId] = useState<number | null>(null);

  useEffect(() => {
    if (open) return;
    setGoalTitle('');
    setGoalAmount(5);
    setTaskTitle('');
    setTaskAmount(null);
    setRepeatType('once');
    setCreatedGoalId(null);
  }, [open]);

  const amountsFilled = (taskAmount ?? goalAmount) !== null;
  const canSubmit =
    goalTitle.trim().length > 0 && taskTitle.trim().length > 0 && amountsFilled && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      let goalId = createdGoalId;
      if (goalId === null) {
        const goal = await familyGoalApi.createGoal(studentId, {
          title: goalTitle.trim(),
          reward_amount: goalAmount === null ? null : goalAmount.toFixed(2),
        });
        goalId = goal.id;
        setCreatedGoalId(goalId);
      }
      await familyGoalApi.createTask(goalId, {
        title: taskTitle.trim(),
        repeat_type: repeatType,
        reward_amount: taskAmount === null ? null : taskAmount.toFixed(2),
      });
      message.success('目标建好了');
      onCreated();
      onClose();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail ?? '保存失败，请重试');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Drawer
      open={open}
      placement="bottom"
      height="auto"
      title="新建目标"
      onClose={onClose}
      destroyOnClose
      footer={
        <div className="sb-family-task-drawer-footer">
          <Button onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button type="primary" loading={submitting} disabled={!canSubmit} onClick={handleSubmit}>
            建目标
          </Button>
        </div>
      }
    >
      {parentBound === false && (
        <div className="sb-family-unbound-hint sb-family-goal-unbound">
          <Text type="secondary">还没绑定家长，建了目标也没人能确认</Text>
          <Button className="sb-family-bind-link" href="#/family">
            去绑定
          </Button>
        </div>
      )}
      <div className="sb-family-goal-form">
        <label>
          <Text strong>我想做到什么</Text>
          <Input
            value={goalTitle}
            onChange={(event) => setGoalTitle(event.target.value)}
            placeholder="比如：英语默写全对"
            maxLength={64}
          />
        </label>
        <label>
          <Text strong>做完给多少奖励</Text>
          <InputNumber
            value={goalAmount}
            onChange={setGoalAmount}
            min={0}
            precision={2}
            step={1}
            prefix="¥"
            style={{ width: '100%' }}
            placeholder="留空表示不设默认金额"
          />
        </label>
        <label>
          <Text strong>第一件事做什么</Text>
          <Input
            value={taskTitle}
            onChange={(event) => setTaskTitle(event.target.value)}
            placeholder="比如：默写英语单词"
            maxLength={80}
          />
        </label>
        <label>
          <Text strong>这件事多久做一次</Text>
          <Radio.Group
            value={repeatType}
            onChange={(event) => setRepeatType(event.target.value)}
            optionType="button"
            buttonStyle="solid"
          >
            <Radio.Button value="once">做一次</Radio.Button>
            <Radio.Button value="daily">每天都要做</Radio.Button>
          </Radio.Group>
        </label>
        <label>
          <Text strong>这件事单独的奖励（可选）</Text>
          <InputNumber
            value={taskAmount}
            onChange={setTaskAmount}
            min={0}
            precision={2}
            step={1}
            prefix="¥"
            style={{ width: '100%' }}
            placeholder="留空就用上面的默认金额"
          />
        </label>
        {!amountsFilled && (
          <Text type="danger" style={{ fontSize: 12 }}>
            目标和任务至少要填一个金额，否则做完没有奖励可记。
          </Text>
        )}
      </div>
    </Drawer>
  );
}
