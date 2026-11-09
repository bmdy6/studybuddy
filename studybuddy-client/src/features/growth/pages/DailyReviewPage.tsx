import { useEffect, useMemo, useState } from 'react';
import { App, Button, Card, Checkbox, DatePicker, Empty, Form, Input, List, Space, Spin, Tag, Typography } from 'antd';
import { CheckCircleOutlined, HistoryOutlined, MessageOutlined, PlusOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import dayjs, { type Dayjs } from 'dayjs';
import { noteApi } from '@/features/note/api';
import { useAuthStore, getActiveStudentId } from '@/features/auth/store';
import type { NoteItem } from '@/types';

const { Title, Text, Paragraph } = Typography;

interface DailyReviewFormValues {
  summary: string;
  goals: GoalItem[];
  support?: string;
}

export interface GoalItem {
  id: string;
  text: string;
  done: boolean;
}

// 日期展示格式与笔记标题、Markdown 内容保持一致。
export const DAY_LABEL_FORMAT = 'YYYY.M.D';

function formatDayLabel(value: Dayjs) {
  return value.format(DAY_LABEL_FORMAT);
}

export function buildDailyReviewContent(
  values: DailyReviewFormValues,
  reviewDate: Dayjs,
) {
  const reviewLabel = formatDayLabel(reviewDate);
  const targetDate = reviewDate.add(1, 'day');
  const targetLabel = formatDayLabel(targetDate);
  const support = values.support?.trim();

  const goalLines = values.goals
    .map((goal) => ({ ...goal, text: goal.text.trim() }))
    .filter((goal) => goal.text)
    .map((goal) => `- [${goal.done ? 'x' : ' '}] ${goal.text.replace(/^[-*]\s*(\[[ xX]\]\s*)?/, '')}`);

  return [
    `## 昨日回顾（${reviewLabel}）`,
    '',
    values.summary.trim(),
    '',
    `## 今日目标（${targetLabel}）`,
    '',
    goalLines.join('\n'),
    ...(support ? ['', '## 需要督促的地方', '', support] : []),
  ].join('\n');
}

export function buildGoalPlanPrompt(goalText: string) {
  return `我今天的目标是：${goalText.trim()}。请先和我商量这个目标怎么安排，确认学习时长、任务拆分和可行性后，再帮我创建学习计划。没有我明确确认前，不要直接创建计划。`;
}

function isDailyReview(note: NoteItem) {
  return note.category === '每日回顾' || note.source === '每日回顾';
}

function getPreview(content: string) {
  return content
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 96);
}

