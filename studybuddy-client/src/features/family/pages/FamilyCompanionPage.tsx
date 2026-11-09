import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App,
  Button,
  Empty,
  Modal,
  Popconfirm,
  Select,
  Skeleton,
  Tag,
  Typography,
} from 'antd';
import { RetryBanner } from '../../../shared/components/RetryBanner';
import {
  CheckCircleOutlined,
  CopyOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { QRCodeSVG } from 'qrcode.react';

import {
  type WechatBindSession,
  type WechatGuardianContext,
  type WechatGuardianSettings,
  wechatApi,
} from '@/features/wechat/api';
import StudentPageShell from '@/shared/components/StudentPageShell';

const { Text, Title } = Typography;

function parseExpiresAt(value: string): number {
  // 后端 expires_at 是 UTC 无时区后缀，补 Z 按 UTC 解析（与微信绑定一致）
  return Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`);
}

function formatRemaining(expiresAt: string): string {
  const ms = parseExpiresAt(expiresAt) - Date.now();
  if (Number.isNaN(ms) || ms <= 0) return '已过期';
  const totalSec = Math.floor(ms / 1000);
  const mm = Math.floor(totalSec / 60);
  const ss = totalSec % 60;
  return `剩余时间 ${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
}

export default function FamilyCompanionPage() {
  const { message } = App.useApp();
  const [contexts, setContexts] = useState<WechatGuardianContext[]>([]);
  const [settings, setSettings] = useState<WechatGuardianSettings | null>(null);
  const [invitation, setInvitation] = useState<WechatBindSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [inviting, setInviting] = useState(false);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [, setTick] = useState(0);
  // 邀请卡片剩余时间倒计时（每秒刷新触发重渲染，formatRemaining 读 Date.now()）
  useEffect(() => {
    if (!invitation || invitation.status !== 'pending') return;
    const t = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, [invitation]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const [nextContexts, nextSettings] = await Promise.all([
        wechatApi.listGuardianContexts(),
        wechatApi.getGuardianSettings(),
      ]);
      setContexts(nextContexts);
      setSettings(nextSettings);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!invitation || invitation.status !== 'pending') return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        const next = await wechatApi.getBindSession(invitation.id);
        if (!active) return;
        setInvitation(next);
        if (next.status === 'bound') {
          window.clearInterval(timer);
          await load();
          message.success('家长已绑定');
        }
      } catch {
        // 轮询失败保留当前二维码，下一轮继续。
      }
    }, 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [invitation, load, message]);

  const timeOptions = useMemo(() => {
    if (!settings) return [];
    return Array.from(
      new Set([...settings.push_time_options, settings.default_push_time]),
    ).map((value) => ({
      value,
      label: value === settings.default_push_time ? `${value}（默认）` : value,
    }));
  }, [settings]);

  const createInvitation = async () => {
    setInviting(true);
    try {
      setInvitation(await wechatApi.createGuardianInvitation());
    } catch {
      message.error('生成家长邀请失败');
    } finally {
      setInviting(false);
    }
  };

  const updateContext = async (
    context: WechatGuardianContext,
    payload: { push_time?: string; paused?: boolean },
  ) => {
    setUpdatingId(context.id);
    try {
      const updated = await wechatApi.updateGuardianContext(context.id, payload);
      setContexts((current) =>
        current.map((item) => (item.id === context.id ? updated : item)),
      );
      message.success('家庭陪伴设置已更新');
    } catch {
      message.error('设置更新失败');
    } finally {
      setUpdatingId(null);
    }
  };

  const unbind = async (context: WechatGuardianContext) => {
    setUpdatingId(context.id);
    try {
      await wechatApi.unbindGuardianContext(context.id);
      setContexts((current) => current.filter((item) => item.id !== context.id));
      message.success('家庭陪伴关系已解除');
    } catch {
      message.error('解除绑定失败');
    } finally {
      setUpdatingId(null);
    }
  };

  return (
    <StudentPageShell
      title="家庭陪伴"
      subtitle="管理已绑定家长、成长摘要时间和微信推送。"
      icon={<TeamOutlined />}
      actions={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          loading={inviting}
          onClick={() => void createInvitation()}
        >
          邀请家长
        </Button>
      }
    >
      {loading ? (
        <section className="sb-family-loading" aria-label="家庭陪伴加载中">
          <Skeleton active paragraph={{ rows: 5 }} />
        </section>
      ) : error ? (
        <RetryBanner message="家庭陪伴加载失败" onRetry={() => void load()} />
      ) : contexts.length === 0 ? (
        <section className="sb-family-empty">
          <Empty description="还没有绑定家长">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => void createInvitation()}>
              邀请家长
            </Button>
          </Empty>
        </section>
      ) : (
        <section className="sb-family-list" aria-label="已绑定家长">
          {contexts.map((context) => (
            <article key={context.id} className="sb-family-row">
              <div className="sb-family-row-main">
                <div className="sb-family-identity">
                  <div>
                    <Title level={4}>{context.guardian_name}</Title>
                    <Text type="secondary">{context.openid_masked}</Text>
                  </div>
                  <Tag className={context.paused ? 'sb-status-chip sb-status-chip--draft' : 'sb-status-chip sb-status-chip--confirmed'}>
                    {context.paused ? '已暂停' : '每日推送'}
                  </Tag>
                </div>

                <div className="sb-family-controls">
                  <label htmlFor={`family-push-time-${context.id}`}>发送时间</label>
                  <Select
                    id={`family-push-time-${context.id}`}
                    aria-label="成长摘要发送时间"
                    value={context.push_time}
                    options={timeOptions}
                    disabled={updatingId === context.id}
                    onChange={(value) => void updateContext(context, { push_time: value })}
                  />
                  <Button
                    icon={context.paused ? <PlayCircleOutlined /> : <PauseCircleOutlined />}
                    loading={updatingId === context.id}
                    onClick={() => void updateContext(context, { paused: !context.paused })}
                  >
                    {context.paused ? '恢复推送' : '暂停推送'}
                  </Button>
                  <Popconfirm
                    title="解除家庭陪伴"
                    description="解除后，这位家长将不再收到你的成长摘要。"
                    okText="确认解除"
                    cancelText="取消"
                    onConfirm={() => void unbind(context)}
                  >
                    <Button danger loading={updatingId === context.id}>
                      解除绑定
                    </Button>
                  </Popconfirm>
                </div>
              </div>

              <div className="sb-family-summary">
                <Text className="sb-family-summary-label">
                  {context.latest_summary_title ?? '最近成长摘要'}
                </Text>
                <Text className="sb-family-summary-content">
                  {context.latest_summary_content ?? '还没有生成成长摘要'}
                </Text>
                {context.latest_summary_created_at ? (
                  <Text type="secondary" className="sb-family-summary-time">
                    {new Date(context.latest_summary_created_at).toLocaleString('zh-CN')}
                  </Text>
                ) : null}
              </div>
            </article>
          ))}
        </section>
      )}

      <Modal
        title="邀请家长"
        open={Boolean(invitation)}
        footer={null}
        destroyOnHidden
        onCancel={() => setInvitation(null)}
      >
        {invitation ? (
          <div className="sb-family-invitation">
            <div aria-label="家长邀请二维码" className="sb-family-invitation-qr">
              <QRCodeSVG value={invitation.qr_value} size={196} />
            </div>
            <Text type="secondary">绑定码</Text>
            <div className="sb-family-bind-code">
              <Text strong>{invitation.bind_code}</Text>
              <Button
                type="text"
                icon={<CopyOutlined />}
                aria-label="复制绑定码"
                onClick={() => {
                  void navigator.clipboard?.writeText(invitation.bind_code);
                  message.success('绑定码已复制');
                }}
              />
            </div>
            <Text type="secondary" aria-label="邀请有效期" style={{ fontSize: 12 }}>
              {formatRemaining(invitation.expires_at)}
            </Text>
            <span
              className={`sb-family-invitation-status ${
                invitation.status === 'bound'
                  ? 'sb-family-invitation-status--bound'
                  : 'sb-family-invitation-status--pending'
              }`}
              aria-label={invitation.status === 'bound' ? '家长已绑定' : '等待家长绑定'}
            >
              {invitation.status === 'bound' ? <CheckCircleOutlined /> : null}
              {invitation.status === 'bound' ? '已绑定' : '等待家长绑定'}
            </span>
          </div>
        ) : null}
      </Modal>
    </StudentPageShell>
  );
}
