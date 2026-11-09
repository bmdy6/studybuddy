import { Tag } from 'antd';
import { ConfirmCard } from '@/shared/components/ConfirmCard';

export interface PlanDraftItem {
  title: string;
  target?: string | null;
  minutes: number;
  related_tags?: string[];
}

export interface PlanDraftState {
  draftId: number;
  revision: number;
  title: string;
  focus?: string | null;
  planned_date?: string | null;
  items: PlanDraftItem[];
  expiresAt?: string | null;
  /** M1：服务端注入的会话归属/创建时间，前端不猜 */
  chatSessionId?: number | null;
  createdAt?: string | null;
}

interface PlanDraftPanelProps {
  state: PlanDraftState;
  confirming?: boolean;
  onConfirm: () => void;
}

/**
 * 计划草案确认卡：AI 生成草案后展示，学生点"确认并创建"才正式建计划。
 * 不接受文字"可以"确认--必须点按钮。基于 ConfirmCard 通用外壳。
 */
export function PlanDraftPanel({ state, confirming = false, onConfirm }: PlanDraftPanelProps) {
  const totalMinutes = state.items.reduce((sum, item) => sum + item.minutes, 0);
  return (
    <ConfirmCard
      title={state.title}
      hint={`共 ${state.items.length} 项，约 ${totalMinutes} 分钟。点"确认并创建"后正式建计划。`}
      confirmLabel="确认并创建"
      onConfirm={onConfirm}
      confirming={confirming}
    >
      <div style={{ display: 'grid', gap: 8 }}>
        {state.focus ? <Tag color="blue">{state.focus}</Tag> : null}
        {state.items.map((item, index) => (
          <div
            key={index}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '6px 0',
              borderTop: index === 0 ? 'none' : '1px solid var(--sb-color-border-warm)',
            }}
          >
            <span>{item.title}</span>
            <Tag>{item.minutes} 分钟</Tag>
          </div>
        ))}
      </div>
    </ConfirmCard>
  );
}
