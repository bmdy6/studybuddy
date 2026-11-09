import { Button, Tag, Typography } from 'antd';
import { RightOutlined, ReloadOutlined } from '@ant-design/icons';

const { Text } = Typography;

export interface PlanCarryOverItem {
  title: string;
  minutes: number;
  status: string;
}

export interface PlanCarryOverCandidate {
  id: number;
  title: string;
  planned_date: string | null;
  status: string;
  overdue_days: number;
  items: PlanCarryOverItem[];
}

export interface PlanCarryOverState {
  asOfDate: string;
  plans: PlanCarryOverCandidate[];
}

interface PlanCarryOverPanelProps {
  state: PlanCarryOverState;
  confirmingPlanId: number | null;
  error: string | null;
  onCarryOver: (planId: number) => void;
  onReplan: () => void;
}

export function PlanCarryOverPanel({ state, confirmingPlanId, error, onCarryOver, onReplan }: PlanCarryOverPanelProps) {
  if (!state.plans.length) return null;
  return (
    <section
      aria-label="可继续的旧计划"
      style={{
        marginBottom: 12,
        padding: 12,
        background: 'var(--sb-color-bg-primary-soft)',
        border: '1px solid var(--sb-color-border-primary-soft)',
        borderRadius: 12,
      }}
    >
      <div style={{ marginBottom: 10 }}>
        <Text strong>发现可继续的旧计划</Text>
        <div style={{ marginTop: 4, fontSize: 12, color: 'var(--sb-color-text-soft)' }}>
          只会带走未完成任务，并创建今天的新计划；原计划会保留为历史记录。
        </div>
      </div>
      <div style={{ display: 'grid', gap: 8 }}>
        {state.plans.map((plan, index) => (
          <div
            key={plan.id}
            style={{
              padding: '10px 12px',
              background: 'var(--sb-color-white)',
              border: '1px solid var(--sb-color-border-warm)',
              borderRadius: 8,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <Text strong style={{ minWidth: 0, flex: 1 }}>{plan.title}</Text>
              <Tag>{plan.planned_date ?? '历史计划'}</Tag>
            </div>
            <div style={{ margin: '6px 0 10px', fontSize: 12, color: 'var(--sb-color-text-soft)' }}>
              {plan.items.map((item) => `${item.title}（${item.minutes} 分钟）`).join('、')}
            </div>
            <Button
              type={index === 0 ? 'primary' : 'default'}
              icon={<RightOutlined />}
              aria-label={`沿用${plan.title}`}
              loading={confirmingPlanId === plan.id}
              disabled={confirmingPlanId !== null}
              onClick={() => onCarryOver(plan.id)}
            >
              沿用这份计划
            </Button>
          </div>
        ))}
      </div>
      <Button
        type="default"
        icon={<ReloadOutlined />}
        aria-label="重新制定今天计划"
        onClick={onReplan}
      >
        重新制定今天计划
      </Button>
      {error ? <div role="alert" style={{ marginTop: 8, color: 'var(--sb-color-error-strong)', fontSize: 12 }}>{error}</div> : null}
    </section>
  );
}
