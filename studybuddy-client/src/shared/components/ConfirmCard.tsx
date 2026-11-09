import type { ReactNode } from 'react';
import { Button, Tag, Typography } from 'antd';
import { CheckOutlined } from '@ant-design/icons';
import { READING_COLUMN_MAX } from '@/shared/theme/breakpoints';

const { Text } = Typography;

interface ConfirmCardProps {
  title: string;
  hint?: string;
  tagText?: string;
  tagColor?: string;
  confirmLabel: string;
  onConfirm: () => void;
  confirming?: boolean;
  disabled?: boolean;
  extraButtons?: ReactNode;
  children: ReactNode;
}

/**
 * 通用确认卡片外壳：白底 + 暖色边框 + 圆角 + 标题 + 待确认 Tag + 内容区 + 底部确认按钮。
 * NoteDraftPanel / PhotoAnswerReviewPanel / PlanDraftPanel 共用，保证样式统一。
 * 复用现有 --sb-* design token，不引入新 UI 库。
 */
export function ConfirmCard({
  title,
  hint,
  tagText = '待确认',
  tagColor = 'warning',
  confirmLabel,
  onConfirm,
  confirming = false,
  disabled = false,
  extraButtons,
  children,
}: ConfirmCardProps) {
  // P2 修复：antd Tag color="warning" 的衍生色在项目 CSS 变量主题下失效（渲染成深灰底黑字），
  // 默认 warning 态改走自定义 class（浅橙底+深橙字+低饱和边框，见 index.css .sb-confirm-tag）；
  // 其他颜色保持 antd 原生行为（当前无调用方传非默认色，仅兜底）。
  const useDefaultTagStyle = tagColor === 'warning';
  return (
    <div
      className="sb-confirm-card"
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
          <Text strong style={{ fontSize: 15 }}>{title}</Text>
          {hint ? (
            <div style={{ marginTop: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>{hint}</Text>
            </div>
          ) : null}
        </div>
        <Tag
          className={useDefaultTagStyle ? 'sb-confirm-tag' : undefined}
          color={useDefaultTagStyle ? undefined : tagColor}
          style={{ marginInlineEnd: 0 }}
        >
          {tagText}
        </Tag>
      </div>
      {children}
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12, gap: 8 }}>
        {extraButtons}
        <Button
          type="primary"
          icon={<CheckOutlined />}
          loading={confirming}
          disabled={disabled}
          onClick={onConfirm}
        >
          {confirmLabel}
        </Button>
      </div>
    </div>
  );
}
