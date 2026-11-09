import type { ReactNode } from 'react';
import { Typography } from 'antd';

const { Text, Title } = Typography;

export interface AppPageMetric {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: 'default' | 'success' | 'warning' | 'danger';
}

interface AppPageShellProps {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  metrics?: AppPageMetric[];
  maxWidth?: number;
  children: ReactNode;
}

export default function AppPageShell({
  title,
  subtitle,
  icon,
  actions,
  metrics,
  maxWidth = 1180,
  children,
}: AppPageShellProps) {
  return (
    <div className="sb-app-page-shell fade-in" style={{ maxWidth }}>
      <section className="sb-app-page-hero">
        <div className="sb-app-page-title-wrap">
          {icon && <div className="sb-app-page-icon">{icon}</div>}
          <div className="sb-app-page-copy">
            <Title level={3} className="sb-app-page-title">
              {title}
            </Title>
            {subtitle && <Text className="sb-app-page-subtitle">{subtitle}</Text>}
          </div>
        </div>
        {actions && <div className="sb-app-page-actions">{actions}</div>}
      </section>

      {metrics?.length ? (
        <section className="sb-app-page-metrics" aria-label="页面概览">
          {metrics.map((metric) => (
            <div key={String(metric.label)} className={`sb-app-page-metric sb-app-page-metric-${metric.tone ?? 'default'}`}>
              <Text className="sb-app-page-metric-label">{metric.label}</Text>
              <div className="sb-app-page-metric-value">{metric.value}</div>
              {metric.hint && <Text className="sb-app-page-metric-hint">{metric.hint}</Text>}
            </div>
          ))}
        </section>
      ) : null}

      {children}
    </div>
  );
}
