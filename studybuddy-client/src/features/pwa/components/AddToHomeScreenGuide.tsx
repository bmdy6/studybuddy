/**
 * 「添加到主屏幕」引导 Modal。
 * 根据环境渲染不同步骤：微信跳浏览器 / iOS 分享添加 / 安卓浏览器菜单添加。
 */
import { type ReactNode } from 'react';
import { Button, Modal, Space, Typography } from 'antd';
import { EllipsisOutlined, MenuOutlined, ShareAltOutlined } from '@ant-design/icons';
import type { InstallEnv } from '../utils/detectInstallEnv';

interface AddToHomeScreenGuideProps {
  env: InstallEnv;
  open: boolean;
  onClose: () => void;
}

export default function AddToHomeScreenGuide({ env, open, onClose }: AddToHomeScreenGuideProps) {
  return (
    <Modal
      title="添加到主屏幕"
      open={open}
      onCancel={onClose}
      footer={[<Button key="ok" type="primary" onClick={onClose}>知道了</Button>]}
    >
      <GuideContent env={env} />
    </Modal>
  );
}

function GuideContent({ env }: { env: InstallEnv }) {
  if (env === 'wechat') {
    return (
      <Space direction="vertical" size={10}>
        <Typography.Paragraph style={{ marginBottom: 0 }}>
          微信内无法直接添加到主屏幕，请先跳到手机浏览器：
        </Typography.Paragraph>
        <Step index={1}>点击右上角 <EllipsisOutlined /> 三个点</Step>
        <Step index={2}>选择「在浏览器中打开」或「在 Safari 中打开」</Step>
        <Step index={3}>在浏览器打开后，回到这里再点「添加」即可安装</Step>
      </Space>
    );
  }

  if (env === 'ios') {
    return (
      <Space direction="vertical" size={10}>
        <Typography.Paragraph style={{ marginBottom: 0 }}>
          把「知了」装到主屏幕，下次直接从桌面打开：
        </Typography.Paragraph>
        <div style={{ fontSize: 14, color: 'var(--sb-color-text)', lineHeight: 1.8 }}>
          先点 <ShareAltOutlined /> 分享按钮：<br />
          · Safari：在屏幕底部<br />
          · Chrome：在地址栏右侧
        </div>
        <Step index={1}>选择「添加到主屏幕」</Step>
        <Step index={2}>点「添加」</Step>
      </Space>
    );
  }

  // android 未捕获 beforeinstallprompt（夸克/UC 等非 Chrome 浏览器）
  return (
    <Space direction="vertical" size={10}>
      <Typography.Paragraph style={{ marginBottom: 0 }}>
        把「知了」装到主屏幕，下次直接从桌面打开：
      </Typography.Paragraph>
      <Step index={1}>点击浏览器菜单 <MenuOutlined />（通常在右上角或底部）</Step>
      <Step index={2}>选择「添加到主屏幕」或「添加到桌面」</Step>
      <Step index={3}>点「添加」</Step>
    </Space>
  );
}

function Step({ index, children }: { index: number; children: ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
      <span
        style={{
          flexShrink: 0,
          width: 20,
          height: 20,
          borderRadius: '50%',
          background: 'var(--sb-color-primary)',
          color: '#fff',
          fontSize: 12,
          lineHeight: '20px',
          textAlign: 'center',
        }}
      >
        {index}
      </span>
      <span style={{ color: 'var(--sb-color-text)' }}>{children}</span>
    </div>
  );
}
