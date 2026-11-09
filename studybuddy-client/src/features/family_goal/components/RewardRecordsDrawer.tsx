import { useCallback, useEffect, useState } from 'react';
import dayjs from 'dayjs';
import { Drawer, Skeleton, Typography } from 'antd';

import { RetryBanner } from '@/shared/components/RetryBanner';
import { familyGoalApi, formatRewardAmount } from '@/features/family_goal/api';
import type { FamilyRewardRecord } from '@/types';

const { Text } = Typography;

/** 确认时间展示格式：后端给 ISO 串，本地时区显示到分钟。 */
const CONFIRMED_AT_FORMAT = 'M月D日 HH:mm';

interface RewardRecordsDrawerProps {
  open: boolean;
  studentId: number;
  onClose: () => void;
}

/** 缺时间就不编：confirmed_at 为 null（理应不发生）时直接不显示时间列。 */
function confirmedAtLabel(value: string | null): string | null {
  if (!value) return null;
  return dayjs(value).format(CONFIRMED_AT_FORMAT);
}

/**
 * 奖励明细：每一笔奖励是怎么来的（时间 / 任务 / 目标 / 金额），按确认时间倒序。
 * 打开时自己拉一次（家长可能刚又确认了一笔），加载 / 空 / 错误三态齐全，错误可重试。
 */
export default function RewardRecordsDrawer({
  open,
  studentId,
  onClose,
}: RewardRecordsDrawerProps) {
  const [records, setRecords] = useState<FamilyRewardRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const summary = await familyGoalApi.rewards(studentId);
      setRecords(summary.records);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [studentId]);

  useEffect(() => {
    if (open) {
      void load();
      return;
    }
    // 关着的时候不留旧数据，下次打开不会闪一笔上回的明细
    setRecords([]);
    setLoading(true);
    setError(false);
  }, [open, load]);

  const ordered = [...records].sort((a, b) =>
    (b.confirmed_at ?? '').localeCompare(a.confirmed_at ?? ''),
  );

  return (
    <Drawer
      open={open}
      placement="bottom"
      height="auto"
      title="奖励明细"
      onClose={onClose}
      destroyOnClose
    >
      {loading ? (
        <div className="sb-family-reward-state" role="status">
          <Skeleton active paragraph={{ rows: 3 }} title={false} />
          <Text type="secondary">正在加载奖励明细…</Text>
        </div>
      ) : error ? (
        <RetryBanner message="奖励明细没加载出来" onRetry={() => void load()} />
      ) : ordered.length === 0 ? (
        <div className="sb-family-reward-state">
          <Text type="secondary">还没有奖励，完成任务让家长确认就有。</Text>
        </div>
      ) : (
        <ul className="sb-family-reward-list" aria-label="奖励记录">
          {ordered.map((record) => {
            const confirmedAt = confirmedAtLabel(record.confirmed_at);
            return (
              <li key={record.id} className="sb-family-reward-item">
                <div className="sb-family-reward-main">
                  <Text strong>{record.task_title}</Text>
                  <div className="sb-family-reward-meta">
                    {record.goal_title && (
                      <Text type="secondary">{record.goal_title}</Text>
                    )}
                    {confirmedAt && <Text type="secondary">{confirmedAt}</Text>}
                  </div>
                </div>
                <Text className="sb-family-task-amount">
                  +{formatRewardAmount(record.amount)}
                </Text>
              </li>
            );
          })}
        </ul>
      )}
    </Drawer>
  );
}
