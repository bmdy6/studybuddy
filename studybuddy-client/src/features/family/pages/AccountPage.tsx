import { WECHAT_ENABLED } from '@/shared/constants';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { App, Avatar, Button, Drawer, Form, Input, Modal, Typography } from 'antd';
import {
  CheckCircleOutlined,
  EditOutlined,
  InfoCircleOutlined,
  LockOutlined,
  LogoutOutlined,
  MobileOutlined,
  RightOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
  SwapOutlined,
  TeamOutlined,
  TrophyOutlined,
  UserOutlined,
  WechatOutlined,
} from '@ant-design/icons';
import { authApi } from '@/features/auth/api';
import { useAuth } from '@/features/auth/useAuth';
import { useOpenFamilyTaskCount } from '@/features/family_goal/hooks';
import { wechatApi, type WechatAccount } from '@/features/wechat/api';
import ReportProgressModal from '@/features/wechat/components/ReportProgressModal';
import WechatBindingPanel from '@/features/wechat/components/WechatBindingPanel';
import StudentPageShell from '@/shared/components/StudentPageShell';
import { BRAND } from '@/shared/constants';
import { useAddToHomeScreen } from '@/features/pwa/hooks/useAddToHomeScreen';
import AddToHomeScreenGuide from '@/features/pwa/components/AddToHomeScreenGuide';
import { READING_COLUMN_MAX } from '@/shared/theme/breakpoints';

const { Text } = Typography;
const WECHAT_ACCOUNT_SYNC_ATTEMPTS = 10;
type AccountDrawer = 'profile' | 'wechat' | 'security' | null;

interface AccountMenuItemProps {
  icon: ReactNode;
  title: string;
  description: string;
  status?: string;
  danger?: boolean;
  onClick: () => void;
}

function AccountMenuItem({ icon, title, description, status, danger, onClick }: AccountMenuItemProps) {
  return (
    <button
      type="button"
      className={`sb-account-menu-item${danger ? ' sb-account-menu-item--danger' : ''}`}
      onClick={onClick}
    >
      <span className="sb-account-menu-icon" aria-hidden="true">{icon}</span>
      <span className="sb-account-menu-copy">
        <Text strong>{title}</Text>
        <Text type="secondary">{description}</Text>
      </span>
      {status ? <span className="sb-account-menu-status">{status}</span> : null}
      <RightOutlined className="sb-account-menu-arrow" aria-hidden="true" />
    </button>
  );
}

