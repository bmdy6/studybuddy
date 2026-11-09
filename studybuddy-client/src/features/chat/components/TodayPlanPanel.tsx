import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  Alert,
  Button,
  Drawer,
  Grid,
  Popconfirm,
  Skeleton,
  Tooltip,
  Typography,
} from 'antd';
import {
  ArrowLeftOutlined,
  CheckOutlined,
  CloseOutlined,
  FileTextOutlined,
  PlusOutlined,
  ReloadOutlined,
  RightOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons';

import { p2Api } from '@/features/p2/api';
import { CompletionEvidenceModal } from '@/features/p2/components/CompletionEvidenceModal';
import { withRetry } from '@/shared/utils/retry';
import { dailyRecordsApi } from '@/features/growth/dailyRecords';
import type {
  DailyLearningRecord,
  StudyPlan,
  StudyPlanItem,
} from '@/types';
import ManualStudyPlanDrawer from './ManualStudyPlanDrawer';
import { useChatStore } from '@/features/chat/store';

const { Text } = Typography;

/** 认证时序重试上限（注册/账号切换后首次请求可能 401/403） */
const AUTH_RETRY_MAX = 2;
/** 认证重试退避基准毫秒，按次数递增（400ms -> 800ms） */
const AUTH_RETRY_DELAY_MS = 400;
/** 兜底重试上限：瞬时错误（500/网络/超时/401认证重试后仍失败）延迟重试恢复，不卡 error */
const ERROR_RETRY_MAX = 2;
/** 兜底重试退避基准毫秒（2s -> 4s），比认证重试拉长，覆盖瞬时网络/后端恢复 */
const ERROR_RETRY_DELAY_MS = 2000;
const ERROR_RECOVER_MAX = 2;
const ERROR_RECOVER_DELAY_MS = 5000;

const SELECTED_ITEM_STORAGE_PREFIX = 'sb-selected-item-';

export interface TodayLearningTask {
  planId: number;
  planTitle: string;
  item: StudyPlanItem;
}

interface TodayPlanPanelProps {
  studentId: number;
  mode: 'today' | 'learning';
  learningPrompt: string;
  onStartLearning: (task: TodayLearningTask, prompt: string) => void;
  onReturnToday: () => void;
  onTaskCompleted: () => void;
  onContinueConversation?: (prompt?: string) => void;
  onAskAiToPlan?: () => void;
  conversationActions?: ReactNode;
  /** 紧凑单行模式：用于 PC 桌面全局 Header 内的今日任务条（不占聊天区顶部整条） */
  compact?: boolean;
}

function todayValue() {
  const value = new Date();
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(
    value.getDate(),
  ).padStart(2, '0')}`;
}

/** 从 localStorage 按 studentId 恢复上次手动选中的任务（刷新后恢复当前任务）。 */
function readSelectedItemId(studentId: number): number | null {
  try {
    const raw = localStorage.getItem(`${SELECTED_ITEM_STORAGE_PREFIX}${studentId}`);
    const parsed = raw ? Number(raw) : null;
    return Number.isFinite(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** 持久化选中的任务 id（按 studentId 隔离，避免串账号）；null 时清理残留。 */
function writeSelectedItemId(studentId: number, itemId: number | null) {
  try {
    if (itemId !== null) {
      localStorage.setItem(`${SELECTED_ITEM_STORAGE_PREFIX}${studentId}`, String(itemId));
    } else {
      localStorage.removeItem(`${SELECTED_ITEM_STORAGE_PREFIX}${studentId}`);
    }
  } catch {
    /* localStorage 不可用时忽略 */
  }
}

function itemStatusLabel(item: StudyPlanItem, currentItemId: number | null) {
  if (item.status === 'done') return '已完成';
  if (item.status === 'skipped') return '已跳过';
  return item.id === currentItemId ? '当前' : '待开始';
}

export default function TodayPlanPanel({
  studentId,
  mode,
  learningPrompt,
  onStartLearning,
  onReturnToday,
  onTaskCompleted,
  onContinueConversation,
  onAskAiToPlan,
  conversationActions,
  compact = false,
}: TodayPlanPanelProps) {
  const [plans, setPlans] = useState<StudyPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);
  // P0 门禁：待填证据的计划项（非 null 时显示证据弹窗）
  const [evidenceTarget, setEvidenceTarget] = useState<StudyPlanItem | null>(null);
  // P2 体验：提交失败重开时保留已输入证据
  const [evidenceDraft, setEvidenceDraft] = useState('');
  const [removingItemId, setRemovingItemId] = useState<number | null>(null);
  const [selectedItemId, setSelectedItemId] = useState<number | null>(() =>
    readSelectedItemId(studentId),
  );
  const [taskDrawerOpen, setTaskDrawerOpen] = useState(false);
  const [manualDrawerOpen, setManualDrawerOpen] = useState(false);
  const [dailyRecord, setDailyRecord] = useState<DailyLearningRecord | null>(null);
  const [dailyRecordLoading, setDailyRecordLoading] = useState(true);
  const [dailyRecordMissing, setDailyRecordMissing] = useState(false);
  const [dailyRecordError, setDailyRecordError] = useState(false);
  const [summaryDrawerOpen, setSummaryDrawerOpen] = useState(false);
  const screens = Grid.useBreakpoint();
  const mobile = !screens.md;
  // 认证时序重试：注册/账号切换后首次请求可能 401/403（token/studentId 未稳定），
  // withRetry 只重试瞬时网络/5xx，不重试 4xx。这里对 401/403 做有限延迟重试，
  // 期间保持 loading 不闪现 error；404 视为空数据走空态。
  const authRetryRef = useRef(0);
  const authRetryTimerRef = useRef<number | null>(null);
  const errorRetryRef = useRef(0);
  const errorRetryTimerRef = useRef<number | null>(null);
  const errorRecoverRef = useRef(0);
  const errorRecoverTimerRef = useRef<number | null>(null);

  const loadPlans = useCallback(
    async (showLoading = true) => {
      if (!studentId) {
        setLoading(false);
        return;
      }
      if (showLoading) {
        setLoading(true);
        setError(false);
      }
      let willRetry = false;
      try {
        setPlans(await withRetry(() => p2Api.listStudyPlans(studentId, '')));
        authRetryRef.current = 0;
        errorRetryRef.current = 0;
        errorRecoverRef.current = 0;
      } catch (requestError) {
        const status = (requestError as { response?: { status?: number } })?.response?.status;
        if (status === 404) {
          // 404 视为空数据（正常空列表应是 200 []，此处防御 404）
          setPlans([]);
          authRetryRef.current = 0;
          errorRetryRef.current = 0;
        } else if (
          (status === 401 || status === 403) &&
          authRetryRef.current < AUTH_RETRY_MAX
        ) {
          // 认证未就绪，延迟重试，保持 loading 不闪 error
          authRetryRef.current += 1;
          willRetry = true;
          authRetryTimerRef.current = window.setTimeout(() => {
            authRetryTimerRef.current = null;
            void loadPlans(false);
          }, AUTH_RETRY_DELAY_MS * authRetryRef.current);
        } else if (errorRetryRef.current < ERROR_RETRY_MAX) {
          // 兜底自动重试：瞬时错误（500/网络/超时/401认证重试后仍失败）延迟重试恢复，不卡 error
          errorRetryRef.current += 1;
          willRetry = true;
          errorRetryTimerRef.current = window.setTimeout(() => {
            errorRetryTimerRef.current = null;
            void loadPlans(false);
          }, ERROR_RETRY_DELAY_MS * errorRetryRef.current);
        } else if (errorRecoverRef.current < ERROR_RECOVER_MAX) {
          // error 后延迟自动恢复（首屏瞬时错误不卡死，最多 N 次，仍失败保持 error 可手动）
          errorRecoverRef.current += 1;
          setError(true);
          errorRecoverTimerRef.current = window.setTimeout(() => {
            errorRecoverTimerRef.current = null;
            void loadPlans(false);
          }, ERROR_RECOVER_DELAY_MS);
        } else {
          setError(true);
          authRetryRef.current = 0;
          errorRetryRef.current = 0;
          errorRecoverRef.current = 0;
        }
      } finally {
        if (!willRetry) setLoading(false);
      }
    },
    [studentId],
  );

  useEffect(() => {
    // studentId 变化（含首次挂载）时重置重试计数并加载；清理未完成的延迟重试避免串账号
    authRetryRef.current = 0;
    errorRetryRef.current = 0;
    if (authRetryTimerRef.current !== null) {
      window.clearTimeout(authRetryTimerRef.current);
      authRetryTimerRef.current = null;
    }
    if (errorRetryTimerRef.current !== null) {
      window.clearTimeout(errorRetryTimerRef.current);
      errorRetryTimerRef.current = null;
    }
    if (errorRecoverTimerRef.current !== null) {
      window.clearTimeout(errorRecoverTimerRef.current);
      errorRecoverTimerRef.current = null;
    }
    void loadPlans();
    return () => {
      if (authRetryTimerRef.current !== null) {
        window.clearTimeout(authRetryTimerRef.current);
        authRetryTimerRef.current = null;
      }
      if (errorRetryTimerRef.current !== null) {
        window.clearTimeout(errorRetryTimerRef.current);
        errorRetryTimerRef.current = null;
      }
      if (errorRecoverTimerRef.current !== null) {
        window.clearTimeout(errorRecoverTimerRef.current);
        errorRecoverTimerRef.current = null;
      }
    };
  }, [loadPlans]);

  // AI 经对话新建学习计划后，chat store 的 planVersion 自增 -> 刷新本面板计划列表。
  // 手动抽屉已在 onCreated 里刷新，这里只补 AI 路径；跳过首次挂载避免与上面的 effect 重复加载。
  const planVersion = useChatStore((state) => state.planVersion);
  // task session 激活时的任务 id（学习页入口不设 selectedItemId，用它兜底显示逾期任务）
  const activeTaskItemId = useChatStore((state) => state.activeTaskItemId);
  const lastSeenPlanVersion = useRef(planVersion);
  useEffect(() => {
    if (lastSeenPlanVersion.current !== planVersion) {
      lastSeenPlanVersion.current = planVersion;
      void loadPlans(false);
    }
  }, [planVersion, loadPlans]);

  // selectedItemId 持久化：刷新后恢复手动选中的任务，按 studentId 隔离避免串账号
  useEffect(() => {
    writeSelectedItemId(studentId, selectedItemId);
  }, [selectedItemId, studentId]);

  // studentId 变化（切账号）时从 localStorage 恢复该账号上次选中的任务
  useEffect(() => {
    setSelectedItemId(readSelectedItemId(studentId));
  }, [studentId]);

  const loadDailyRecord = useCallback(async () => {
    setDailyRecordLoading(true);
    setDailyRecordMissing(false);
    setDailyRecordError(false);
    try {
      setDailyRecord(await dailyRecordsApi.refresh(studentId));
    } catch (requestError) {
      const status = (requestError as { response?: { status?: number } }).response?.status;
      setDailyRecord(null);
      setDailyRecordMissing(status === 404);
      setDailyRecordError(status !== 404);
    } finally {
      setDailyRecordLoading(false);
    }
  }, [studentId]);

  useEffect(() => {
    void loadDailyRecord();
  }, [loadDailyRecord]);

  const today = todayValue();
  const dueActivePlans = useMemo(
    () =>
      plans.filter(
        (plan) =>
          plan.status === 'active' &&
          plan.planned_date &&
          plan.planned_date === today &&
          plan.items.some((item) => item.status === 'todo'),
      ),
    [plans, today],
  );
  const completedTodayPlans = useMemo(
    () => plans.filter((plan) => plan.status === 'completed' && plan.planned_date === today),
    [plans, today],
  );
  const queuePlans = useMemo(
    () => [...dueActivePlans, ...completedTodayPlans],
    [completedTodayPlans, dueActivePlans],
  );
  const queueItems = useMemo(
    () =>
      queuePlans.flatMap((plan) =>
        [...plan.items]
          .sort((left, right) => left.sort_order - right.sort_order)
          .map((item) => ({ plan, item })),
      ),
    [queuePlans],
  );
  const availableItems = useMemo(
    () =>
      dueActivePlans.flatMap((plan) =>
        [...plan.items]
          .filter((item) => item.status === 'todo')
          .sort((left, right) => left.sort_order - right.sort_order)
          .map((item) => ({ plan, item })),
      ),
    [dueActivePlans],
  );
  // task session 激活时 selectedItemId 可能指向逾期计划的 todo 任务（跨天继续昨天计划）。
  // dueActivePlans 只收今天的计划，逾期计划不在 availableItems，会导致 currentItem 为 null 走空态。
  // 这里把所有 active 计划（含逾期）的 todo 任务纳入查找，保证 task session 顶部显示当前任务。
  const allActiveTodoItems = useMemo(
    () =>
      plans
        .filter((plan) => plan.status === 'active')
        .flatMap((plan) =>
          [...plan.items]
            .filter((item) => item.status === 'todo')
            .sort((left, right) => left.sort_order - right.sort_order)
            .map((item) => ({ plan, item })),
        ),
    [plans],
  );
  const currentQueueItem =
    availableItems.find(({ item }) => item.id === selectedItemId) ??
    allActiveTodoItems.find(({ item }) => item.id === selectedItemId) ??
    allActiveTodoItems.find(({ item }) => item.id === activeTaskItemId) ??
    availableItems[0] ??
    null;
  const currentPlan = currentQueueItem?.plan ?? null;
  const currentItem = currentQueueItem?.item ?? null;
  // 当前任务是否属于今日队列；逾期计划的任务不算今日队列，顶部进度不显示 0/0。
  const isCurrentItemToday = currentItem
    ? availableItems.some(({ item }) => item.id === currentItem.id)
    : true;
  const currentLearningPrompt =
    selectedItemId === null || selectedItemId === availableItems[0]?.item.id ? learningPrompt : '';
  const processedCount = queueItems.filter(
    ({ item }) => item.status === 'done' || item.status === 'skipped',
  ).length;
  const completedToday = !currentItem && completedTodayPlans.length > 0;
  const remainingCount = queueItems.filter(({ item }) => item.status === 'todo').length;

  const deterministicSummary = (record: DailyLearningRecord) => {
    const titles = record.facts_snapshot.evidence
      .map((item) => item.title?.trim())
      .filter((title): title is string => Boolean(title));
    if (titles.length === 0) return '今天暂时没有新的学习记录';
    const uniqueTitles = [...new Set(titles)].slice(0, 3);
    const parts = [`今天记录了${uniqueTitles.join('、')}`];
    if (record.facts_snapshot.self_reported_duration_minutes > 0) {
      parts.push(`自报学习 ${record.facts_snapshot.self_reported_duration_minutes} 分钟`);
    }
    if (record.facts_snapshot.pending_tasks.length > 0) {
      parts.push(`还有 ${record.facts_snapshot.pending_tasks.length} 项任务待完成`);
    }
    return `${parts.join('，')}。`;
  };

  const dailyRecap = (
    <section className="sb-daily-recap" aria-label="今日学习摘要">
      <div className="sb-daily-recap-heading">
        <div>
          <Text strong>{completedToday ? '今天的学习摘要' : processedCount > 0 ? '今天到目前为止' : '今日学习摘要'}</Text>
          {remainingCount > 0 && <Text type="secondary">还剩 {remainingCount} 项任务</Text>}
        </div>
        {onContinueConversation && (
          <Button
            type="text"
            className="sb-daily-recap-continue"
            onClick={() => onContinueConversation('我想继续聊聊今天的学习记录。')}
          >
            继续聊聊
          </Button>
        )}
      </div>
      {dailyRecordLoading ? (
        <div className="sb-daily-recap-skeleton" aria-label="今日学习摘要加载中">
          <Skeleton active paragraph={{ rows: 2 }} title={false} />
        </div>
      ) : dailyRecordMissing ? (
        <Text type="secondary">今天暂时没有新的学习记录</Text>
      ) : dailyRecordError ? (
        <Text type="secondary">今日摘要暂时不可用，任务进度仍以 Today 为准。</Text>
      ) : dailyRecord?.generation_status === 'pending' || dailyRecord?.generation_status === 'generating' ? (
        <div className="sb-daily-recap-skeleton" aria-label="今日学习摘要加载中">
          <Skeleton active paragraph={{ rows: 2 }} title={false} />
        </div>
      ) : dailyRecord?.generation_status === 'failed' ? (
        <Text className="sb-daily-recap-summary">{dailyRecord ? deterministicSummary(dailyRecord) : '今天暂时没有新的学习记录'}</Text>
      ) : (
        <Text className="sb-daily-recap-summary">
          {dailyRecord?.summary_text?.trim() || (dailyRecord ? deterministicSummary(dailyRecord) : '今天暂时没有新的学习记录')}
        </Text>
      )}
    </section>
  );

  const openManualPlan = () => {
    setTaskDrawerOpen(false);
    setManualDrawerOpen(true);
  };

  const completeCurrentItem = async () => {
    if (!currentItem) return;
    // P0 门禁：完成学习必须带学生自报证据（复述/回答），无证据不请求 PATCH
    setEvidenceTarget(currentItem);
  };

  const handleEvidenceSubmit = async (evidence: string) => {
    if (!evidenceTarget) return;
    const item = evidenceTarget;
    const targetId = item.id;
    setEvidenceTarget(null);
    setUpdating(true);
    setActionError(null);
    try {
      await p2Api.updateStudyPlanItem(targetId, 'done', evidence);
      await loadPlans(false);
      void loadDailyRecord();
      setSelectedItemId(null);
      onTaskCompleted();
    } catch {
      setActionError('更新任务失败，请再试一次');
      // P2 体验：失败时重新打开弹窗并保留已输入的证据，避免学生重打
      setEvidenceTarget({ ...item });
      setEvidenceDraft(evidence);
    } finally {
      setUpdating(false);
    }
  };

  const archiveCurrentPlan = async () => {
    if (!currentPlan) return;
    setActionError(null);
    try {
      await p2Api.archiveStudyPlan(currentPlan.id);
      await loadPlans(false);
      setSelectedItemId(null);
      setTaskDrawerOpen(false);
    } catch {
      setActionError('删除计划失败，请再试一次');
    }
  };

  const removeTask = async (item: StudyPlanItem) => {
    setRemovingItemId(item.id);
    setActionError(null);
    try {
      await p2Api.updateStudyPlanItem(item.id, 'skipped');
      await loadPlans(false);
      if (selectedItemId === item.id) setSelectedItemId(null);
    } catch {
      setActionError('移出任务失败，请再试一次');
    } finally {
      setRemovingItemId(null);
    }
  };

  const selectTask = (itemId: number) => {
    const target = availableItems.find(({ item }) => item.id === itemId);
    if (!target) return;
    setSelectedItemId(itemId);
    setTaskDrawerOpen(false);
    // 手动选择任务 -> 进对应 task session（后端建/恢复），保证顶部、任务列表、AI 对话一致
    onStartLearning(
      { planId: target.plan.id, planTitle: target.plan.title, item: target.item },
      '',
    );
  };

  const renderTaskQueue = () => (
    <div className="sb-learning-task-list">
      {queueItems.map(({ plan, item }) => {
        const status = itemStatusLabel(item, currentItem?.id ?? null);
        const selectable = item.status === 'todo';
        return (
          <div
            className={`sb-learning-task-row${item.id === currentItem?.id ? ' is-current' : ''}${
              item.status === 'done' || item.status === 'skipped' ? ' is-closed' : ''
            }`}
            key={`${plan.id}-${item.id}`}
          >
            <button
              type="button"
              className="sb-learning-task-main"
              disabled={!selectable}
              aria-label={selectable ? `切换到任务 ${item.title}` : undefined}
              onClick={selectable ? () => selectTask(item.id) : undefined}
            >
              <span className="sb-learning-task-state" aria-hidden="true">
                {item.status === 'done' ? <CheckOutlined /> : item.id === currentItem?.id ? <RightOutlined /> : '○'}
              </span>
              <div className="sb-learning-task-copy">
                <Text strong>{item.title}</Text>
                <Text type="secondary">
                  {plan.title} · {item.minutes} 分钟
                </Text>
              </div>
              <Text className="sb-learning-task-status">{status}</Text>
            </button>
            {item.status === 'todo' && (
              <Popconfirm
                title="移出这个任务？"
                description="移出后不再计入今天，历史记录仍会保留。"
                okText="确认移出"
                cancelText="取消"
                okButtonProps={{ danger: true }}
                onConfirm={() => removeTask(item)}
              >
                <Button
                  type="text"
                  shape="circle"
                  className="sb-learning-task-remove"
                  icon={<CloseOutlined />}
                  loading={removingItemId === item.id}
                  aria-label={`移出今天 ${item.title}`}
                />
              </Popconfirm>
            )}
          </div>
        );
      })}
    </div>
  );

  if (loading) {
    return (
      <section className="sb-learning-dock sb-learning-dock--loading" aria-label="今日学习任务">
        <Skeleton active paragraph={{ rows: 2 }} title={{ width: 180 }} />
      </section>
    );
  }

  if (error) {
    return (
      <section className="sb-learning-dock sb-learning-dock--error" aria-label="今日学习任务">
        <Alert
          type="info"
          showIcon
          message="暂时没拿到今日计划"
          action={
            <Button type="text" icon={<ReloadOutlined />} onClick={() => void loadPlans()}>
              重新加载
            </Button>
          }
        />
      </section>
    );
  }

  const sharedDrawers = (
    <>
      <Drawer
        key={mobile ? 'bottom' : 'right'}
        open={taskDrawerOpen}
        placement={mobile ? 'bottom' : 'right'}
        width={mobile ? undefined : 360}
        height={mobile ? 'min(68dvh, 560px)' : undefined}
        title={
          <div className="sb-learning-task-drawer-title">
            <div>
              <span>今天计划</span>
              <Text type="secondary">
                已完成 {processedCount} / {queueItems.length} 项
              </Text>
            </div>
            <div style={{ display: 'flex', gap: 4 }}>
              {currentPlan && (
                <Popconfirm
                  title="删除这个计划？"
                  description="删除后不会出现在今天，历史记录仍会保留。"
                  okText="确认删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  onConfirm={archiveCurrentPlan}
                >
                  <Tooltip title="删除当前计划">
                    <Button
                      type="text"
                      shape="circle"
                      icon={<CloseOutlined />}
                      aria-label={`删除计划 ${currentPlan.title}`}
                    />
                  </Tooltip>
                </Popconfirm>
              )}
              <Tooltip title="添加计划">
                <Button
                  type="text"
                  shape="circle"
                  icon={<PlusOutlined />}
                  aria-label="添加计划"
                  onClick={openManualPlan}
                />
              </Tooltip>
            </div>
          </div>
        }
        rootClassName="sb-learning-task-drawer"
        onClose={() => setTaskDrawerOpen(false)}
        footer={conversationActions ? <div className="sb-learning-conversation-actions">{conversationActions}</div> : undefined}
      >
        {renderTaskQueue()}
      </Drawer>
      <ManualStudyPlanDrawer
        open={manualDrawerOpen}
        studentId={studentId}
        onClose={() => setManualDrawerOpen(false)}
        onCreated={() => {
          setManualDrawerOpen(false);
          void loadPlans(false);
        }}
      />
      <Drawer
        key={mobile ? 'bottom' : 'right'}
        open={summaryDrawerOpen}
        placement={mobile ? 'bottom' : 'right'}
        width={mobile ? undefined : 420}
        height={mobile ? 'min(60dvh, 480px)' : undefined}
        title="今日学习总结"
        rootClassName="sb-daily-summary-drawer"
        onClose={() => setSummaryDrawerOpen(false)}
      >
        {dailyRecap}
      </Drawer>
    </>
  );

  // PC 桌面全局 Header 内的紧凑单行今日任务条：空态/有任务/学习中/已完成 都在一行内表达。
  // 复用全部抽屉与门禁（任务列表/总结/完成学习证据弹窗），仅渲染形态不同。
  if (compact) {
    const noPlan = !currentPlan || !currentItem;
    const currentTask: TodayLearningTask | null = noPlan
      ? null
      : { planId: currentPlan.id, planTitle: currentPlan.title, item: currentItem! };
    const taskLabel = noPlan
      ? '今天还没计划'
      : completedToday
        ? '今天的任务做完了'
        : mode === 'learning'
          ? `${processedCount} / ${queueItems.length} 进行中`
          : `今日 ${processedCount + 1} / ${queueItems.length}`;
    const taskSub = noPlan
      ? '让 AI 帮你安排'
      : completedToday
        ? `完成 ${processedCount} / ${queueItems.length} 项`
        : currentPlan && currentItem
          ? `${currentPlan.title} · ${currentItem.minutes} 分钟`
          : '';
    return (
      <>
        <section
          className="sb-learning-dock sb-learning-dock--today sb-learning-dock--compact"
          aria-label="今日学习任务"
        >
          <div className="sb-learning-dock-current">
            <div>
              <Text strong className="sb-learning-dock-current-title">
                {taskLabel}
              </Text>
              <Text type="secondary" className="sb-learning-dock-current-meta">
                {taskSub}
              </Text>
            </div>
          </div>
          <div className="sb-learning-dock-actions">
            {mode === 'learning' && (
              <Tooltip title="返回今天">
                <Button
                  type="text"
                  shape="circle"
                  className="sb-learning-dock-back"
                  icon={<ArrowLeftOutlined />}
                  aria-label="返回今天"
                  onClick={onReturnToday}
                />
              </Tooltip>
            )}
            <Tooltip title="任务列表">
              <Button
                type="default"
                shape="circle"
                icon={<UnorderedListOutlined />}
                aria-label="任务列表"
                onClick={() => setTaskDrawerOpen(true)}
              />
            </Tooltip>
            {noPlan || completedToday ? (
              <Button type="primary" size="small" onClick={() => onAskAiToPlan?.()}>
                {completedToday ? '再排一份计划' : '让 AI 帮我定'}
              </Button>
            ) : mode === 'learning' ? (
              <Button type="primary" size="small" loading={updating} onClick={() => void completeCurrentItem()}>
                完成本任务
              </Button>
            ) : (
              <Button
                type="primary"
                size="small"
                onClick={() => {
                  if (currentTask) onStartLearning(currentTask, currentLearningPrompt);
                }}
              >
                继续
              </Button>
            )}
          </div>
        </section>
        {sharedDrawers}
      </>
    );
  }

  if (completedToday) {
    return (
      <>
        <section className="sb-learning-dock sb-learning-dock--today sb-learning-dock--complete" aria-label="今日学习任务">
          <div className="sb-learning-dock-current">
            <span className="sb-task-dock-progress">
              {processedCount}/{queueItems.length}
            </span>
            <div>
              <Text strong className="sb-learning-dock-current-title">
                今天的任务做完了
              </Text>
              <Text type="secondary" className="sb-learning-dock-current-meta">
                完成 {processedCount} / {queueItems.length} 项
              </Text>
            </div>
          </div>
          <div className="sb-learning-dock-actions">
            <Tooltip title="任务列表">
              <Button
                type="default"
                shape="circle"
                icon={<UnorderedListOutlined />}
                aria-label="任务列表"
                onClick={() => setTaskDrawerOpen(true)}
              />
            </Tooltip>
            <Button
              type="default"
              icon={<FileTextOutlined />}
              aria-label="今日学习总结"
              onClick={() => setSummaryDrawerOpen(true)}
            >
              <span className="sb-dock-summary-label">总结</span>
            </Button>
            {conversationActions}
            <Button type="primary" onClick={() => onAskAiToPlan?.()}>
              再排一份计划
            </Button>
          </div>
        </section>
        {sharedDrawers}
      </>
    );
  }

  if (!currentPlan || !currentItem) {
    return (
      <>
        <section className="sb-learning-dock sb-learning-dock--today sb-learning-dock--empty" aria-label="添加今天计划">
          <div className="sb-learning-dock-current">
            <div>
              <Text strong className="sb-learning-dock-current-title">
                今天还没有计划
              </Text>
              <Text type="secondary" className="sb-learning-dock-current-meta">
                让 AI 帮你安排，或点列表手动添加
              </Text>
            </div>
          </div>
          <div className="sb-learning-dock-actions">
            {mode === 'learning' && (
              <Tooltip title="返回今天">
                <Button
                  type="text"
                  shape="circle"
                  className="sb-learning-dock-back"
                  icon={<ArrowLeftOutlined />}
                  aria-label="返回今天"
                  onClick={onReturnToday}
                />
              </Tooltip>
            )}
            <Tooltip title="任务列表">
              <Button
                type="default"
                shape="circle"
                icon={<UnorderedListOutlined />}
                aria-label="任务列表"
                onClick={() => setTaskDrawerOpen(true)}
              />
            </Tooltip>
            <Button
              type="default"
              icon={<FileTextOutlined />}
              aria-label="今日学习总结"
              onClick={() => setSummaryDrawerOpen(true)}
            >
              <span className="sb-dock-summary-label">总结</span>
            </Button>
            {conversationActions}
            <Button type="primary" onClick={() => onAskAiToPlan?.()}>
              让 AI 帮我定
            </Button>
          </div>
        </section>
        {sharedDrawers}
      </>
    );
  }

  const currentTask: TodayLearningTask = {
    planId: currentPlan.id,
    planTitle: currentPlan.title,
    item: currentItem,
  };

  return (
    <>
      {mode === 'learning' ? (
        <section className="sb-learning-dock sb-learning-dock--learning" aria-label="今日学习任务">
          <Tooltip title="返回今天">
            <Button
              type="text"
              shape="circle"
              className="sb-learning-dock-back"
              icon={<ArrowLeftOutlined />}
              aria-label="返回今天"
              onClick={onReturnToday}
            />
          </Tooltip>
          <div className="sb-learning-dock-current">
            <span className="sb-learning-dock-live" aria-hidden="true" />
            <div>
              <Text strong className="sb-learning-dock-current-title">
                {currentItem.title}
              </Text>
              <Text type="secondary" className="sb-learning-dock-current-meta">
                {isCurrentItemToday
                  ? `进行中 · ${processedCount} / ${queueItems.length} · ${currentItem.minutes} 分钟`
                  : `${currentPlan?.title} · 进行中 · ${currentItem.minutes} 分钟`}
              </Text>
            </div>
          </div>
          <div className="sb-learning-dock-actions">
            <Tooltip title="任务列表">
              <Button
                type="default"
                shape="circle"
                icon={<UnorderedListOutlined />}
                aria-label="任务列表"
                onClick={() => setTaskDrawerOpen(true)}
              />
            </Tooltip>
            {conversationActions}
            <Button type="primary" loading={updating} onClick={() => void completeCurrentItem()}>
              完成学习
            </Button>
          </div>
        </section>
      ) : (
        <section className="sb-learning-dock sb-learning-dock--today" aria-label="今日学习任务">
          <div className="sb-learning-dock-current">
            <span className="sb-task-dock-progress">
              {processedCount + 1}/{queueItems.length}
            </span>
            <div>
              <Text strong className="sb-learning-dock-current-title">
                {currentItem.title}
              </Text>
              <Text type="secondary" className="sb-learning-dock-current-meta">
                {currentPlan.title} · 预计 {currentItem.minutes} 分钟
              </Text>
            </div>
          </div>
          <div className="sb-learning-dock-actions">
            <Tooltip title="任务列表">
              <Button
                type="default"
                shape="circle"
                icon={<UnorderedListOutlined />}
                aria-label="任务列表"
                onClick={() => setTaskDrawerOpen(true)}
              />
            </Tooltip>
            <Button
              type="default"
              icon={<FileTextOutlined />}
              aria-label="今日学习总结"
              onClick={() => setSummaryDrawerOpen(true)}
            >
              <span className="sb-dock-summary-label">总结</span>
            </Button>
            {conversationActions}
            <Button type="primary" onClick={() => onStartLearning(currentTask, currentLearningPrompt)}>
              继续学习
            </Button>
          </div>
        </section>
      )}
      {actionError && (
        <Alert
          className="sb-learning-dock-update-error"
          type="error"
          showIcon
          message={actionError}
        />
      )}
      <CompletionEvidenceModal
        open={evidenceTarget !== null}
        itemTitle={evidenceTarget?.title ?? ''}
        submitting={updating}
        initialValue={evidenceDraft}
        onCancel={() => {
          setEvidenceTarget(null);
          setEvidenceDraft('');
        }}
        onSubmit={handleEvidenceSubmit}
      />
      {sharedDrawers}
    </>
  );
}
