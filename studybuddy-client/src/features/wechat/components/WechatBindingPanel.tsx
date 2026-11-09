import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Alert, Button, Skeleton, Typography } from 'antd';
import {
  CheckCircleOutlined,
  CopyOutlined,
  ReloadOutlined,
  WechatOutlined,
} from '@ant-design/icons';
import { QRCodeCanvas } from 'qrcode.react';

import { wechatApi, type WechatBindSession } from '@/features/wechat/api';

const { Text } = Typography;
const POLL_INTERVAL_MS = 3000;
const createSessionRequests = new Map<string, Promise<WechatBindSession>>();
const getSessionRequests = new Map<number, Promise<WechatBindSession>>();

interface WechatBindingPanelProps {
  userId: number;
  autoStart?: boolean;
  allowSkip?: boolean;
  onBound?: () => void;
  onSkip?: () => void;
}

export interface WechatBindingPanelHandle {
  stopPolling: () => void;
}

function sessionStorageKey(userId: number) {
  return `studybuddy:wechat-bind-session:${userId}`;
}

export function wechatBindingReminderStorageKey(userId: number) {
  return `studybuddy:wechat-bind-snoozed-on:${userId}`;
}

function requestBindSession(storageKey: string) {
  const existing = createSessionRequests.get(storageKey);
  if (existing) return existing;
  const request = wechatApi.createBindSession().finally(() => {
    if (createSessionRequests.get(storageKey) === request) {
      createSessionRequests.delete(storageKey);
    }
  });
  createSessionRequests.set(storageKey, request);
  return request;
}

function requestBindSessionState(sessionId: number) {
  const existing = getSessionRequests.get(sessionId);
  if (existing) return existing;
  const request = wechatApi.getBindSession(sessionId).finally(() => {
    if (getSessionRequests.get(sessionId) === request) {
      getSessionRequests.delete(sessionId);
    }
  });
  getSessionRequests.set(sessionId, request);
  return request;
}

