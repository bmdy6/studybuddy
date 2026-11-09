import { Spin } from 'antd';

interface PageSpinnerProps {
  /** 垂直留白(px)，默认 80，统一历史 60/80/120 漂移 */
  padding?: number;
}

/**
 * 页面级居中加载态。
 *
 * 收敛各页 `<div style={{ textAlign: 'center', padding: N }}><Spin size="large" /></div>`
 * 重复写法；padding 历史在 60/80/120 之间漂移，统一默认 80，需要更大留白时显式传。
 */
export function PageSpinner({ padding = 80 }: PageSpinnerProps) {
  return (
    <div style={{ textAlign: 'center', padding }}>
      <Spin size="large" />
    </div>
  );
}
