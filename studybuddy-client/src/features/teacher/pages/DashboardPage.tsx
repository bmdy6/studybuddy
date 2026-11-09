import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Typography, Row, Col, Statistic, Button, Space, Empty } from 'antd';
import { PageSpinner } from '../../../shared/components/PageSpinner';
import {
  FileTextOutlined,
  CheckSquareOutlined,
  TeamOutlined,
  ArrowRightOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import { examApi } from '@/features/exams/exam';
import { answerApi } from '@/features/exams/answer';
import { useAuth } from '@/features/auth/useAuth';
import type { ExamListItem, PendingGradeItem } from '@/types';

const { Title, Text } = Typography;

export default function DashboardPage() {
  const navigate = useNavigate();
  const { displayName } = useAuth();
  const [exams, setExams] = useState<ExamListItem[]>([]);
  const [pending, setPending] = useState<PendingGradeItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [examList, pendingList] = await Promise.all([examApi.list(), answerApi.pending(100)]);
        setExams(examList);
        setPending(pendingList);
      } catch {
        // 忽略错误，降级为空
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <PageSpinner padding={120} />
    );
  }

  const totalScore = exams.reduce((s, e) => s + e.total_score, 0);

  const quickActions = [
    {
      title: '判分队列',
      desc: `${pending.length} 题待批改`,
      icon: <CheckSquareOutlined style={{ fontSize: 28, color: 'var(--sb-color-warning)' }} />,
      path: '/teacher/grading',
      color: 'var(--sb-color-bg-warning-soft)',
    },
    {
      title: '试卷管理',
      desc: `共 ${exams.length} 套试卷`,
      icon: <FileTextOutlined style={{ fontSize: 28, color: 'var(--sb-color-primary)' }} />,
      path: '/teacher/exams',
      color: 'var(--sb-color-bg-info)',
    },
  ];

  return (
    <div className="fade-in" style={{ padding: '32px 40px', maxWidth: 1000, margin: '0 auto' }}>
      {/* 页头 */}
      <div style={{ marginBottom: 28 }}>
        <Title level={3} style={{ marginBottom: 4 }}>
          {displayName ? `${displayName}，欢迎回来` : '教学概览'}
        </Title>
        <Text type="secondary">管理试卷、批改作业、追踪学生进度</Text>
      </div>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 28 }}>
        <Col span={6}>
          <Card style={{ borderRadius: 12 }}>
            <Statistic
              title="试卷总数"
              value={exams.length}
              prefix={<FileTextOutlined style={{ color: 'var(--sb-color-primary)' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card style={{ borderRadius: 12 }}>
            <Statistic
              title="待批改"
              value={pending.length}
              prefix={<ClockCircleOutlined style={{ color: 'var(--sb-color-warning)' }} />}
              valueStyle={{ color: pending.length > 0 ? 'var(--sb-color-warning)' : undefined }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card style={{ borderRadius: 12 }}>
            <Statistic
              title="累计满分"
              value={totalScore}
              suffix="分"
              prefix={<TeamOutlined style={{ color: 'var(--sb-color-success)' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card style={{ borderRadius: 12 }}>
            <Statistic
              title="学生人数"
              value={1}
              suffix="人"
              prefix={<TeamOutlined style={{ color: 'var(--sb-color-primary)' }} />}
            />
          </Card>
        </Col>
      </Row>

      {/* 快捷操作 */}
      <Title level={5} style={{ marginBottom: 16 }}>
        快捷操作
      </Title>
      <Row gutter={[16, 16]} style={{ marginBottom: 28 }}>
        {quickActions.map((action) => (
          <Col key={action.title} span={12}>
            <Card
              className="app-card-hover"
              style={{ borderRadius: 12, cursor: 'pointer', height: '100%' }}
              onClick={() => navigate(action.path)}
            >
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <div
                  style={{
                    width: 56,
                    height: 56,
                    borderRadius: 14,
                    background: action.color,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  {action.icon}
                </div>
                <Title level={5} style={{ margin: 0 }}>
                  {action.title}
                </Title>
                <Text type="secondary">{action.desc}</Text>
                <Button type="link" size="small" style={{ padding: 0, marginTop: 4 }}>
                  进入 <ArrowRightOutlined />
                </Button>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 最近待批改 */}
      <Card
        title="最近待批改"
        style={{ borderRadius: 12 }}
        styles={{ body: { padding: 0 } }}
        extra={
          pending.length > 0 ? (
            <Button type="link" onClick={() => navigate('/teacher/grading')}>
              全部 <ArrowRightOutlined />
            </Button>
          ) : null
        }
      >
        {pending.length === 0 ? (
          <Empty description="暂无待批改题目" style={{ padding: 40 }} />
        ) : (
          <div style={{ padding: '8px 24px' }}>
            {pending.slice(0, 5).map((item) => (
              <div
                key={item.answer_id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '12px 0',
                  borderBottom: '1px solid var(--sb-color-border-subtle)',
                }}
              >
                <Space>
                  <Text strong>{item.student_name}</Text>
                  <Text type="secondary">{item.exam_title}</Text>
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    {item.question_stem.slice(0, 40)}
                    {item.question_stem.length > 40 ? '…' : ''}
                  </Text>
                </Space>
                <Space>
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    {item.submitted_at.slice(0, 10)}
                  </Text>
                  <Button type="link" size="small" onClick={() => navigate('/teacher/grading')}>
                    批改
                  </Button>
                </Space>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
