/**
 * 学生详情页（parent 点击学生后进入）。
 *
 * Tab 切换：属性面板 / 学情诊断 / 错题本
 * 复用 ProfilePage 的属性面板展示逻辑
 */

import { useEffect, useState, type ReactNode } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Alert, Avatar, Button, Card, Col, Empty, Row, Space, Spin, Tabs, Tag, Typography } from 'antd';
import { PageSpinner } from '../../../shared/components/PageSpinner';
import {
  ArrowLeftOutlined,
  BarChartOutlined,
  BookOutlined,
  CheckCircleOutlined,
  MessageOutlined,
  SendOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { p2Api } from '@/features/p2/api';
import { supervisionApi } from '@/features/growth/supervision';
import { useAuthStore } from '@/features/auth/store';
import type { AttributeSnapshot, SupervisionSummaryResponse } from '@/types';

const { Text, Title } = Typography;

export default function StudentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { children } = useAuthStore();
  const studentId = Number(id);
  const [attrs, setAttrs] = useState<AttributeSnapshot | null>(null);
  const [studentName, setStudentName] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!studentId) return;
    (async () => {
      try {
        const attrResp = await p2Api.getAttributes(studentId);
        setAttrs(attrResp.current);
        const found = children?.find((s) => s.id === studentId);
        setStudentName(found?.display_name ?? `学生 #${studentId}`);
      } catch {
        // 忽略
      } finally {
        setLoading(false);
      }
    })();
  }, [studentId, children]);

  if (loading) {
    return (
      <PageSpinner />
    );
  }

  return (
    <div className="sb-page-shell fade-in" style={{ maxWidth: 1000 }}>
      <Button
        type="text"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate('/students')}
        style={{ marginBottom: 16, padding: '4px 0' }}
      >
        返回学生列表
      </Button>
      <div className="sb-student-cover">
        <div className="sb-page-header" style={{ marginBottom: 24 }}>
          <Space size={16} align="center">
            <Avatar className="sb-student-avatar" size={64} icon={<UserOutlined />} />
            <div>
              <Space size={8} wrap>
                <Title className="sb-student-title" level={3} style={{ margin: 0 }}>
                  {studentName}
                </Title>
                <Tag className="sb-student-tag">学生档案</Tag>
              </Space>
              <div style={{ marginTop: 6 }}>
                <Text className="sb-student-subtitle">从学情、错题、笔记三个角度跟踪学习状态</Text>
              </div>
            </div>
          </Space>
          <div className="sb-page-header-actions">
            <Button
              icon={<MessageOutlined />}
              onClick={() => navigate(`/chat?student_id=${studentId}`)}
            >
              去对话页
            </Button>
          </div>
        </div>
        <StudentMetrics attrs={attrs} />
      </div>

      <StudentDashboard
        attrs={attrs}
        onChat={() => navigate(`/chat?student_id=${studentId}`)}
        onNotes={() => navigate(`/notes?student_id=${studentId}`)}
      />

      <Card className="sb-detail-tabs" style={{ borderRadius: 12 }}>
        <Tabs
          items={[
            {
              key: 'profile',
              label: '学习档案',
              children: <AttributesView attrs={attrs} />,
            },
            {
              key: 'diagnosis',
              label: '学情诊断',
              children: <DiagnosisView studentId={studentId} />,
            },
            {
              key: 'error-book',
              label: '错题本',
              children: <ErrorBookView studentId={studentId} />,
            },
            {
              key: 'notes',
              label: '笔记',
              children: (
                <div className="sb-empty-state sb-empty-state-compact">
                  <Empty
                    image={
                      <BookOutlined
                        style={{ fontSize: 48, color: 'var(--sb-color-attr-neutral)' }}
                      />
                    }
                    description={
                      <Space direction="vertical" size={4}>
                        <Text strong>学习笔记集中在笔记页</Text>
                        <Text type="secondary">可查看学习记录、盲区关联和确认状态</Text>
                      </Space>
                    }
                  >
                    <Button
                      type="primary"
                      onClick={() => navigate(`/notes?student_id=${studentId}`)}
                    >
                      查看笔记
                    </Button>
                  </Empty>
                </div>
              ),
            },
            {
              key: 'supervision',
              label: '督促面板',
              children: <SupervisionPanel studentId={studentId} onAssign={() => navigate('/teacher/exams')} />,
            },
          ]}
        />
      </Card>
    </div>
  );
}

