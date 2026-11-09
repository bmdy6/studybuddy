/** 家庭目标与任务激励：与后端 app/features/family_goal/schemas.py 契约一致，金额均为字符串。 */

export interface FamilyGoal {
  id: number;
  student_id: number;
  title: string;
  description: string | null;
  reward_amount: string | null;
  creator_role: 'student' | 'parent';
  status: 'active' | 'completed' | 'archived';
  start_date: string | null;
  end_date: string | null;
  created_at: string | null;
}

export interface FamilyGoalTask {
  id: number;
  goal_id: number;
  student_id: number;
  title: string;
  description: string | null;
  repeat_type: 'once' | 'daily';
  reward_amount: string | null;
  resolved_reward_amount: string | null;
  status: 'active' | 'archived';
  sort_order: number;
}

export type FamilyTaskStatus = 'pending' | 'submitted' | 'approved' | 'rejected';

export interface FamilyTaskEvidence {
  id: number;
  url: string;
  sort_order: number;
}

export interface FamilyTodayTask {
  occurrence_id: number;
  task_id: number;
  goal_id: number;
  student_id: number;
  title: string;
  description: string | null;
  goal_title: string;
  repeat_type: 'once' | 'daily';
  status: FamilyTaskStatus;
  occurrence_date: string;
  reward_amount: string | null;
  submit_note: string | null;
  reject_reason: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  evidence: FamilyTaskEvidence[];
}

export interface FamilyRewardRecord {
  id: number;
  occurrence_id: number;
  task_title: string;
  goal_title: string | null;
  amount: string;
  confirmed_at: string | null;
}

export interface FamilyRewardSummary {
  student_id: number;
  total_amount: string;
  records: FamilyRewardRecord[];
}

/** 家庭任务上下文：是否有家长审核账号绑定了该学生（没人绑就没人能确认作业）。 */
export interface FamilyGoalContext {
  parent_bound: boolean;
}

export interface CreateFamilyGoalRequest {
  title: string;
  description?: string | null;
  reward_amount?: string | null;
}

export interface CreateFamilyTaskRequest {
  title: string;
  description?: string | null;
  repeat_type?: 'once' | 'daily';
  reward_amount?: string | null;
}

export interface SubmitFamilyOccurrenceRequest {
  note?: string | null;
  evidence_refs?: string[];
}

export interface FamilyEvidenceUploadResponse {
  content_ref: string;
  url: string;
}
