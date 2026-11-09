import type { ReactNode } from 'react';
import { Space, Typography } from 'antd';

const { Text, Title } = Typography;

export interface StudentPageMetric {
  label: string;
  value: ReactNode;
  tone?: 'default' | 'success' | 'warning' | 'danger';
}

interface StudentPageShellProps {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  metrics?: StudentPageMetric[];
  maxWidth?: number;
  children: ReactNode;
}

export default function StudentPageShell({
  title,
  subtitle,
  icon,
  actions,
  metrics,
  maxWidth = 1080,
  children,
}: StudentPageShellProps) {
  return (
    <div className="sb-student-shell fade-in" style={{ maxWidth }}>
      <section className="sb-student-hero">
        <div className="sb-student-hero-main">
          {icon && <div className="sb-student-hero-icon">{icon}</div>}
          <Space direction="vertical" size={4}>
            <Title level={3} className="sb-student-hero-title">
              {title}
            </Title>
            {subtitle && <Text className="sb-student-hero-subtitle">{subtitle}</Text>}
          </Space>
        </div>
        {actions && <div className="sb-student-hero-actions">{actions}</div>}
      </section>

      {metrics?.length ? (
        <section className="sb-student-metrics" aria-label="学习概览">
          {metrics.map((metric) => (
            <div key={String(metric.label)} className={`sb-student-metric sb-student-metric-${metric.tone ?? 'default'}`}>
              <Text className="sb-student-metric-label">{metric.label}</Text>
              <div className="sb-student-metric-value">{metric.value}</div>
            </div>
          ))}
        </section>
      ) : null}

      {children}
    </div>
  );
}
// agg-1 P2
