import { useEffect, useState, useCallback } from 'react';
import {
  Card,
  Button,
  Skeleton,
  Empty,
  Typography,
  Space,
  Tag,
  Input,
  Rate,
  App,
} from 'antd';
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  ReloadOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { answerApi } from '@/features/exams/answer';
import type { PendingGradeItem } from '@/types';
import AppPageShell from '@/shared/components/AppPageShell';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

const typeLabel: Record<string, string> = {
  single_choice: '单选题',
  multi_choice: '多选题',
  fill_blank: '填空题',
  transform: '转换题',
  translation: '翻译题',
  essay: '简答题',
  math_answer: '解答题',
};

export default function GradingPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [pending, setPending] = useState<PendingGradeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [score, setScore] = useState<number>(0);
  const [comment, setComment] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const loadPending = useCallback(async () => {
    setLoading(true);
    try {
      const data = await answerApi.pending(100);
      setPending(data);
      // 重置当前批改状态
      if (data.length > 0) {
        setCurrentIdx(0);
      }
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '加载待批改列表失败';
      message.error(msg);
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    loadPending();
  }, [loadPending]);

  // 切换到新的待批改条目时，重置评分
  useEffect(() => {
    if (pending[currentIdx]) {
      setScore(0);
      setComment('');
    }
  }, [currentIdx, pending]);

  const handleGrade = async () => {
    const item = pending[currentIdx];
    if (!item) return;

    if (score <= 0) {
      message.warning('请先打分');
      return;
    }
    if (score > item.max_score) {
      message.warning(`分数不能超过满分 ${item.max_score} 分`);
      return;
    }

    setSubmitting(true);
    try {
      await answerApi.grade(item.answer_id, score, comment);
      message.success('批改成功');
      // 从列表中移除已批改项
      const newList = pending.filter((_, i) => i !== currentIdx);
      setPending(newList);
      // 调整索引
      if (currentIdx >= newList.length && newList.length > 0) {
        setCurrentIdx(newList.length - 1);
      }
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '批改失败，请重试';
      message.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleSkip = () => {
    if (currentIdx < pending.length - 1) {
      setCurrentIdx(currentIdx + 1);
    } else {
      setCurrentIdx(0);
    }
  };

  const current = pending[currentIdx];

  const pageActions = (
    <Space wrap>
      <Button icon={<ReloadOutlined />} onClick={loadPending} loading={loading}>
        刷新列表
      </Button>
    </Space>
  );

  if (loading) {
    return (
      <AppPageShell
        title="判分队列"
        subtitle="人工处理翻译、作文、解答题等主观题。"
        icon={<CheckCircleOutlined />}
        actions={pageActions}
        maxWidth={900}
      >
        <Card style={{ borderRadius: 12 }}>
          <Skeleton active paragraph={{ rows: 8 }} />
        </Card>
      </AppPageShell>
    );
  }

  if (pending.length === 0) {
    return (
      <AppPageShell
        title="判分队列"
        subtitle="人工处理翻译、作文、解答题等主观题。"
        icon={<CheckCircleOutlined />}
        actions={pageActions}
        metrics={[
          { label: '待批改', value: 0, hint: '当前没有主观题等待处理', tone: 'success' },
          { label: '处理状态', value: '清空', hint: '学生提交后会自动进入队列' },
        ]}
        maxWidth={900}
      >
        <Card style={{ borderRadius: 12 }}>
          <div className="sb-empty-state">
            <Empty
              image={
                <CheckCircleOutlined style={{ fontSize: 52, color: 'var(--sb-color-success)' }} />
              }
              description={
                <Space direction="vertical" size={4}>
                  <Text strong>暂无待人工判分题</Text>
                  <Text type="secondary">学生提交含主观题的试卷后，会自动进入这里等待批改</Text>
                </Space>
              }
            >
              <Space wrap>
                <Button icon={<ReloadOutlined />} onClick={loadPending}>
                  刷新列表
                </Button>
                <Button type="primary" onClick={() => navigate('/teacher/exams')}>
                  查看试卷
                </Button>
              </Space>
            </Empty>
          </div>
        </Card>
      </AppPageShell>
    );
  }

  return (
    <AppPageShell
      title="判分队列"
      subtitle="逐题批改学生提交的主观题，批完后会回填成绩和错题记录。"
      icon={<CheckCircleOutlined />}
      actions={pageActions}
      metrics={[
        { label: '待批改', value: pending.length, hint: '主观题数量', tone: 'warning' },
        { label: '当前进度', value: `${currentIdx + 1}/${pending.length}`, hint: current.student_name },
        { label: '本题满分', value: `${current.max_score} 分`, hint: typeLabel[current.question_type] ?? current.question_type },
      ]}
      maxWidth={900}
    >

      {/* 批改卡片 */}
      <Card style={{ borderRadius: 12 }} styles={{ body: { padding: 32 } }}>
        {/* 学生信息 */}
        <Space size={16} style={{ marginBottom: 20 }}>
          <Space>
            <UserOutlined style={{ color: 'var(--sb-color-text-secondary)' }} />
            <Text strong>{current.student_name}</Text>
          </Space>
          <Tag color="blue">{current.exam_title}</Tag>
          <Tag>{typeLabel[current.question_type] ?? current.question_type}</Tag>
          <ClockCircleOutlined style={{ color: 'var(--sb-color-text-secondary)' }} />
          <Text type="secondary" style={{ fontSize: 13 }}>
            提交于 {current.submitted_at.slice(0, 16).replace('T', ' ')}
          </Text>
        </Space>

        {/* 题目 */}
        <div style={{ marginBottom: 24 }}>
          <Text type="secondary" style={{ fontSize: 13 }}>
            题目
          </Text>
          <Paragraph
            style={{
              fontSize: 16,
              lineHeight: 1.7,
              marginTop: 8,
              padding: 16,
              background: 'var(--sb-color-bg-layout)',
              borderRadius: 8,
              whiteSpace: 'pre-wrap',
            }}
          >
            {current.question_stem}
          </Paragraph>
        </div>

        {/* 学生答案 */}
        <div style={{ marginBottom: 24 }}>
          <Text type="secondary" style={{ fontSize: 13 }}>
            学生答案
          </Text>
          <Paragraph
            style={{
              fontSize: 16,
              lineHeight: 1.7,
              marginTop: 8,
              padding: 16,
              background: 'var(--sb-color-bg-warning-soft)',
              border: '1px solid var(--sb-color-border-warning)',
              borderRadius: 8,
              whiteSpace: 'pre-wrap',
            }}
          >
            {current.student_answer || '（未作答）'}
          </Paragraph>
        </div>

        {/* 参考答案 */}
        <div style={{ marginBottom: 24 }}>
          <Text type="secondary" style={{ fontSize: 13 }}>
            参考答案
          </Text>
          <Paragraph
            style={{
              fontSize: 16,
              lineHeight: 1.7,
              marginTop: 8,
              padding: 16,
              background: 'var(--sb-color-bg-success-soft)',
              border: '1px solid var(--sb-color-border-success)',
              borderRadius: 8,
              whiteSpace: 'pre-wrap',
            }}
          >
            {current.reference_answer}
          </Paragraph>
        </div>

        {/* 评分区 */}
        <div
          style={{
            borderTop: '1px solid var(--sb-color-border-secondary)',
            paddingTop: 24,
          }}
        >
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <div>
              <Text strong style={{ marginRight: 16 }}>
                评分（满分 {current.max_score} 分）
              </Text>
              <Rate
                count={Math.ceil(current.max_score)}
                value={score}
                onChange={setScore}
                style={{ fontSize: 28 }}
              />
              <Text
                style={{
                  marginLeft: 12,
                  fontSize: 20,
                  fontWeight: 600,
                  color: score > 0 ? 'var(--sb-color-primary)' : 'var(--sb-color-text-secondary)',
                }}
              >
                {score} / {current.max_score}
              </Text>
            </div>

            <div>
              <Text type="secondary" style={{ fontSize: 13 }}>
                批改评语（可选）
              </Text>
              <TextArea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="给学生写评语，如：时态正确，但拼写需要改进…"
                autoSize={{ minRows: 3 }}
                style={{ marginTop: 8 }}
              />
            </div>

            <Space>
              <Button
                type="primary"
                size="large"
                icon={<CheckCircleOutlined />}
                loading={submitting}
                onClick={handleGrade}
              >
                提交批改
              </Button>
              <Button size="large" onClick={handleSkip}>
                跳过本题
              </Button>
            </Space>
          </Space>
        </div>
      </Card>
    </AppPageShell>
  );
}