export default function AccountPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { displayName, avatar, role, userId, updateProfile, logout, mode, setMode } = useAuth();
  // 手机端列表行没有徽标，靠 status 插槽提醒今天还有事没交
  const openFamilyTaskCount = useOpenFamilyTaskCount(role === 'student' ? (userId ?? null) : null);
  const [drawer, setDrawer] = useState<AccountDrawer>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingPwd, setSavingPwd] = useState(false);
  const [wechatAccount, setWechatAccount] = useState<WechatAccount | null>(null);
  const [wechatLoading, setWechatLoading] = useState(false);
  const [wechatBindingCompleted, setWechatBindingCompleted] = useState(false);
  const [modeModalOpen, setModeModalOpen] = useState(false);
  const [profileForm] = Form.useForm();
  const [pwdForm] = Form.useForm();
  const install = useAddToHomeScreen();

  const roleLabel = role === 'parent' ? '辅导者' : '学生';
  const accountName = displayName || '未设置名称';

  const switchMode = async (m: 'study' | 'hobby') => {
    try {
      await authApi.updateProfile({ mode: m });
      setMode(m);
      setModeModalOpen(false);
      // 切模式后重载：重新拉当前模式主会话，避免旧会话上下文串污染（会话已按模式隔离）
      window.location.reload();
    } catch {
      message.error('切换失败，请稍后再试');
    }
  };

  const refreshWechatAccount = useCallback(async () => {
    if (!WECHAT_ENABLED) return;
    try {
      setWechatAccount(await wechatApi.getAccount());
    } catch {
      setWechatAccount({ bound: false });
    }
  }, []);

  useEffect(() => {
    void refreshWechatAccount();
  }, [refreshWechatAccount]);

  useEffect(() => {
    if (!wechatBindingCompleted || wechatAccount?.bound) return;
    let active = true;
    let timer: number | undefined;
    let attempts = 0;
    const refresh = async () => {
      attempts += 1;
      await refreshWechatAccount();
      if (active && attempts < WECHAT_ACCOUNT_SYNC_ATTEMPTS) {
        timer = window.setTimeout(() => void refresh(), 3000);
      }
    };
    timer = window.setTimeout(() => void refresh(), 3000);
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [refreshWechatAccount, wechatAccount?.bound, wechatBindingCompleted]);

  const openProfile = () => {
    profileForm.setFieldsValue({ display_name: displayName ?? '', avatar: avatar ?? '' });
    setDrawer('profile');
  };

  const onWechatBound = useCallback(() => {
    setWechatBindingCompleted(true);
    void refreshWechatAccount();
  }, [refreshWechatAccount]);

  const onUnbindWechat = async () => {
    setWechatLoading(true);
    try {
      await wechatApi.unbind();
      await refreshWechatAccount();
      message.success('已解除绑定');
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail ?? '解除绑定失败');
    } finally {
      setWechatLoading(false);
    }
  };

  const onSaveProfile = async (values: { display_name: string; avatar?: string }) => {
    setSavingProfile(true);
    try {
      const result = await authApi.updateProfile({
        display_name: values.display_name,
        avatar: values.avatar || undefined,
      });
      updateProfile(result.display_name, result.avatar);
      message.success('已保存');
      setDrawer(null);
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail ?? '保存失败');
    } finally {
      setSavingProfile(false);
    }
  };

  const onChangePassword = async (values: {
    old_password: string;
    new_password: string;
    confirm: string;
  }) => {
    if (values.new_password !== values.confirm) {
      message.error('两次输入的新密码不一致');
      return;
    }
    setSavingPwd(true);
    try {
      await authApi.changePassword({
        old_password: values.old_password,
        new_password: values.new_password,
      });
      message.success('密码已修改');
      pwdForm.resetFields();
      setDrawer(null);
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail ?? '修改失败');
    } finally {
      setSavingPwd(false);
    }
  };

  const closeSecurityDrawer = () => {
    pwdForm.resetFields();
    setDrawer(null);
  };

  const confirmLogout = () => {
    Modal.confirm({
      title: '退出登录？',
      content: '下次使用需要重新输入账号和密码。',
      okText: '退出登录',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: () => {
        logout();
        navigate('/login');
      },
    });
  };

  return (
    <StudentPageShell title="我的" maxWidth={READING_COLUMN_MAX}>
      <div className="sb-account-page">
        <button
          type="button"
          className="sb-account-profile-card"
          aria-label={`${accountName} ${roleLabel} 编辑个人资料`}
          onClick={openProfile}
        >
          <Avatar size={68} src={avatar || undefined} icon={<UserOutlined />} />
          <span className="sb-account-profile-copy">
            <Text strong>{accountName}</Text>
            <span className="sb-account-role-chip">{roleLabel}</span>
          </span>
          <span className="sb-account-profile-action">
            <EditOutlined />
            <span>编辑资料</span>
          </span>
          <RightOutlined className="sb-account-menu-arrow" aria-hidden="true" />
        </button>

        <section className="sb-account-group" aria-labelledby="account-learning-title">
          <h2 id="account-learning-title">学习与连接</h2>
          <div className="sb-account-menu-card">
            <AccountMenuItem
              icon={<SwapOutlined />}
              title="模式切换"
              description={mode === 'hobby' ? '兴趣爱好模式（资源推荐/陪练对话）' : '学习模式（错题/试卷/笔记/记录）'}
              status={mode === 'hobby' ? '兴趣爱好' : '学习'}
              onClick={() => setModeModalOpen(true)}
            />
            {WECHAT_ENABLED && <>
            <AccountMenuItem
              icon={<WechatOutlined />}
              title="微信学习助手"
              description="在微信继续学习和接收动态"
              status={wechatAccount ? (wechatAccount.bound ? '已绑定' : '未绑定') : '加载中'}
              onClick={() => setDrawer('wechat')}
            />
            {role === 'student' ? (
              <AccountMenuItem
                icon={<SendOutlined />}
                title="向家长汇报进度"
                description="把今天的学习情况发给家长"
                onClick={() => setReportOpen(true)}
              />
            ) : null}
            <AccountMenuItem
              icon={<TeamOutlined />}
              title="家庭陪伴"
              description="查看家庭成员与陪伴关系"
              onClick={() => navigate('/family')}
            />
            </>}
            <AccountMenuItem
              icon={<TrophyOutlined />}
              title="家庭任务"
              description="定目标、交作业、攒奖励"
              status={openFamilyTaskCount > 0 ? `${openFamilyTaskCount} 件待完成` : undefined}
              onClick={() => navigate('/family-tasks')}
            />
          </div>
        </section>

        <section className="sb-account-group" aria-labelledby="account-support-title">
          <h2 id="account-support-title">账户与支持</h2>
          <div className="sb-account-menu-card">
            <AccountMenuItem
              icon={<LockOutlined />}
              title="账号安全"
              description="修改登录密码"
              onClick={() => setDrawer('security')}
            />
            <AccountMenuItem
              icon={<InfoCircleOutlined />}
              title="帮助与更新"
              description={`了解${BRAND.name}的使用方式和最近更新`}
              onClick={() => navigate('/help')}
            />
            {install.visible ? (
              <AccountMenuItem
                icon={<MobileOutlined />}
                title="添加到主屏幕"
                description="像 App 一样从桌面直接进入"
                onClick={() => void install.trigger()}
              />
            ) : null}
            <AccountMenuItem
              icon={<LogoutOutlined />}
              title="退出登录"
              description="退出当前账号"
              danger
              onClick={confirmLogout}
            />
          </div>
        </section>
      </div>

      <Modal
        title="模式切换"
        open={modeModalOpen}
        onCancel={() => setModeModalOpen(false)}
        footer={null}
        width="min(92vw, 360px)"
      >
        <div className="sb-mode-options">
          <button
            type="button"
            className={`sb-mode-option${mode === 'study' ? ' active' : ''}`}
            onClick={() => void switchMode('study')}
          >
            <strong>学习模式</strong>
            <span>错题 / 试卷 / 笔记 / 每日记录 / 知识地图</span>
          </button>
          <button
            type="button"
            className={`sb-mode-option${mode === 'hobby' ? ' active' : ''}`}
            onClick={() => void switchMode('hobby')}
          >
            <strong>兴趣爱好模式</strong>
            <span>搜 B站资源推荐 · 陪练对话 · 计划笔记素材记录照常可用</span>
          </button>
        </div>
      </Modal>

      <Drawer
        className="sb-account-drawer"
        title="编辑个人资料"
        placement="bottom"
        height="auto"
        open={drawer === 'profile'}
        onClose={() => setDrawer(null)}
        destroyOnHidden
        closeIcon={<span aria-label="关闭">×</span>}
      >
        <Form form={profileForm} layout="vertical" onFinish={onSaveProfile}>
          <Form.Item
            name="display_name"
            label="显示名称"
            rules={[{ required: true, message: '请输入显示名称' }, { max: 64 }]}
          >
            <Input placeholder="如：哥哥 / 弟弟 / 你的称呼" />
          </Form.Item>
          <Form.Item name="avatar" label="头像链接" extra="可选，留空使用默认头像">
            <Input placeholder="https://..." />
          </Form.Item>
          <Button block type="primary" htmlType="submit" loading={savingProfile}>
            保存资料
          </Button>
        </Form>
      </Drawer>

      <Drawer
        className="sb-account-drawer"
        title="账号安全"
        placement="bottom"
        height="auto"
        open={drawer === 'security'}
        onClose={closeSecurityDrawer}
        destroyOnHidden
        closeIcon={<span aria-label="关闭">×</span>}
      >
        <Form form={pwdForm} layout="vertical" onFinish={onChangePassword}>
          <Form.Item name="old_password" label="当前密码" rules={[{ required: true, message: '请输入当前密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="当前密码" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, message: '至少 6 位' },
              { max: 64 },
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="新密码（至少 6 位）" />
          </Form.Item>
          <Form.Item name="confirm" label="确认新密码" rules={[{ required: true, message: '请再次输入新密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="再次输入新密码" />
          </Form.Item>
          <Button block type="primary" htmlType="submit" loading={savingPwd}>
            修改密码
          </Button>
        </Form>
      </Drawer>

      <Drawer
        className="sb-account-drawer sb-account-wechat-drawer"
        title="微信学习助手"
        placement="bottom"
        height="min(86dvh, 760px)"
        open={drawer === 'wechat'}
        onClose={() => setDrawer(null)}
        destroyOnHidden
        closeIcon={<span aria-label="关闭">×</span>}
      >
        {wechatAccount?.bound ? (
          <div className="sb-wechat-bound">
            <CheckCircleOutlined />
            <div>
              <Text strong>已绑定微信学习助手</Text>
              <Text type="secondary">{wechatAccount.openid_masked}</Text>
            </div>
            <Button danger loading={wechatLoading} onClick={onUnbindWechat}>
              解除绑定
            </Button>
          </div>
        ) : userId ? (
          <WechatBindingPanel userId={userId} onBound={onWechatBound} />
        ) : null}
        <div className="sb-wechat-privacy-note">
          <SafetyCertificateOutlined />
          <Text type="secondary">
            {BRAND.name}只能处理你主动发送给学习助手的消息，不会读取你的微信聊天记录、好友列表、朋友圈或支付信息。
          </Text>
        </div>
      </Drawer>

      <ReportProgressModal open={reportOpen} onClose={() => setReportOpen(false)} />
      <AddToHomeScreenGuide env={install.env} open={install.guideOpen} onClose={install.closeGuide} />
    </StudentPageShell>
  );
}
