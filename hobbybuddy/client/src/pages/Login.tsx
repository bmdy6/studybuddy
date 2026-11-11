import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Form, Input, Tabs, Typography, message } from 'antd';
import { register, login } from '../api';
import { setToken } from '../main';

const { Title, Text } = Typography;

export default function LoginPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: {
    username: string;
    password: string;
  }) => {
    setLoading(true);
    try {
      const result = await login(values.username, values.password);
      setToken(result.access_token);
      navigate('/chat');
    } catch (err: unknown) {
      message.error('登录失败，请检查账号密码');
    } finally {
      setLoading(false);
    }
  };

  const onRegister = async (values: {
    username: string;
    password: string;
  }) => {
    setLoading(true);
    try {
      await register(values.username, values.password);
      message.success('注册成功，请登录');
    } catch (err: unknown) {
      message.error('注册失败，用户名可能已存在');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        height: '100dvh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
        background: 'var(--sb-color-bg-app)',
      }}
    >
      <Card style={{ width: '100%', maxWidth: 360 }} styles={{ body: { padding: 28 } }}>
        <Title level={3} style={{ marginTop: 0, marginBottom: 4 }}>
          趣爱好
        </Title>
        <Text type="secondary" style={{ display: 'block', marginBottom: 20 }}>
          把喜欢的事，练成作品。这里不判分、不打分，只陪你找资源、做记录。
        </Text>
        <Tabs
          items={[
            {
              key: 'login',
              label: '登录',
              children: (
                <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
                  <Form.Item
                    name="username"
                    label="用户名"
                    rules={[{ required: true, message: '请输入用户名' }]}
                  >
                    <Input autoComplete="username" placeholder="用户名" />
                  </Form.Item>
                  <Form.Item
                    name="password"
                    label="密码"
                    rules={[{ required: true, message: '请输入密码' }]}
                  >
                    <Input.Password autoComplete="current-password" placeholder="密码" />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block loading={loading}>
                    登录
                  </Button>
                </Form>
              ),
            },
            {
              key: 'register',
              label: '注册',
              children: (
                <Form layout="vertical" onFinish={onRegister} requiredMark={false}>
                  <Form.Item
                    name="username"
                    label="用户名"
                    rules={[{ required: true, min: 3, message: '用户名至少 3 个字符' }]}
                  >
                    <Input autoComplete="username" placeholder="用户名" />
                  </Form.Item>
                  <Form.Item
                    name="password"
                    label="密码"
                    rules={[{ required: true, min: 6, message: '密码至少 6 位' }]}
                  >
                    <Input.Password autoComplete="new-password" placeholder="密码" />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block loading={loading}>
                    注册
                  </Button>
                </Form>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