function SupervisionPanel({
  studentId,
  onAssign,
}: {
  studentId: number;
  onAssign: () => void;
}) {
  const [summary, setSummary] = useState<SupervisionSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    supervisionApi
      .summary(studentId)
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          '加载督促面板失败';
        setError(msg);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [studentId]);

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '44px 0' }}>
        <Spin />
      </div>
    );
  }

  if (error) {
    return <Alert type="error" showIcon message={error} />;
  }

  if (!summary) {
    return <Empty description="暂时没有督促数据" />;
  }

  const metricItems = [
    { label: '待提醒计划', value: summary.reminders.length, tone: 'warning' },
    { label: '薄弱知识点', value: summary.weak_points.length, tone: 'danger' },
    { label: '最近分发', value: summary.recent_assignments.length, tone: 'default' },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Row gutter={[12, 12]}>
        {metricItems.map((item) => (
          <Col xs={24} md={8} key={item.label}>
            <div
              style={{
                border: '1px solid var(--sb-color-border-warm)',
                borderRadius: 10,
                padding: '14px 16px',
                background: 'var(--sb-color-white)',
              }}
            >
              <Text type="secondary">{item.label}</Text>
              <div style={{ marginTop: 8 }}>
                <Text strong style={{ fontSize: 24, color: 'var(--sb-color-text)' }}>
                  {item.value}
                </Text>
              </div>
            </div>
          </Col>
        ))}
      </Row>

      <Row gutter={[12, 12]}>
        <Col xs={24} lg={12}>
          <SupervisionSection title="需要提醒" emptyText="目前没有待提醒计划">
            {summary.reminders.map((item) => (
              <SupervisionLine
                key={item.plan_id}
                title={item.title}
                desc={item.reminder_message}
                tag={item.is_overdue ? `逾期 ${item.overdue_days} 天` : `${item.todo_minutes} 分钟`}
              />
            ))}
          </SupervisionSection>
        </Col>
        <Col xs={24} lg={12}>
          <SupervisionSection title="学生自己写的督促点" emptyText="最近每日回顾里没有写督促点">
            {summary.support_items.map((item) => (
              <SupervisionLine key={item.note_id} title={item.title} desc={item.content} tag="每日回顾" />
            ))}
          </SupervisionSection>
        </Col>
        <Col xs={24} lg={12}>
          <SupervisionSection title="高频薄弱点" emptyText="暂时没有高频薄弱点">
            {summary.weak_points.map((item) => (
              <SupervisionLine
                key={item.tag}
                title={item.tag}
                desc={item.next_action}
                tag={`错 ${item.error_count} 次`}
              />
            ))}
          </SupervisionSection>
        </Col>
        <Col xs={24} lg={12}>
          <SupervisionSection
            title="最近分发"
            emptyText="还没有定向分发记录"
            extra={
              <Button size="small" icon={<SendOutlined />} onClick={onAssign}>
                去分发试卷
              </Button>
            }
          >
            {summary.recent_assignments.map((item) => (
              <SupervisionLine
                key={item.assignment_id}
                title={item.exam_title}
                desc={item.note || (item.due_at ? `截止 ${item.due_at}` : '已分发给该学生')}
                tag={assignmentStatusLabel(item.status)}
              />
            ))}
          </SupervisionSection>
        </Col>
      </Row>

      <Card
        title={summary.weekly_report.title}
        size="small"
        style={{ borderRadius: 10 }}
        extra={
          summary.weekly_report.sources.length > 0 ? (
            <Space size={4} wrap>
              {summary.weekly_report.sources.map((source) => (
                <Tag key={source}>{source}</Tag>
              ))}
            </Space>
          ) : null
        }
      >
        <Text type="secondary">{summary.weekly_report.summary}</Text>
        {summary.weekly_report.highlights.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              {summary.weekly_report.highlights.map((item) => (
                <div key={item} style={{ color: 'var(--sb-color-text)' }}>
                  {item}
                </div>
              ))}
            </Space>
          </div>
        )}
        {summary.weekly_report.next_suggestions.length > 0 && (
          <div
            style={{
              marginTop: 12,
              paddingTop: 12,
              borderTop: '1px solid var(--sb-color-border-warm)',
            }}
          >
            <Text strong>下一步建议</Text>
            <Space direction="vertical" size={6} style={{ width: '100%', marginTop: 8 }}>
              {summary.weekly_report.next_suggestions.map((item) => (
                <Text key={item} type="secondary">
                  {item}
                </Text>
              ))}
            </Space>
          </div>
        )}
      </Card>
    </Space>
  );
}

