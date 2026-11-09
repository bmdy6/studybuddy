import { useEffect, useState } from 'react';
import { Modal, Button, Skeleton, Typography, message } from 'antd';
import { dailyRecordsApi } from '@/features/growth/dailyRecords';
import { wechatApi } from '../api';
import type { DailyLearningRecord } from '@/types';

const { Text, Paragraph } = Typography;

function hasLearningFacts(record: DailyLearningRecord | null): boolean {
  if (!record?.facts_snapshot) return false;
  const f = record.facts_snapshot;
  return (
    (f.evidence?.length ?? 0) > 0 ||
    (f.pending_tasks?.length ?? 0) > 0 ||
    (f.self_reported_duration_minutes ?? 0) > 0
  );
}

interface ReportProgressModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * 报进度预览弹窗：打开时读当日 AI 学习摘要（daily-records/refresh），只读展示。
 * 学习时长等事实由 AI 摘要决定，学生不可改；确认后发送给家长微信。
 * 发送接口下一步接入，当前发送按钮先提示开发中。
 */
export default function ReportProgressModal({ open, onClose }: ReportProgressModalProps) {
  const [loading, setLoading] = useState(false);
  const [record, setRecord] = useState<DailyLearningRecord | null>(null);
  const [error, setError] = useState(false);
  const [sending, setSending] = useState(false);

  const handleSend = async () => {
    setSending(true);
    try {
      await wechatApi.reportProgress();
      message.success('已发给家长');
      onClose();
    } catch (e) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '发送失败，请稍后重试';
      message.error(detail);
    } finally {
      setSending(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(false);
    setRecord(null);
    dailyRecordsApi
      .refresh()
      .then((r) => {
        if (!cancelled) setRecord(r);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  return (
    <Modal
      title="向家长汇报进度"
      open={open}
      onCancel={onClose}
      destroyOnClose
      footer={[
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button
          key="send"
          type="primary"
          loading={sending}
          disabled={!hasLearningFacts(record)}
          onClick={handleSend}
        >
          发送给家长
        </Button>,
      ]}
    >
      {loading ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : error ? (
        <Text type="secondary">读取今天的学习记录失败，请稍后再试。</Text>
      ) : hasLearningFacts(record) ? (
        record?.summary_text ? (
          <>
            <Text type="secondary">下面是今天的学习情况，确认后发给家长：</Text>
            <Paragraph style={{ whiteSpace: 'pre-wrap', marginTop: 8 }} strong>
              {record.summary_text}
            </Paragraph>
          </>
        ) : (
          <Text type="secondary">今天的学习摘要还在生成中，稍后再来报进度吧。</Text>
        )
      ) : (
        <Text type="secondary">今天还没有学习记录，学完再来报进度吧。</Text>
      )}
    </Modal>
  );
}