export default function DailyReviewPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const authState = useAuthStore();
  const studentId = getActiveStudentId(authState);
  const [saving, setSaving] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [reviewHistory, setReviewHistory] = useState<NoteItem[]>([]);
  const [values, setValues] = useState<DailyReviewFormValues>({
    summary: '',
    goals: [],
    support: '',
  });
  const today = useMemo(() => dayjs(), []);
  const [reviewDate, setReviewDate] = useState<Dayjs>(() => today.subtract(1, 'day'));
  const [goalDraft, setGoalDraft] = useState('');
  const targetDate = useMemo(() => reviewDate.add(1, 'day'), [reviewDate]);
  const reviewLabel = formatDayLabel(reviewDate);
  const targetLabel = formatDayLabel(targetDate);

  const loadHistory = async () => {
    if (!studentId) {
      setReviewHistory([]);
      return;
    }
    setHistoryLoading(true);
    try {
      const notes = await noteApi.list(studentId);
      setReviewHistory(notes.filter(isDailyReview).slice(0, 8));
    } catch {
      message.error('加载最近回顾失败');
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    loadHistory();
  }, [studentId]); // eslint-disable-line react-hooks/exhaustive-deps

  const updateField = (field: keyof DailyReviewFormValues, value: string) => {
    setValues((current) => ({ ...current, [field]: value }));
  };

  const addGoal = () => {
    const text = goalDraft.trim();
    if (!text) return;
    setValues((current) => ({
      ...current,
      goals: [...current.goals, { id: `${Date.now()}-${current.goals.length}`, text, done: false }],
    }));
    setGoalDraft('');
  };

  const toggleGoal = (id: string) => {
    setValues((current) => ({
      ...current,
      goals: current.goals.map((goal) => (
        goal.id === id ? { ...goal, done: !goal.done } : goal
      )),
    }));
  };

  const openGoalPlanChat = (goal: GoalItem) => {
    if (!studentId) {
      message.error('没有找到当前学生账号');
      return;
    }
    const params = new URLSearchParams({
      student_id: String(studentId),
      prompt: buildGoalPlanPrompt(goal.text),
    });
    navigate(`/chat?${params.toString()}`);
  };

  const handleSave = async () => {
    if (!studentId) {
      message.error('没有找到当前学生账号');
      return;
    }
    if (!values.summary.trim()) {
      message.error('写一点昨日回顾');
      return;
    }
    if (!values.goals.some((goal) => goal.text.trim())) {
      message.error('写一点今日目标');
      return;
    }
    setSaving(true);
    try {
      const note = await noteApi.create({
        student_id: studentId,
        title: `${targetLabel} 每日回顾`,
        subject: '其他',
        category: '每日回顾',
        content: buildDailyReviewContent(values, reviewDate),
        knowledge_tags: ['每日回顾', '目标'],
        source: '每日回顾',
        source_ref: [],
        status: 'confirmed',
      });
      if (note.status !== 'confirmed') {
        await noteApi.update(note.id, { status: 'confirmed' });
      }
      message.success('已保存到笔记');
      navigate(`/notes/${note.id}`);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '保存每日回顾失败';
      message.error(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="sb-daily-review-shell">
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <div>
          <Title level={3} style={{ marginBottom: 8 }}>
            每日回顾
          </Title>
          <Paragraph type="secondary" style={{ margin: 0 }}>
            每天花 3 分钟写下昨日回顾和今日目标，助手会用这些记录帮你复盘和督促。
          </Paragraph>
        </div>

        <Card
          variant="borderless"
          className="sb-daily-review-card"
          styles={{ body: { padding: 24 } }}
        >
          <div className="sb-daily-review-head">
            <div className="sb-date-chip-group">
              <Tag className="sb-date-chip sb-date-chip--review">回顾 {reviewLabel}</Tag>
              <Tag className="sb-date-chip sb-date-chip--target">目标 {targetLabel}</Tag>
            </div>
            <DatePicker
              aria-label="回顾日期"
              id="daily-review-review-date"
              value={reviewDate}
              onChange={(value) => value && setReviewDate(value)}
              allowClear={false}
              format={DAY_LABEL_FORMAT}
            />
          </div>

          <Form<DailyReviewFormValues>
            layout="vertical"
            requiredMark={false}
          >
            <Form.Item
              label="昨日回顾"
              required
              htmlFor="daily-review-summary"
            >
              <Input.TextArea
                id="daily-review-summary"
                value={values.summary}
                onChange={(event) => updateField('summary', event.target.value)}
                rows={5}
                placeholder="昨天完成了什么？哪里卡住了？"
                maxLength={800}
                showCount
              />
            </Form.Item>

            <Form.Item
              label="今日目标"
              required
              htmlFor="daily-review-goal-input"
              extra="点一下目标就能标记完成，完成后会显示删除线。"
            >
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  id="daily-review-goal-input"
                  value={goalDraft}
                  onChange={(event) => setGoalDraft(event.target.value)}
                  onPressEnter={addGoal}
                  placeholder="输入一条今日目标"
                  maxLength={120}
                />
                <Button
                  aria-label="添加目标"
                  icon={<PlusOutlined />}
                  htmlType="button"
                  onClick={addGoal}
                >
                  添加目标
                </Button>
              </Space.Compact>
              <Space direction="vertical" size={8} className="sb-goal-list">
                {values.goals.length === 0 ? (
                  <Text type="secondary">还没有目标，先写一条今天最想完成的事。</Text>
                ) : (
                  values.goals.map((goal) => (
                    <div key={goal.id} className="sb-goal-row">
                      <Checkbox
                        checked={goal.done}
                        onChange={() => toggleGoal(goal.id)}
                        style={{ minWidth: 0 }}
                      >
                        <span
                          className={`sb-goal-text ${goal.done ? 'is-done' : ''}`}
                        >
                          {goal.text}
                        </span>
                      </Checkbox>
                      {!goal.done && (
                        <Button
                          size="small"
                          type="link"
                          icon={<MessageOutlined />}
                          aria-label={`商量计划：${goal.text}`}
                          onClick={() => openGoalPlanChat(goal)}
                          style={{ paddingInline: 4 }}
                        >
                          商量计划
                        </Button>
                      )}
                    </div>
                  ))
                )}
              </Space>
            </Form.Item>

            <Form.Item
              label="需要提醒我的地方"
              htmlFor="daily-review-support"
              extra="可选。比如容易拖延、容易忘记开始。"
            >
              <Input.TextArea
                id="daily-review-support"
                value={values.support}
                onChange={(event) => updateField('support', event.target.value)}
                rows={3}
                placeholder="希望被怎么提醒？"
                maxLength={400}
                showCount
              />
            </Form.Item>

            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button
                type="primary"
                icon={<CheckCircleOutlined />}
                aria-label="保存回顾"
                htmlType="button"
                loading={saving}
                onClick={handleSave}
              >
                保存回顾
              </Button>
            </div>
          </Form>
        </Card>

        <Card
          variant="borderless"
          className="sb-daily-review-card"
          styles={{ body: { padding: 0 } }}
        >
          <div className="sb-review-history-head">
            <HistoryOutlined style={{ color: 'var(--sb-color-primary)' }} />
            <Text strong>最近回顾</Text>
          </div>

          {historyLoading ? (
            <div style={{ padding: 36, textAlign: 'center' }}>
              <Spin />
            </div>
          ) : reviewHistory.length === 0 ? (
            <Empty description="还没有写过每日回顾" style={{ padding: '20px 0 36px' }} />
          ) : (
            <List
              className="sb-review-history-list"
              dataSource={reviewHistory}
              renderItem={(note) => (
                <List.Item
                  style={{ cursor: 'pointer', padding: '14px 24px' }}
                  onClick={() => navigate(`/notes/${note.id}`)}
                >
                  <List.Item.Meta
                    title={
                      <Space size={8} wrap>
                        <Text strong className="sb-review-history-title">{note.title}</Text>
                        {note.status === 'confirmed' ? (
                          <Tag className="sb-status-chip sb-status-chip--confirmed">已确认</Tag>
                        ) : (
                          <Tag className="sb-status-chip sb-status-chip--draft">草稿</Tag>
                        )}
                      </Space>
                    }
                    description={
                      <Space direction="vertical" size={4} style={{ width: '100%' }}>
                        <Text className="sb-review-history-preview">{getPreview(note.content) || '暂无内容'}</Text>
                        <Text className="sb-review-history-time">
                          {note.updated_at}
                        </Text>
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          )}
        </Card>
      </Space>
    </div>
  );
}
