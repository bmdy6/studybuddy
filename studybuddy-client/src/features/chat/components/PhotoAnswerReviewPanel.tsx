import { useEffect, useState } from 'react';
import { Alert, Button, Checkbox, Input, Tag, Typography } from 'antd';
import { CheckCircleOutlined } from '@ant-design/icons';
import type { PhotoAnswerReviewItem, PhotoAnswerReviewState } from '@/types';
import { READING_COLUMN_MAX } from '@/shared/theme/breakpoints';

const { Text } = Typography;

interface PhotoAnswerReviewPanelProps {
  state: PhotoAnswerReviewState;
  confirming?: boolean;
  onConfirm: (items: PhotoAnswerReviewItem[]) => void;
}

function confidenceLabel(confidence: PhotoAnswerReviewItem['confidence']) {
  if (confidence === 'high') return { text: '高', color: 'success' };
  if (confidence === 'medium') return { text: '中', color: 'processing' };
  return { text: '低', color: 'warning' };
}

export function PhotoAnswerReviewPanel({
  state,
  confirming = false,
  onConfirm,
}: PhotoAnswerReviewPanelProps) {
  const [items, setItems] = useState<PhotoAnswerReviewItem[]>([]);

  useEffect(() => {
    setItems(
      state.items.map((item) => ({
        ...item,
        confirmed_answer: item.confirmed_answer ?? item.detected_answer ?? '',
      })),
    );
  }, [state]);

  const updateItem = (index: number, patch: Partial<PhotoAnswerReviewItem>) => {
    setItems((prev) => prev.map((item, idx) => (idx === index ? { ...item, ...patch } : item)));
  };

  const unresolvedCount = items.filter(
    (item) =>
      (item.needs_review || item.confidence === 'low') &&
      !item.skipped &&
      !(item.confirmed_answer || '').trim(),
  ).length;
  const canConfirm = items.length > 0 && unresolvedCount === 0;

  return (
    <div
      className="sb-answer-review-panel"
      style={{
        maxWidth: READING_COLUMN_MAX,
        margin: '0 auto 12px',
        padding: 14,
        background: 'var(--sb-color-white)',
        border: '1px solid var(--sb-color-border-warm)',
        borderRadius: 8,
        boxShadow: '0 1px 2px var(--sb-shadow-message)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 12 }}>
        <div style={{ flex: 1 }}>
          <Text strong style={{ fontSize: 15 }}>
            核对学生作答
          </Text>
          <div style={{ marginTop: 4 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              先确认 AI 识别到的学生答案，再进入逐题批改。
            </Text>
          </div>
        </div>
        <Tag color={unresolvedCount ? 'warning' : 'success'} style={{ marginInlineEnd: 0 }}>
          {unresolvedCount ? `${unresolvedCount} 题待确认` : '可批改'}
        </Tag>
      </div>

      {items.length === 0 ? (
        <Alert type="warning" showIcon message="暂未识别到逐题作答，可以直接把题目和答案发给我。" />
      ) : (
        <div style={{ display: 'grid', gap: 10 }}>
          {items.map((item, index) => {
            const confidence = confidenceLabel(item.confidence);
            return (
              <div
                key={`${item.question_no}-${index}`}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '64px minmax(0, 1fr) auto',
                  gap: 10,
                  alignItems: 'center',
                  padding: '10px 0',
                  borderTop: index === 0 ? 'none' : '1px solid var(--sb-color-border-warm)',
                }}
              >
                <Text strong>第{item.question_no}题</Text>
                <Input
                  aria-label={`第${item.question_no}题确认作答`}
                  value={item.confirmed_answer ?? ''}
                  disabled={item.skipped}
                  placeholder={item.detected_answer || '未识别'}
                  onChange={(event) => updateItem(index, { confirmed_answer: event.target.value })}
                />
                <Checkbox
                  checked={item.skipped}
                  onChange={(event) => updateItem(index, { skipped: event.target.checked })}
                >
                  跳过
                </Checkbox>
                <div style={{ gridColumn: '2 / 4', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <Tag color={confidence.color}>置信度 {confidence.text}</Tag>
                  {item.detected_answer ? <Tag>识别：{item.detected_answer}</Tag> : null}
                  {item.review_reason ? <Text type="secondary">{item.review_reason}</Text> : null}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
        <Button
          type="primary"
          aria-label="确认后批改"
          icon={<CheckCircleOutlined />}
          disabled={!canConfirm}
          loading={confirming}
          onClick={() => onConfirm(items)}
        >
          确认后批改
        </Button>
      </div>
    </div>
  );
}
