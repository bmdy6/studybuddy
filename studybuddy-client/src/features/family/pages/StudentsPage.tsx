/**
 * 学生管理页（parent 专属）。
 *
 * 学生列表 → 点击进详情页（该学生的属性面板/学情/错题 tab）
 */

import { useEffect, useState } from 'react';
import { Avatar, Button, Empty, List, Space, Tag, Typography } from 'antd';
import { PageSpinner } from '../../../shared/components/PageSpinner';
import {
  ArrowRightOutlined,
  MessageOutlined,
  UserAddOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/features/auth/store';

const { Text, Title } = Typography;

export default function StudentsPage() {
  const { children } = useAuthStore();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // children 来自 authStore，登录时已加载
    setLoading(false);
  }, [children]);

  if (loading) {
    return (
      <PageSpinner />
    );
  }

  return (
    <div className="sb-page-shell fade-in" style={{ maxWidth: 900 }}>
      <div className="sb-page-header">
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>
            我的孩子
          </Title>
          <Text type="secondary">集中查看学习档案、学情诊断和错题进展</Text>
        </div>
        <div className="sb-page-header-actions">
          <Button icon={<MessageOutlined />} onClick={() => navigate('/chat')}>
            去对话页
          </Button>
          <Button type="primary" icon={<UserAddOutlined />} disabled>
            绑定孩子
          </Button>
        </div>
      </div>

      {children.length === 0 ? (
        <div
          className="sb-empty-state"
          style={{ background: 'var(--sb-color-white)', borderRadius: 12 }}
        >
          <Empty
            image={<UserOutlined style={{ fontSize: 52, color: 'var(--sb-color-attr-neutral)' }} />}
            description={
              <Space direction="vertical" size={4}>
                <Text strong>还没有绑定孩子</Text>
                <Text type="secondary">绑定后这里会显示学习概览、错题和笔记入口</Text>
              </Space>
            }
          >
            <Button type="primary" icon={<MessageOutlined />} onClick={() => navigate('/chat')}>
              先去对话页了解流程
            </Button>
          </Empty>
        </div>
      ) : (
        <List
          dataSource={children}
          renderItem={(child) => (
            <List.Item
              className="sb-action-card"
              style={{ marginBottom: 12 }}
              onClick={() => navigate(`/students/${child.id}`)}
              actions={[
                <Button key="open" type="link" icon={<ArrowRightOutlined />}>
                  查看
                </Button>,
              ]}
            >
              <List.Item.Meta
                avatar={
                  <Avatar
                    size={52}
                    icon={<UserOutlined />}
                    style={{ background: 'var(--sb-color-primary)' }}
                  />
                }
                title={
                  <Space size={8} wrap>
                    <Text strong style={{ fontSize: 16 }}>
                      {child.display_name}
                    </Text>
                    <Tag color="blue">学习档案</Tag>
                  </Space>
                }
                description={<Text type="secondary">学情诊断、错题本、笔记和素材都从这里进入</Text>}
              />
            </List.Item>
          )}
        />
      )}
    </div>
  );
}
