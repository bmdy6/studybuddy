import { useState } from 'react';
import { Button, Typography } from 'antd';
import ReportProgressModal from './ReportProgressModal';

const { Text } = Typography;

/**
 * 个人中心"向家长汇报进度"入口区块。
 * 上下结构：标题 + 说明 + 按钮，不把长文案塞进按钮，避免突兀。
 */
export default function ReportProgressEntry() {
  const [open, setOpen] = useState(false);
  return (
    <section className="sb-account-report">
      <div className="sb-account-report-copy">
        <Text strong>跟家长汇报进度</Text>
        <br />
        <Text type="secondary" className="sb-account-report-desc">让家长知道你今天学了什么</Text>
      </div>
      <Button onClick={() => setOpen(true)}>汇报进度</Button>
      <ReportProgressModal open={open} onClose={() => setOpen(false)} />
    </section>
  );
}
