export type AttributeSubjectSource = 'exam_score' | 'manual_adjust';

export interface AttributeSnapshot {
  id: number;
  snapshot: {
    chinese?: number;
    math?: number;
    english?: number;
    pe?: number;
    engagement?: number;
    mastered_count?: number;
    subject_sources?: Partial<Record<'chinese' | 'math' | 'english' | 'pe' | 'engagement', AttributeSubjectSource>>;
  } & Record<string, unknown>;
  source: string;
  trigger_ref: string | null;
  created_at: string;
}

export interface InterestItem {
  id: number;
  tag: string;
  source: string;
  approved: boolean;
}

export interface FeedbackItem {
  id: number;
  feedback_type: string;
  content: string;
  created_at: string;
}

export interface RecommendationItem {
  id: number;
  title: string;
  platform: string;
  url: string;
  reason: string | null;
  clicked: boolean;
}

export interface RecommendationBoundary {
  student_id: number;
  allowed_platforms: string[];
  blocked_keywords: string[];
  daily_limit: number;
  allow_entertainment_interests: boolean;
}

export interface ProfileSummary {
  student_id: number;
  needs_onboarding: boolean;
  missing_fields: string[];
  summary: {
    grade?: string | null;
    semester?: string | null;
    school?: string | null;
    district?: string | null;
    textbook_versions?: Record<string, string>;
    recent_scores?: Record<string, number>;
    weak_subjects?: string[];
    study_preferences?: Record<string, unknown>;
    interests?: string[];
  };
}

export interface ProfileOnboardingRequest {
  grade?: string;
  semester?: string;
  school?: string;
  district?: string;
  textbook_versions?: Record<string, string>;
  recent_scores?: Record<string, number>;
  weak_subjects?: string[];
  study_preferences?: Record<string, unknown>;
  interests?: string[];
}

export interface StudyPlanItem {
  id: number;
  title: string;
  target: string | null;
  minutes: number;
  status: string;
  related_tags: string[];
  sort_order: number;
  completed_at: string | null;
}

export interface StudyPlan {
  id: number;
  student_id: number;
  title: string;
  focus: string | null;
  description?: string | null;
  context_refs?: Record<string, unknown> | null;
  revision?: number;
  status: string;
  planned_date: string | null;
  is_overdue: boolean;
  overdue_days: number;
  reminder_message: string | null;
  created_by: number | null;
  created_at: string;
  items: StudyPlanItem[];
}

export interface LearningFlowEntry {
  kind: 'continue_plan' | 'review_error' | 'review_knowledge' | 'empty';
  title: string;
  description: string;
  primary_label: string;
  prompt: string;
  source_type: 'study_plan' | 'error_book' | 'learning_map' | null;
  source_id: number | null;
  item_id: number | null;
  evidence: string[];
}

// === Daily learning records / progress ===
