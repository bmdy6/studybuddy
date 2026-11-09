import { Alert, Button } from 'antd';

interface RetryBannerProps {
  message: string;
  onRetry: () => void;
}

/**
 * 错误 + 重新加载横幅。
 *
 * 收敛各页 `<Alert type="error" showIcon action={<Button>重新加载</Button>}>` 重复写法，
 * 统一可重试错误的交互（非终态错误才用；404/失效等终态用 AntD Result）。
 */
export function RetryBanner({ message, onRetry }: RetryBannerProps) {
  return (
    <Alert
      type="error"
      showIcon
      message={message}
      action={<Button onClick={onRetry}>重新加载</Button>}
    />
  );
}
