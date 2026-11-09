import { useState } from 'react';
import { Card, Form, Input, Button, Typography, Divider } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '@/features/auth/useAuth';
import { BRAND } from '@/shared/constants';
import type { LoginRequest, RegisterFormValues } from '@/types';

const { Title, Text } = Typography;

interface LocationState {
  from?: string;
}

export default function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [form] = Form.useForm<LoginRequest & Partial<RegisterFormValues>>();

  const from = (location.state as LocationState | null)?.from ?? '/';

  const onFinish = async (values: LoginRequest & Partial<RegisterFormValues>) => {
    setLoading(true);
    const ok =
      mode === 'register'
        ? await register({ username: values.username, password: values.password })
        : await login({ username: values.username, password: values.password });
    setLoading(false);
    if (ok) {
      navigate(from, { replace: true });
    }
  };

  const switchMode = (nextMode: 'login' | 'register') => {
    setMode(nextMode);
    form.setFields([{ name: 'confirmPassword', errors: [] }]);
  };

  return (
    <div className="sb-login-page">
      <div className="sb-login-brand">
        <div className="sb-login-mark">{BRAND.name[0]}</div>
        <Title level={1} className="sb-login-title">
          {BRAND.name}
        </Title>
        <Text className="sb-login-copy">
          家庭学习工具：家长出题、孩子答题，AI 帮你整理错题与每日反馈。
        </Text>
      </div>

      <Card
        className="sb-login-card"
        styles={{ body: { padding: 36 } }}
      >
        <div className="sb-login-card-head">
          <div className="sb-login-card-mark">{BRAND.name[0]}</div>
          <Title level={3} className="sb-login-card-title">
            {mode === 'login' ? '开始学习' : '创建学生账号'}
          </Title>
          <Text type="secondary">
            {mode === 'login' ? '输入账号密码，进入今天的学习桌面' : '注册后会直接登录，并在这台设备保持 30 天'}
          </Text>
        </div>

        <Form<LoginRequest & Partial<RegisterFormValues>>
          form={form}
          name="auth"
          onFinish={onFinish}
          size="large"
          autoComplete="off"
          requiredMark={false}
        >
          <Form.Item
            name="username"
            rules={[
              { required: true, message: '请输入用户名' },
              { max: 64, message: '用户名不能超过 64 个字符' },
            ]}
          >
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>

          <Form.Item
            name="password"
            rules={[
              { required: true, message: '请输入密码' },
              ...(mode === 'register' ? [{ min: 6, message: '密码至少需要 6 位' }] : []),
            ]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder={mode === 'register' ? '密码（至少 6 位）' : '密码'}
              autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
            />
          </Form.Item>

          {mode === 'register' && (
            <Form.Item
              name="confirmPassword"
              dependencies={['password']}
              rules={[
                { required: true, message: '请再次输入密码' },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    if (!value || getFieldValue('password') === value) return Promise.resolve();
                    return Promise.reject(new Error('两次输入的密码不一致'));
                  },
                }),
              ]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder="再次输入密码"
                autoComplete="new-password"
              />
            </Form.Item>
          )}

          <Form.Item style={{ marginBottom: 0 }}>
            <Button
              type="primary"
              htmlType="submit"
              block
              loading={loading}
              aria-label={mode === 'register' ? '注册并进入' : '登录'}
              style={{ height: 44, fontWeight: 500 }}
            >
              {mode === 'register' ? '注册并进入' : '登录'}
            </Button>
          </Form.Item>
        </Form>

        <Divider style={{ margin: '24px 0', borderColor: 'var(--sb-color-border-secondary)' }} />
        <div className="sb-login-switch">
          <Text type="secondary">{mode === 'login' ? '还没有账号？' : '已经有账号？'}</Text>
          <Button
            type="link"
            className="sb-login-switch-action"
            aria-label={mode === 'login' ? '注册账号' : '返回登录'}
            onClick={() => switchMode(mode === 'login' ? 'register' : 'login')}
          >
            {mode === 'login' ? '注册账号' : '返回登录'}
          </Button>
        </div>
      </Card>
    </div>
  );
}
