import { useEffect, useState } from 'react';
import { CheckCircleOutlined } from '@ant-design/icons';
import { Result, Skeleton } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { wechatApi, type WechatParentInvitation } from '@/features/wechat/api';
import WechatBindCard from '@/features/wechat/components/WechatBindCard';

function parseServerTime(value: string): number {
  return Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`);
}

export default function WechatParentBindPage() {
  const [searchParams] = useSearchParams();
  const scene = searchParams.get('token')?.trim() ?? '';
  const [invitation, setInvitation] = useState<WechatParentInvitation | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    if (!scene) {
      setFailed(true);
      return () => {
        active = false;
      };
    }
    const load = async () => {
      try {
        const value = await wechatApi.getParentInvitation(scene);
        if (!active) return;
        const expired = value.status === 'pending' && Date.now() >= parseServerTime(value.expires_at);
        setInvitation(expired ? { ...value, status: 'expired' } : value);
        setFailed(false);
        if (!expired && value.status === 'pending') {
          timer = window.setTimeout(() => void load(), 3000);
        }
      } catch (error) {
        if (!active) return;
        const status = (error as { response?: { status?: number } }).response?.status;
        if (status === 404 || status === 410) {
          setFailed(true);
        } else {
          timer = window.setTimeout(() => void load(), 3000);
        }
      }
    };
    void load();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [scene]);

  useEffect(() => {
    if (invitation?.status !== 'pending') return;
    const timer = window.setInterval(() => {
      if (Date.now() >= parseServerTime(invitation.expires_at)) {
        setInvitation((current) =>
          current?.status === 'pending' ? { ...current, status: 'expired' } : current,
        );
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [invitation?.expires_at, invitation?.status]);

  if (failed) {
    return (
      <main className="sb-wechat-parent-page">
        <Result status="warning" title="邀请已失效" subTitle="请让学生重新生成家长邀请" />
      </main>
    );
  }

  if (!invitation) {
    return (
      <main className="sb-wechat-parent-page">
        <section className="sb-wechat-parent-loading" aria-label="正在加载家长邀请">
          <Skeleton active title paragraph={{ rows: 5 }} />
        </section>
      </main>
    );
  }

  if (invitation.status === 'bound') {
    return (
      <main className="sb-wechat-parent-page">
        <Result
          status="success"
          icon={<CheckCircleOutlined />}
          title="绑定成功"
          subTitle={`${invitation.parent_name}已绑定${invitation.student_name}的学习提醒`}
        />
      </main>
    );
  }

  if (invitation.status !== 'pending') {
    return (
      <main className="sb-wechat-parent-page">
        <Result status="warning" title="邀请已失效" subTitle="请让学生重新生成家长邀请" />
      </main>
    );
  }

  return (
    <main className="sb-wechat-parent-page">
      <section className="sb-wechat-parent-content">
        <WechatBindCard
          bindCode={invitation.bind_code}
          qrValue={invitation.qr_value}
          expiresAt={invitation.expires_at}
          relation={{ parentName: invitation.parent_name, studentName: invitation.student_name }}
        />
      </section>
    </main>
  );
}
