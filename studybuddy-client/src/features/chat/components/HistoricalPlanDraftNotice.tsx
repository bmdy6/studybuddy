import { Button, Typography } from 'antd';
import { useChatStore } from '@/features/chat/store';
import { READING_COLUMN_MAX } from '@/shared/theme/breakpoints';

const { Text } = Typography;

/**
 * 历史未完成草案提示条（M1 B：当前卡、历史草案分层）。
 * 同会话里已被后续 user 消息越过、或 legacy 无法证明归属的 pending 草案只降级为
 * 不可确认的紧凑提示，不提供"确认并创建"按钮；关闭只清前端展示，不改服务端草案状态。
 * 样式复用 --sb-* design token（暖色浅底 + 低饱和边框 + 次级文字），不引入新 UI 体系。
 */
export function HistoricalPlanDraftNotice() {
  const notice = useChatStore((s) => s.historicalPlanDraftNotice);
  const clear = useChatStore((s) => s.clearHistoricalPlanDraftNotice);
  if (!notice) return null;
  return (
    <div
      className="sb-historical-draft-notice"
      style={{
        maxWidth: READING_COLUMN_MAX,
        margin: '0 auto 12px',
        padding: '8px 12px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        background: 'var(--sb-color-bg-muted)',
        border: '1px solid var(--sb-color-border-warm)',
        borderRadius: 8,
      }}
    >
      <Text type="secondary" style={{ fontSize: 13 }}>
        上一份未确认草案「{notice.title}」已转为历史，不再生成计划。
      </Text>
      <Button type="text" size="small" onClick={clear} aria-label="关闭历史草案提示">
        知道了
      </Button>
    </div>
  );
}