function parseExpiresAt(value: string) {
  return Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`);
}

function getError(error: unknown, fallback: string) {
  return (
    (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? fallback
  );
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

const WechatBindingPanel = forwardRef<WechatBindingPanelHandle, WechatBindingPanelProps>(
  function WechatBindingPanel({ userId, autoStart = false, allowSkip = false, onBound, onSkip }, ref) {
    const [session, setSession] = useState<WechatBindSession | null>(null);
    const [loading, setLoading] = useState(false);
    const [pollStopped, setPollStopped] = useState(false);
    const [error, setError] = useState('');
    const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
    const [now, setNow] = useState(Date.now());
    const storageKey = sessionStorageKey(userId);
    // skipRef 标记是否已跳过/关闭：跳过后异步轮询回调不得再 setSession/setPollStopped 重新触发渲染或重排定时器。
    const skipRef = useRef(false);

    useImperativeHandle(
      ref,
      () => ({
        stopPolling: () => {
          skipRef.current = true;
          setPollStopped(true);
        },
      }),
      [],
    );

    const applySession = useCallback(
      (next: WechatBindSession) => {
        // 已跳过/关闭后，丢弃所有异步轮询返回的 session，避免重置 pollStopped/重排轮询导致弹窗关闭时序异常。
        if (skipRef.current) return;
        setSession(next);
        setNow(Date.now());
        setPollStopped(false);
        if (next.status === 'bound') {
          window.sessionStorage.removeItem(storageKey);
          window.localStorage.removeItem(wechatBindingReminderStorageKey(userId));
          onBound?.();
        } else if (next.status === 'pending') {
          window.sessionStorage.setItem(storageKey, String(next.id));
        } else {
          window.sessionStorage.removeItem(storageKey);
        }
      },
      [onBound, storageKey, userId],
    );

    const createSession = useCallback(async () => {
      setLoading(true);
      setError('');
      setCopyState('idle');
      try {
        applySession(await requestBindSession(storageKey));
      } catch (requestError) {
        setError(getError(requestError, '暂时无法生成二维码和绑定码，请稍后再试'));
      } finally {
        setLoading(false);
      }
    }, [applySession, storageKey]);

    useEffect(() => {
      let active = true;
      const restore = async () => {
        const storedId = Number(window.sessionStorage.getItem(storageKey));
        if (storedId > 0) {
          setLoading(true);
          try {
            const restored = await requestBindSessionState(storedId);
            if (active) applySession(restored);
            return;
          } catch {
            window.sessionStorage.removeItem(storageKey);
          } finally {
            if (active) setLoading(false);
          }
        }
        if (active && autoStart) await createSession();
      };
      void restore();
      return () => {
        active = false;
      };
    }, [applySession, autoStart, createSession, storageKey]);

    useEffect(() => {
      if (!session || session.status !== 'pending' || pollStopped) return;
      const expiresAt = parseExpiresAt(session.expires_at);
      if (expiresAt <= Date.now()) {
        applySession({ ...session, status: 'expired' });
        return;
      }
      let active = true;
      let timer: number | undefined;
      const poll = async () => {
        try {
          const next = await requestBindSessionState(session.id);
          if (!active) return;
          applySession(next);
        } catch (requestError) {
          if (!active) return;
          const status = (requestError as { response?: { status?: number } })?.response?.status;
          if (status === 400 || status === 404 || status === 409) {
            setError(getError(requestError, '这次绑定无法完成，请重新生成二维码和绑定码'));
            setPollStopped(true);
            if (status === 404) window.sessionStorage.removeItem(storageKey);
            return;
          }
        }
        if (active) timer = window.setTimeout(() => void poll(), POLL_INTERVAL_MS);
      };
      timer = window.setTimeout(() => void poll(), POLL_INTERVAL_MS);
      return () => {
        active = false;
        if (timer !== undefined) window.clearTimeout(timer);
      };
    }, [applySession, pollStopped, session, storageKey]);

    useEffect(() => {
      if (session?.status !== 'pending') return;
      const timer = window.setInterval(() => setNow(Date.now()), 1000);
      return () => window.clearInterval(timer);
    }, [session?.status]);

    useEffect(() => {
      if (session?.status === 'pending' && parseExpiresAt(session.expires_at) <= now) {
        applySession({ ...session, status: 'expired' });
      }
    }, [applySession, now, session]);

    const remainingSeconds =
      session?.status === 'pending'
        ? Math.max(0, Math.floor((parseExpiresAt(session.expires_at) - now) / 1000))
        : 0;
    const countdown = `${String(Math.floor(remainingSeconds / 60)).padStart(2, '0')}:${String(
      remainingSeconds % 60,
    ).padStart(2, '0')}`;

    const copyBindCode = async () => {
      if (!session?.bind_code) return;
      try {
        await navigator.clipboard.writeText(session.bind_code);
        setCopyState('copied');
      } catch {
        setCopyState('failed');
      }
    };

    if (session?.status === 'bound') {
      return (
        <div className="sb-wechat-bound" role="status">
          <CheckCircleOutlined />
          <div>
            <Text strong>微信学习助手已绑定</Text>
            <Text type="secondary">现在可以直接回到主页开始学习。</Text>
          </div>
        </div>
      );
    }

    if (session?.status === 'pending' && !pollStopped) {
      return (
        <div className="sb-wechat-bind-layout">
          <div className="sb-wechat-code-panel">
            <WechatOutlined aria-hidden="true" />
            <Text strong>先复制绑定码</Text>
            <Text type="secondary">扫码进入微信后，需要把它粘贴到对话里。</Text>
            <div className="sb-wechat-bind-code">
              <div>
                <Text>一次性绑定码</Text>
                <strong>{session.bind_code}</strong>
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
            <PngQrImage value={session.qr_value} />
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
            {allowSkip && (
              <Button type="text" onClick={onSkip}>
                今天不再提醒
              </Button>
            )}
          </div>
        </div>
      );
    }

    if (error || session?.status === 'expired' || pollStopped) {
      return (
        <div className="sb-wechat-retry" role="status">
          <Alert
            type="warning"
            showIcon
            message={error || '二维码或绑定码已失效'}
            description="重新生成后按复制、保存、扫码、发送绑定码的顺序再试一次。"
          />
          <div className="sb-wechat-bind-actions">
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={() => void createSession()}
            >
              重新生成二维码和绑定码
            </Button>
            {allowSkip && (
              <Button type="text" onClick={onSkip}>
                今天不再提醒
              </Button>
            )}
          </div>
        </div>
      );
    }

    if (loading) {
      return <Skeleton active paragraph={{ rows: 3 }} />;
    }

    return (
      <div className="sb-wechat-intro">
        <WechatOutlined />
        <div>
          <Text strong>连接微信学习助手</Text>
          <Text type="secondary">绑定后可在微信ClawBot AI继续学习和接收学习动态。</Text>
        </div>
        <Button
          type="primary"
          icon={<WechatOutlined />}
          onClick={() => void createSession()}
        >
          绑定微信学习助手
        </Button>
        {allowSkip && (
          <Button type="text" onClick={onSkip}>
            今天不再提醒
          </Button>
        )}
      </div>
    );
  },
);

export default WechatBindingPanel;
