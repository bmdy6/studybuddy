export type LearningMapStatus = 'weak' | 'reviewing' | 'stable' | 'unknown';

export type LearningMapResourceType = 'error' | 'note' | 'material' | 'plan_item';

export interface LearningMapResource {
  id: number;
  title: string;
  type: LearningMapResourceType;
  status: string | null;
  summary: string;
  url: string | null;
}

export interface LearningMapNode {
  tag: string;
  status: LearningMapStatus;
  error_count: number;
  note_count: number;
  material_count: number;
  plan_item_count: number;
  last_wrong_at: string | null;
  next_actions: string[];
  resources: LearningMapResource[];
}

export interface LearningMapResponse {
  student_id: number;
  generated_at: string;
  nodes: LearningMapNode[];
  summary: Record<LearningMapStatus, number>;
  total_count: number;
  has_more: boolean;
}

// === Parent Supervision ===

export type LearningEvidenceTier = 'verified' | 'self_reported' | 'machine_extracted';

export interface DailyLearningEvidence {
  source_type: string;
  source_id: number;
  version: number;
  tier: LearningEvidenceTier;
  title?: string;
  [key: string]: unknown;
}

export interface DailyLearningFactsSnapshot {
  student_id: number;
  record_date: string;
  period_start: string | null;
  period_end: string | null;
  timezone: string;
  evidence: DailyLearningEvidence[];
  pending_tasks: { plan_title: string; item_title: string }[];
  self_reported_duration_minutes: number;
  has_verified_evidence: boolean;
}

export interface DailyLearningRecord {
  id: number;
  student_id: number;
  record_date: string;
  facts_snapshot: DailyLearningFactsSnapshot;
  summary_text: string | null;
  evidence_hash: string | null;
  generation_status: 'pending' | 'generating' | 'ready' | 'failed';
  summary_source: 'ai' | 'deterministic' | null;
  checkin_status: 'pending' | 'done' | null;
  checkin_response: string | null;
  checked_in_at: string | null;
  generated_at: string | null;
  finalized_at: string | null;
  created_at: string;
  updated_at: string;
}

export type CheckinChoiceKey = 'follow_plan' | 'adjust' | 'reduce';

export interface DailyCheckinChoice {
  key: CheckinChoiceKey;
  label: string;
}

export type DailyCheckinState =
  | 'yesterday_completed'
  | 'yesterday_incomplete'
  | 'consecutive_incomplete'
  | 'no_plan'
  | 'already_done';

export interface DailyCheckinStatus {
  record_date: string;
  status: DailyCheckinState;
  state: DailyCheckinState;
  message: string;
  task_count: number;
  estimated_minutes: number;
  unfinished_days: number;
  primary_action: CheckinChoiceKey | null;
  primary_recommendation: CheckinChoiceKey | null;
  choices: DailyCheckinChoice[];
  checkin_status: 'pending' | 'done' | null;
  checkin_response: CheckinChoiceKey | null;
  checked_in_at: string | null;
}

export interface TodayProgress {
  completed_count: number;
  total_count: number;
  completion_rate: number | null;
  status: 'no_plan' | 'planned' | 'completed';
}

export interface DayProgress {
  record_date: string;
  status: 'future' | 'no_plan' | 'planned' | 'active';
  completed_count: number;
}

export interface LearningProgressMetrics {
  student_id: number;
  as_of: string;
  today: TodayProgress;
  streak_days: number;
  week: DayProgress[];
  recent_7_days_completed_tasks: number;
}
