import { Alert, Button } from 'antd';
import type { ErrorReportInfo } from '@/features/chat/store';

interface ErrorReportCardProps {
  report: ErrorReportInfo;
  onCopy: () => void;
  onClose: () => void;
}

export function ErrorReportCard({ report, onCopy, onClose }: ErrorReportCardProps) {
  return (
    <Alert
      type="error"
      showIcon
      className="sb-error-report"
      message="出错了，可以复制给开发者"
      description={
        <div>
          <div className="sb-error-report-message">{report.message}</div>
          <div className="sb-error-report-actions">
            <Button size="small" onClick={onCopy}>
              复制错误信息
            </Button>
            <Button size="small" type="text" onClick={onClose}>
              关闭
            </Button>
          </div>
        </div>
      }
    />
  );
}
