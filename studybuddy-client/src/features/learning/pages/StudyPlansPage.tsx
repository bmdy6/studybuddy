import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { App, Button, Card, Empty, Progress, Select, Space, Tag, Typography } from 'antd';
import { PageSpinner } from '../../../shared/components/PageSpinner';
import {
  AlertOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  EyeOutlined,
  MessageOutlined,
  ReloadOutlined,
  ScheduleOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { p2Api } from '@/features/p2/api';
import { CompletionEvidenceModal } from '@/features/p2/components/CompletionEvidenceModal';
import { ROLES } from '@/shared/constants';
import StudentPageShell from '@/shared/components/StudentPageShell';
import { getActiveStudentId, useAuthStore } from '@/features/auth/store';
import type { StudyPlan, StudyPlanItem } from '@/types';

const { Text, Title, Paragraph } = Typography;

const PLAN_STATUS_META: Record<string, { color: string; label: string }> = {
  active: { color: 'processing', label: '进行中' },
  completed: { color: 'green', label: '已完成' },
  archived: { color: 'default', label: '已归档' },
};

const ITEM_STATUS_META: Record<string, { color: string; label: string }> = {
  todo: { color: 'default', label: '待做' },
  done: { color: 'green', label: '完成' },
  skipped: { color: 'gold', label: '跳过' },
};

const formatDate = (value: string | null) => value || '未定日期';

function getCompletion(plan: StudyPlan) {
  const total = plan.items.length;
  const done = plan.items.filter((item) => item.status === 'done').length;
  const closed = plan.items.filter((item) => item.status === 'done' || item.status === 'skipped').length;
  return {
    total,
    done,
    closed,
    percent: total ? Math.round((closed / total) * 100) : 0,
  };
}

function getTotalMinutes(plan: StudyPlan) {
  return plan.items.reduce((sum, item) => sum + item.minutes, 0);
}

function buildOverdueReviewPrompt(plan: StudyPlan) {
  const dateText = formatDate(plan.planned_date);
  const itemText = plan.items.map((item) => `- ${item.title}：${item.status}`).join('\n');
  return `帮我复盘这个逾期学习计划「${plan.title}」。计划日期：${dateText}，已经逾期 ${plan.overdue_days} 天。请先判断哪些任务没完成，再用温和的方式帮学生分析原因，并给出今天可以补救的 1-3 个小步骤。\n${itemText}`;
}

export default function StudyPlansPage() {
  const { message } = App.useApp();
  const messageRef = useRef(message);
  const navigate = useNavigate();
  const authState = useAuthStore();
  const { role, children, activeChildId, setActiveChild } = authState;
  const [plans, setPlans] = useState<StudyPlan[]>([]);
  const [statusFilter, setStatusFilter] = useState<'active' | 'completed' | 'all'>('active');
  const [loading, setLoading] = useState(false);
  const [updatingIds, setUpdatingIds] = useState<Set<number>>(new Set());
  // P0 门禁：待填证据的计划项（非 null 时显示证据弹窗）
  const [evidenceTarget, setEvidenceTarget] = useState<StudyPlanItem | null>(null);
  // P2 体验：提交失败重开时保留已输入证据
  const [evidenceDraft, setEvidenceDraft] = useState('');

  const studentId = getActiveStudentId(authState);
  const activeChild = children.find((child) => child.id === activeChildId);
  const studentName =
    role === ROLES.PARENT ? activeChild?.display_name ?? '当前学生' : authState.displayName ?? '我';

  useEffect(() => {
    messageRef.current = message;
  }, [message]);

  const loadPlans = useCallback(async () => {
    if (!studentId) return;
    setLoading(true);
    try {
      const data = await p2Api.listStudyPlans(studentId, statusFilter === 'all' ? '' : statusFilter);
      setPlans(data);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '加载学习计划失败';
      messageRef.current.error(msg);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, studentId]);

  useEffect(() => {
    void loadPlans();
  }, [loadPlans]);

  const summary = useMemo(() => {
    const itemCount = plans.reduce((sum, plan) => sum + plan.items.length, 0);
    const doneCount = plans.reduce(
      (sum, plan) => sum + plan.items.filter((item) => item.status === 'done').length,
      0,
    );
    const minutes = plans.reduce((sum, plan) => sum + getTotalMinutes(plan), 0);
    const overdueCount = plans.filter((plan) => plan.is_overdue).length;
    return { itemCount, doneCount, minutes, overdueCount };
  }, [plans]);

  const updateItemStatus = async (item: StudyPlanItem, status: 'done' | 'skipped') => {
    if (status === 'done') {
      // P0 门禁：完成必须带学生自报证据，先弹证据输入框
      setEvidenceTarget(item);
      return;
    }
    await doUpdateItemStatus(item, status);
  };

  const doUpdateItemStatus = async (item: StudyPlanItem, status: 'done' | 'skipped', evidence?: string) => {
    setUpdatingIds((ids) => new Set(ids).add(item.id));
    try {
      await p2Api.updateStudyPlanItem(item.id, status, evidence);
      await loadPlans();
      message.success(status === 'done' ? '任务已完成' : '已跳过任务');
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '更新任务状态失败';
      message.error(msg);
    } finally {
      setUpdatingIds((ids) => {
        const next = new Set(ids);
        next.delete(item.id);
        return next;
      });
    }
  };

  const handleEvidenceSubmit = async (evidence: string) => {
    if (!evidenceTarget) return;
    const item = { ...evidenceTarget };
    setEvidenceTarget(null);
    try {
      await doUpdateItemStatus(item, 'done', evidence);
    } catch {
      // P2 体验：失败时重新打开弹窗并保留已输入的证据
      setEvidenceTarget(item);
      setEvidenceDraft(evidence);
    }
  };

  const openItemReview = (item: StudyPlanItem) => {
    navigate(`/chat?continue_task_item=${item.id}`);
  };

  const openOverdueReview = (plan: StudyPlan) => {
    // P2 修复：逾期计划「继续」应激活 task session（continue_task_item），
    // 顶部 dock 才能显示任务标题 + 完成学习；旧逻辑用 prompt 预填主会话不激活 task session → dock 空态。
    const firstTodo = [...(plan.items || [])]
      .filter((item) => item.status === 'todo')
      .sort((a, b) => a.sort_order - b.sort_order)[0];
    if (firstTodo) {
      navigate(`/chat?continue_task_item=${firstTodo.id}`);
      return;
    }
    const params = new URLSearchParams({
      student_id: String(plan.student_id),
      prompt: buildOverdueReviewPrompt(plan),
    });
    navigate(`/chat?${params.toString()}`);
  };

  if (!studentId) {
    return (
      <div className="sb-student-shell" style={{ maxWidth: 1000 }}>
        <Empty description="还没有可查看的学生">
          <Button type="primary" icon={<MessageOutlined />} onClick={() => navigate('/chat')}>
            去对话页创建计划
          </Button>
        </Empty>
      </div>
    );
  }

  return (
    <StudentPageShell
      title="学习计划"
      subtitle="把对话里制定的计划变成可完成、可跳过、可复盘的小任务。"
      icon={<ScheduleOutlined />}
      actions={
        <>
          <Button icon={<MessageOutlined />} onClick={() => navigate('/chat')}>
            去对话页
          </Button>
          <Button icon={<ReloadOutlined />} onClick={loadPlans} loading={loading}>
            刷新
          </Button>
        </>
      }
      metrics={[
        { label: '任务完成', value: `${summary.doneCount}/${summary.itemCount}` },
        { label: '预计用时', value: `${summary.minutes} 分钟` },
        {
          label: '需要复盘',
          value: `${summary.overdueCount} 个逾期`,
          tone: summary.overdueCount ? 'warning' : 'success',
        },
      ]}
      maxWidth={1080}
    >
      <Card style={{ borderRadius: 12, marginBottom: 16 }}>
        <div className="sb-visual-filter-row">
          <Space direction="vertical" size={2} className="sb-visual-field">
            <Text type="secondary" style={{ fontSize: 12 }}>
              当前学生
            </Text>
            {role === ROLES.PARENT && children.length > 1 ? (
              <Select
                value={activeChildId ?? undefined}
                onChange={setActiveChild}
                options={children.map((child) => ({ value: child.id, label: child.display_name }))}
              />
            ) : (
              <Title level={4} style={{ margin: 0 }}>
                {studentName}
              </Title>
            )}
          </Space>
          <Space direction="vertical" size={2} className="sb-visual-field">
            <Text type="secondary" style={{ fontSize: 12 }}>
              查看范围
            </Text>
            <Select
              style={{ width: 160 }}
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: 'active', label: '进行中' },
                { value: 'completed', label: '已完成' },
                { value: 'all', label: '全部计划' },
              ]}
            />
          </Space>
        </div>
      </Card>

      {loading ? (
        <PageSpinner />
      ) : plans.length === 0 ? (
        <Card style={{ borderRadius: 12 }}>
          <Empty
            image={<ScheduleOutlined style={{ fontSize: 48, color: 'var(--sb-color-attr-neutral)' }} />}
            description="还没有学习计划"
            style={{ padding: '44px 0' }}
          >
            <Button
              type="primary"
              icon={<MessageOutlined />}
              onClick={() => navigate('/chat?prompt=' + encodeURIComponent('帮我制定今天的学习计划'))}
            >
              让助手制定今天的计划
            </Button>
          </Empty>
        </Card>
      ) : (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {plans.map((plan) => {
            const completion = getCompletion(plan);
            const planMeta = PLAN_STATUS_META[plan.status] ?? { color: 'default', label: plan.status };
            return (
              <Card key={plan.id} style={{ borderRadius: 12 }}>
                <div className="sb-plan-card-head">
                  <Space direction="vertical" size={4}>
                    <Space size={8} wrap align="center">
                      <Title level={4} className="sb-plan-card-title">
                        {plan.title}
                      </Title>
                      <Tag color={planMeta.color}>{planMeta.label}</Tag>
                    </Space>
                    <div className="sb-plan-tags">
                      <Tag icon={<ClockCircleOutlined />}>{formatDate(plan.planned_date)}</Tag>
                      {plan.is_overdue && (
                        <Tag color="orange" icon={<AlertOutlined />}>
                          逾期 {plan.overdue_days} 天
                        </Tag>
                      )}
                      <Tag>{getTotalMinutes(plan)} 分钟</Tag>
                      {plan.focus && <Tag color="blue">{plan.focus}</Tag>}
                    </div>
                  </Space>
                  <div className="sb-plan-progress">
                    <Progress percent={completion.percent} size="small" />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      完成 {completion.done} 项，收尾 {completion.closed}/{completion.total} 项
                    </Text>
                    {plan.is_overdue && (
                      <Button
                        size="small"
                        icon={<MessageOutlined />}
                        style={{ marginTop: 8 }}
                        onClick={() => openOverdueReview(plan)}
                      >
                        复盘
                      </Button>
                    )}
                  </div>
                </div>

                <Space direction="vertical" size={10} style={{ width: '100%' }}>
                  {plan.items.map((item) => {
                    const itemMeta = ITEM_STATUS_META[item.status] ?? { color: 'default', label: item.status };
                    const isClosed = item.status === 'done' || item.status === 'skipped';
                    return (
                      <div
                        key={item.id}
                        className={`sb-plan-item${item.status === 'done' ? ' sb-plan-item--done' : ''}`}
                        onClick={item.status === 'done' ? () => openItemReview(item) : undefined}
                        role={item.status === 'done' ? 'button' : undefined}
                        tabIndex={item.status === 'done' ? 0 : undefined}
                        onKeyDown={
                          item.status === 'done'
                            ? (e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault();
                                  openItemReview(item);
                                }
                              }
                            : undefined
                        }
                      >
                        <Space direction="vertical" size={4} className="sb-plan-item-main">
                          <Space size={8} wrap align="center">
                            <Text
                              strong
                              className={`sb-plan-item-title${item.status === 'done' ? ' sb-plan-item-title--clickable' : ''}`}
                            >
                              {item.title}
                            </Text>
                            <Tag color={itemMeta.color}>{itemMeta.label}</Tag>
                            <Tag>{item.minutes} 分钟</Tag>
                          </Space>
                          {item.target && (
                            <Paragraph type="secondary" style={{ margin: 0 }}>
                              {item.target}
                            </Paragraph>
                          )}
                          {item.related_tags.length > 0 && (
                            <Space size={4} wrap>
                              {item.related_tags.map((tag) => (
                                <Tag key={tag}>{tag}</Tag>
                              ))}
                            </Space>
                          )}
                        </Space>
                        <Space size={6} wrap className="sb-plan-item-actions" onClick={(e) => e.stopPropagation()}>
                          {item.status === 'done' ? (
                            <Button
                              size="small"
                              icon={<EyeOutlined />}
                              onClick={() => openItemReview(item)}
                            >
                              查看
                            </Button>
                          ) : (
                            <Button
                              size="small"
                              icon={<CheckCircleOutlined />}
                              loading={updatingIds.has(item.id)}
                              onClick={() => updateItemStatus(item, 'done')}
                            >
                              完成
                            </Button>
                          )}
                          <Button
                            size="small"
                            icon={<StopOutlined />}
                            disabled={isClosed}
                            loading={updatingIds.has(item.id)}
                            onClick={() => updateItemStatus(item, 'skipped')}
                          >
                            跳过
                          </Button>
                        </Space>
                      </div>
                    );
                  })}
                </Space>
              </Card>
            );
          })}
        </Space>
      )}
      <CompletionEvidenceModal
        open={evidenceTarget !== null}
        itemTitle={evidenceTarget?.title ?? ''}
        submitting={updatingIds.has(evidenceTarget?.id ?? -1)}
        initialValue={evidenceDraft}
        onCancel={() => {
          setEvidenceTarget(null);
          setEvidenceDraft('');
        }}
        onSubmit={handleEvidenceSubmit}
      />
    </StudentPageShell>
  );
}