function SupervisionSection({
  title,
  emptyText,
  extra,
  children,
}: {
  title: string;
  emptyText: string;
  extra?: ReactNode;
  children: ReactNode;
}) {
  const childArray = Array.isArray(children) ? children.filter(Boolean) : children ? [children] : [];
  return (
    <Card
      title={title}
      size="small"
      style={{ borderRadius: 10, height: '100%' }}
      extra={extra}
      styles={{ body: { minHeight: 130 } }}
    >
      {childArray.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />
      ) : (
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          {children}
        </Space>
      )}
    </Card>
  );
}

function SupervisionLine({
  title,
  desc,
  tag,
}: {
  title: string;
  desc: string;
  tag: string;
}) {
  return (
    <div
      style={{
        paddingBottom: 10,
        borderBottom: '1px solid var(--sb-color-border-subtle)',
      }}
    >
      <Space size={8} wrap style={{ marginBottom: 4 }}>
        <Text strong>{title}</Text>
        <Tag>{tag}</Tag>
      </Space>
      <div style={{ color: 'var(--sb-color-text-muted)', fontSize: 13, lineHeight: 1.6 }}>
        {desc}
      </div>
    </div>
  );
}

function assignmentStatusLabel(status: string): string {
  if (status === 'assigned') return '已分发';
  if (status === 'started') return '已开始';
  if (status === 'submitted') return '已提交';
  return status;
}

