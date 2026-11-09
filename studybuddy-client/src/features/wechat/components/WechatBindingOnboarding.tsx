import { useCallback, useEffect, useRef, useState } from 'react';
import { Modal, Typography } from 'antd';

import { wechatApi } from '@/features/wechat/api';
import { p2Api } from '@/features/p2/api';
import { useChatStore } from '@/features/chat/store';
import WechatBindingPanel, {
  type WechatBindingPanelHandle,
  wechatBindingReminderStorageKey,
} from './WechatBindingPanel';

const { Paragraph, Title } = Typography;

interface WechatBindingOnboardingProps {
  userId: number;
}

function todayKey() {
  const today = new Date();
  const month = String(today.getMonth() + 1).padStart(2, '0');
  const day = String(today.getDate()).padStart(2, '0');
  return `${today.getFullYear()}-${month}-${day}`;
}

export default function WechatBindingOnboarding({ userId }: WechatBindingOnboardingProps) {
  const [open, setOpen] = useState(false);
  const reminderKey = wechatBindingReminderStorageKey(userId);
  // 草案/笔记/答题确认卡出现时，引导弹窗让位（确认是更高优先级，绑定微信可等）
  const hasPendingConfirm = useChatStore(
    (s) => !!(s.pendingPlanDraft || s.pendingNoteDraft || s.pendingAnswerReview),
  );
  useEffect(() => {
    if (hasPendingConfirm && open) {
      panelRef.current?.stopPolling();
      setOpen(false);
    }
  }, [hasPendingConfirm, open]);
  // 通过 ref 主动停止子组件轮询：点 X / 点遮罩 / 点「今天不再提醒」都走 skip，
  // 同步停止轮询 + 标记 skipRef，丢弃飞行中的异步回调，避免弹窗关闭时序被打乱。
  const panelRef = useRef<WechatBindingPanelHandle>(null);

  useEffect(() => {
    if (window.localStorage.getItem(reminderKey) === todayKey()) return;
    let active = true;
    Promise.all([wechatApi.getAccount(), p2Api.getProfileSummary(userId).catch(() => null)])
      .then(([account, profile]) => {
        if (!active) return;
        // 冷启动未完成（年级还没问）时不弹，不抢戏
        const needsColdStart =
          profile?.needs_onboarding && profile?.missing_fields?.includes('grade');
        if (needsColdStart) return;
        if (!account.bound) setOpen(true);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [reminderKey, userId]);

  const skip = useCallback(() => {
    // 先停轮询再写 snooze 和关闭，防止异步轮询回调在关闭动画期间重新 setSession/setPollStopped。
    panelRef.current?.stopPolling();
    window.localStorage.setItem(reminderKey, todayKey());
    setOpen(false);
  }, [reminderKey]);

  const bound = useCallback(() => {
    window.localStorage.removeItem(reminderKey);
    setOpen(false);
  }, [reminderKey]);

  // AntD 5.13 不支持 destroyOnHidden(5.25+ 才有)，用条件渲染确保关闭后 DOM 彻底卸载，
  // 避免弹窗关闭后 .ant-modal-wrap 残留 display:block 遮挡确认卡（P1 根因）
  if (!open) return null;
  return (
    <Modal
      className="sb-wechat-onboarding"
      open={open}
      footer={null}
      closable
      maskClosable
      onCancel={skip}
      width={560}
    >
      <Title level={3}>连接微信学习助手</Title>
      <Paragraph type="secondary">
        先复制绑定码，再保存二维码去微信扫码，最后在微信ClawBot AI对话中粘贴并发送绑定码。现在不方便可以选择今天不再提醒，明天会再次提醒。
      </Paragraph>
      <WechatBindingPanel
        ref={panelRef}
        userId={userId}
        autoStart
        allowSkip
        onBound={bound}
        onSkip={skip}
      />
    </Modal>
  );
}
