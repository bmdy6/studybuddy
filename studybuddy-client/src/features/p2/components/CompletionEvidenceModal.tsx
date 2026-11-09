import { useState } from 'react';
import { Input, Modal, Typography } from 'antd';

const { TextArea } = Input;
const { Text } = Typography;

interface CompletionEvidenceModalProps {
  open: boolean;
  itemTitle: string;
  submitting?: boolean;
  initialValue?: string;
  onCancel: () => void;
  onSubmit: (evidence: string) => void;
}

/**
 * 完成学习证据输入弹窗（P0 门禁）：学生完成计划项必须写一句
 * "学会了什么 / 哪里还没懂" 作为自报证据，strip 后非空才允许提交。
 * TodayPlanPanel 与 StudyPlansPage 共用，避免重复校验和文案。
 */
export function CompletionEvidenceModal({
  open,
  itemTitle,
  submitting = false,
  initialValue = '',
  onCancel,
  onSubmit,
}: CompletionEvidenceModalProps) {
  const [evidence, setEvidence] = useState(initialValue);

  // initialValue 变化（失败重开保留输入）时同步
  const [syncedInitial, setSyncedInitial] = useState(initialValue);
  if (syncedInitial !== initialValue) {
    setSyncedInitial(initialValue);
    if (initialValue) setEvidence(initialValue);
  }

  const handleOk = () => {
    const trimmed = evidence.trim();
    if (!trimmed) return; // 空证据不提交，提示在下方
    onSubmit(trimmed);
  };

  const handleCancel = () => {
    setEvidence('');
    onCancel();
  };

  return (
    <Modal
      open={open}
      title="完成学习"
      okText="确认完成"
      cancelText="再想想"
      okButtonProps={{ disabled: !evidence.trim(), loading: submitting }}
      onOk={handleOk}
      onCancel={handleCancel}
      afterClose={() => setEvidence('')}
      destroyOnClose
    >
      <Text strong style={{ display: 'block', marginBottom: 8 }}>
        {itemTitle}
      </Text>
      <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
        用一句话写写你学会了什么，或者哪里还没弄懂。这是你完成这项任务的记录。
      </Text>
      <TextArea
        value={evidence}
        onChange={(e) => setEvidence(e.target.value)}
        placeholder="例如：背出了不规则动词的过去式，但一般过去时否定句还不熟"
        rows={3}
        maxLength={500}
        showCount
        autoFocus
      />
      {!evidence.trim() && (
        <Text type="warning" style={{ display: 'block', marginTop: 4 }}>
          需要写一句学习记录才能确认完成
        </Text>
      )}
    </Modal>
  );
}