function StudentDashboard({
  attrs,
  onChat,
  onNotes,
}: {
  attrs: AttributeSnapshot | null;
  onChat: () => void;
  onNotes: () => void;
}) {
  const ready = Boolean(attrs);
  return (
    <div className="sb-dashboard-grid">
      <div className="sb-workbench-panel">
        <Space direction="vertical" size={4} style={{ marginBottom: 14 }}>
          <Text className="sb-side-title" strong>
            下一步建议
          </Text>
          <Text className="sb-muted-copy">
            把学生详情页当成家长的决策台：先看状态，再让助手继续处理。
          </Text>
        </Space>
        <div className="sb-suggestion-grid">
          <div className="sb-action-card sb-action-card-primary" onClick={onChat}>
            <div className="sb-action-card-body">
              <span className="sb-action-icon">
                <BarChartOutlined />
              </span>
              <div className="sb-action-text">
                <Text className="sb-action-title" strong>
                  {ready ? '复盘当前档案' : '初始化学习档案'}
                </Text>
                <div className="sb-action-desc">
                  {ready ? '让助手解释分数变化' : '先生成语数英基础画像'}
                </div>
              </div>
            </div>
          </div>
          <div className="sb-action-card" onClick={onChat}>
            <div className="sb-action-card-body">
              <span className="sb-action-icon">
                <BookOutlined />
              </span>
              <div className="sb-action-text">
                <Text className="sb-action-title" strong>
                  整理错题
                </Text>
                <div className="sb-action-desc">按知识点找重复错误</div>
              </div>
            </div>
          </div>
          <div className="sb-action-card" onClick={onNotes}>
            <div className="sb-action-card-body">
              <span className="sb-action-icon">
                <MessageOutlined />
              </span>
              <div className="sb-action-text">
                <Text className="sb-action-title" strong>
                  查看笔记
                </Text>
                <div className="sb-action-desc">检查学习记录和盲区关联</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="sb-workbench-side">
        <Text className="sb-side-title" strong>
          最近动态
        </Text>
        <div className="sb-activity-list">
          <div className="sb-activity-item">
            <CheckCircleOutlined style={{ color: 'var(--sb-color-primary)', marginTop: 3 }} />
            <div>
              <Text className="sb-activity-title" strong>
                档案状态
              </Text>
              <div className="sb-activity-desc">
                {ready ? '已有学习档案，可继续对话复盘' : '尚未初始化，建议先生成一次档案'}
              </div>
            </div>
          </div>
          <div className="sb-activity-item">
            <BookOutlined style={{ color: 'var(--sb-color-primary)', marginTop: 3 }} />
            <div>
              <Text className="sb-activity-title" strong>
                错题与笔记
              </Text>
              <div className="sb-activity-desc">做题和导入错题后会在这里形成连续追踪</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StudentMetrics({ attrs }: { attrs: AttributeSnapshot | null }) {
  const snap = attrs?.snapshot;
  const sources = snap?.subject_sources ?? {};
  const subjectKeys = ['chinese', 'math', 'english', 'pe', 'engagement'] as const;
  const evidencedValues = subjectKeys
    .map((k) => (sources[k] ? snap?.[k] : undefined))
    .filter((v): v is number => v !== undefined && v !== null);
  // 仅当全部能力项都有真实证据时才计算综合均值，否则显示数据不足
  const average =
    snap && evidencedValues.length === subjectKeys.length
      ? Math.round(evidencedValues.reduce((sum, v) => sum + v, 0) / evidencedValues.length)
      : null;
  const metrics = [
    {
      label: '综合状态',
      value: average === null ? '数据不足' : `${average}`,
      hint: average === null ? '录入大考成绩后显示' : '五项能力均值',
      icon: <BarChartOutlined />,
    },
    {
      label: '已掌握',
      value: snap && snap.mastered_count != null ? `${snap.mastered_count}` : '待生成',
      hint: '知识点数量',
      icon: <CheckCircleOutlined />,
    },
    {
      label: '学习投入',
      value: sources.engagement && snap ? `${snap.engagement}` : '数据不足',
      hint: '根据练习反馈更新',
      icon: <BookOutlined />,
    },
  ];

  return (
    <Row gutter={[12, 12]}>
      {metrics.map((item) => (
        <Col xs={24} md={8} key={item.label}>
          <div
            style={{
              padding: '4px 0 4px 16px',
              borderLeft: '2px solid var(--sb-color-border-warm)',
              height: '100%',
            }}
          >
            <Space direction="vertical" size={6}>
              <Space>
                <span style={{ color: 'var(--sb-color-primary)' }}>{item.icon}</span>
                <Text type="secondary">{item.label}</Text>
              </Space>
              <Text strong style={{ fontSize: 24, color: 'var(--sb-color-text)' }}>
                {item.value}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {item.hint}
              </Text>
            </Space>
          </div>
        </Col>
      ))}
    </Row>
  );
}

/** 属性面板视图（复用 ProfilePage 的展示逻辑，简化版） */
function AttributesView({ attrs }: { attrs: AttributeSnapshot | null }) {
  if (!attrs) {
    return (
      <div className="sb-empty-state sb-empty-state-compact">
        <Empty
          image={
            <BarChartOutlined style={{ fontSize: 48, color: 'var(--sb-color-attr-neutral)' }} />
          }
          description={
            <Space direction="vertical" size={4}>
              <Text strong>学习档案尚未初始化</Text>
              <Text type="secondary">
                去对话页让助手初始化档案，例如输入“帮这个学生初始化学习档案”
              </Text>
            </Space>
          }
        />
      </div>
    );
  }
  const snap = attrs.snapshot;
  const sources = snap.subject_sources ?? {};
  const attrs_list: [string, 'chinese' | 'math' | 'english' | 'pe' | 'engagement'][] = [
    ['语文', 'chinese'],
    ['数学', 'math'],
    ['英语', 'english'],
    ['体育', 'pe'],
    ['学习投入度', 'engagement'],
  ];
  return (
    <div>
      {attrs_list.map(([label, key]) => {
        const evidenced = Boolean(sources[key]);
        const val = snap[key];
        return (
          <div key={label} style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <Typography.Text>{label}</Typography.Text>
              {evidenced && val != null ? (
                <Typography.Text
                  strong
                  style={{
                    color: val >= 80 ? 'var(--sb-color-success-strong)' : 'var(--sb-color-text)',
                  }}
                >
                  {val}
                </Typography.Text>
              ) : (
                <Typography.Text style={{ fontSize: 12, color: 'var(--sb-color-text-tertiary)' }}>
                  数据不足
                </Typography.Text>
              )}
            </div>
            <div
              style={{
                height: 8,
                background: 'var(--sb-color-track)',
                borderRadius: 4,
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: `${evidenced && val != null ? Math.min(100, val) : 0}%`,
                  height: '100%',
                  background:
                    evidenced && val != null && val >= 80
                      ? 'var(--sb-color-success-strong)'
                      : 'var(--sb-color-attr-neutral)',
                  borderRadius: 4,
                  transition: 'width 0.6s ease',
                }}
              />
            </div>
          </div>
        );
      })}
      <div
        style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--sb-color-bg-muted)' }}
      >
        <Typography.Text type="secondary">已掌握知识点</Typography.Text>
        {!snap.mastered_count ? (
          <div style={{ marginTop: 4 }}>
            <Typography.Text
              strong
              style={{ fontSize: 20, color: 'var(--sb-color-text-tertiary)' }}
            >
              暂无
            </Typography.Text>
            <div style={{ fontSize: 12, color: 'var(--sb-color-text-tertiary)', marginTop: 2 }}>
              还没有做过题或题目尚未判分，做题后这里会显示已掌握的知识点
            </div>
          </div>
        ) : (
          <Typography.Text
            strong
            style={{ fontSize: 20, marginLeft: 8, color: 'var(--sb-color-success-strong)' }}
          >
            {snap.mastered_count} 个
          </Typography.Text>
        )}
      </div>
    </div>
  );
}

function DiagnosisView({ studentId }: { studentId: number }) {
  return (
    <div className="sb-empty-state sb-empty-state-compact">
      <Empty
        image={<BarChartOutlined style={{ fontSize: 48, color: 'var(--sb-color-attr-neutral)' }} />}
        description={
          <Space direction="vertical" size={4}>
            <Text strong>学情诊断由对话助手聚合</Text>
            <Text type="secondary">在对话页询问“查一下这个学生的学情诊断”</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              student_id: {studentId}
            </Text>
          </Space>
        }
      />
    </div>
  );
}

function ErrorBookView({ studentId }: { studentId: number }) {
  return (
    <div className="sb-empty-state sb-empty-state-compact">
      <Empty
        image={<BookOutlined style={{ fontSize: 48, color: 'var(--sb-color-attr-neutral)' }} />}
        description={
          <Space direction="vertical" size={4}>
            <Text strong>错题会按知识点沉淀</Text>
            <Text type="secondary">在对话页询问“查一下这个学生的错题”</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              student_id: {studentId}
            </Text>
          </Space>
        }
      />
    </div>
  );
}
