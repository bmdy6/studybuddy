import client from '@/shared/api/client';
import type {
  CreateFamilyGoalRequest,
  CreateFamilyTaskRequest,
  FamilyEvidenceUploadResponse,
  FamilyGoal,
  FamilyGoalContext,
  FamilyGoalTask,
  FamilyRewardSummary,
  FamilyTodayTask,
  SubmitFamilyOccurrenceRequest,
} from '@/types';

/** 家庭目标与任务激励 API：目标/任务/今日任务/提交证据/奖励累计。 */
export const familyGoalApi = {
  listGoals: (studentId: number) =>
    client.get<FamilyGoal[]>(`/api/students/${studentId}/family-goals`).then((r) => r.data),

  createGoal: (studentId: number, data: CreateFamilyGoalRequest) =>
    client.post<FamilyGoal>(`/api/students/${studentId}/family-goals`, data).then((r) => r.data),

  createTask: (goalId: number, data: CreateFamilyTaskRequest) =>
    client.post<FamilyGoalTask>(`/api/family-goals/${goalId}/tasks`, data).then((r) => r.data),

  todayTasks: (studentId: number, date?: string) =>
    client
      .get<FamilyTodayTask[]>(`/api/students/${studentId}/today-family-tasks`, {
        params: date ? { date } : undefined,
      })
      .then((r) => r.data),

  submitOccurrence: (occurrenceId: number, data: SubmitFamilyOccurrenceRequest) =>
    client
      .post<FamilyTodayTask>(`/api/family-task-occurrences/${occurrenceId}/submit`, data)
      .then((r) => r.data),

  uploadEvidence: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return client
      .post<FamilyEvidenceUploadResponse>('/api/family-task-evidence/upload', form)
      .then((r) => r.data);
  },

  rewards: (studentId: number) =>
    client.get<FamilyRewardSummary>(`/api/students/${studentId}/family-rewards`).then((r) => r.data),

  /** 是否有家长审核账号绑定了该学生：没人绑就没人能确认作业、发奖励。 */
  parentBound: (studentId: number) =>
    client
      .get<FamilyGoalContext>(`/api/students/${studentId}/family-goal-context`)
      .then((r) => r.data),

  /** 今日任务：从任务列表里取（同一份数据，避免额外接口）。 */
  rewardTotalOf: (summary: FamilyRewardSummary | null) => summary?.total_amount ?? '0.00',
};

/** 金额展示：后端给两位小数字符串，「5.00」显示 ¥5，「5.50」显示 ¥5.50。 */
export function formatRewardAmount(amount?: string | null): string | null {
  if (!amount) return null;
  const value = Number(amount);
  if (Number.isNaN(value)) return `¥${amount}`;
  return `¥${Number.isInteger(value) ? value : value.toFixed(2)}`;
}

export const FAMILY_TASK_STATUS_LABELS: Record<string, string> = {
  pending: '待完成',
  submitted: '待家长确认',
  approved: '已确认',
  rejected: '已驳回',
};
