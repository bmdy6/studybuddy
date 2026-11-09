/**
 * 微信绑定卡片（学生 / 家长共用）。
 * 统一二维码（可长按保存的 PNG）、绑定码 + 复制、4 步说明、倒计时。
 * 家长端通过 relation 显示家长/学生关系。
 */
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Button, Skeleton, Typography } from 'antd';
import { CopyOutlined, WechatOutlined } from '@ant-design/icons';
import { QRCodeCanvas } from 'qrcode.react';

const { Text } = Typography;

function parseExpiresAt(value: string): number {
  return Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`);
}

interface WechatBindCardProps {
  bindCode: string;
  qrValue: string;
  expiresAt: string;
  /** 家长端显示的家长/学生关系，学生端不传 */
  relation?: { parentName: string; studentName: string };
  /** 卡片底部额外内容（如学生端"今天不再提醒"按钮） */
  footer?: ReactNode;
}

function PngQrImage({ value }: { value: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [src, setSrc] = useState('');

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas) setSrc(canvas.toDataURL('image/png'));
  }, [value]);

  return (
    <>
      <QRCodeCanvas
        ref={canvasRef}
        className="sb-wechat-qr-source"
        value={value}
        size={320}
        includeMargin
      />
      {src ? (
        <img
          className="sb-wechat-qr-image"
          src={src}
          alt="微信学习助手二维码"
          data-qr-value={value}
          width={320}
          height={320}
        />
      ) : (
        <Skeleton.Image active className="sb-wechat-qr-placeholder" />
      )}
    </>
  );
}

export default function WechatBindCard({ bindCode, qrValue, expiresAt, relation, footer }: WechatBindCardProps) {
  const [now, setNow] = useState(Date.now());
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const remainingSeconds = Math.max(0, Math.floor((parseExpiresAt(expiresAt) - now) / 1000));
  const countdown = `${String(Math.floor(remainingSeconds / 60)).padStart(2, '0')}:${String(
    remainingSeconds % 60,
  ).padStart(2, '0')}`;

  const copyBindCode = async () => {
    if (!bindCode) return;
    try {
      await navigator.clipboard.writeText(bindCode);
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  };

  return (
    <>
      {relation && (
        <dl className="sb-wechat-bind-relation">
          <div>
            <dt>家长</dt>
            <dd>{relation.parentName}</dd>
          </div>
          <div>
            <dt>学生</dt>
            <dd>{relation.studentName}</dd>
          </div>
        </dl>
      )}
      <div className="sb-wechat-bind-layout">
        <div className="sb-wechat-code-panel">
        <WechatOutlined aria-hidden="true" />
        <Text strong>先复制绑定码</Text>
        <Text type="secondary">扫码进入微信后，需要把它粘贴到对话里。</Text>
        <div className="sb-wechat-bind-code">
          <div>
            <Text>一次性绑定码</Text>
            <strong>{bindCode}</strong>
          </div>
          <Button
            icon={<CopyOutlined />}
            aria-label="复制绑定码"
            onClick={() => void copyBindCode()}
          >
            {copyState === 'copied' ? '已复制' : '复制绑定码'}
          </Button>
        </div>
        {copyState === 'failed' && (
          <Text type="danger" role="status">
            复制失败，请长按绑定码复制
          </Text>
        )}
      </div>
      <div className="sb-wechat-qr-panel">
        <PngQrImage value={qrValue} />
        <Text strong>再长按保存二维码</Text>
        <Text type="secondary">保存后去微信“扫一扫”，从相册选择这张二维码。</Text>
      </div>
      <div className="sb-wechat-bind-steps">
        <ol>
          <li>先复制绑定码</li>
          <li>长按二维码，保存到手机</li>
          <li>打开微信“扫一扫”，从相册选择二维码</li>
          <li>进入“微信ClawBot AI”对话，粘贴并发送绑定码</li>
        </ol>
        <div className="sb-wechat-countdown" aria-live="polite">
          <Text type="secondary">二维码与绑定码剩余时间</Text>
          <strong>{countdown}</strong>
        </div>
        {footer}
      </div>
    </div>
    </>
  );
}
