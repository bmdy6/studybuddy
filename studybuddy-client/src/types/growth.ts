export interface SupervisionReminderItem {
  plan_id: number;
  title: string;
  planned_date: string | null;
  is_overdue: boolean;
  overdue_days: number;
  todo_count: number;
  todo_minutes: number;
  first_todo_title: string;
  reminder_message: string;
}

export interface SupervisionSupportItem {
  note_id: number;
  title: string;
  content: string;
  created_at: string;
}

export interface SupervisionWeakPointItem {
  tag: string;
  status: string;
  error_count: number;
  last_wrong_at: string | null;
  next_action: string;
}

export interface SupervisionAssignmentItem {
  assignment_id: number;
  exam_id: number;
  exam_title: string;
  status: string;
  due_at: string | null;
  note: string | null;
  created_at: string;
}

export interface WeeklyReportDraft {
  title: string;
  is_empty: boolean;
  summary: string;
  highlights: string[];
  next_suggestions: string[];
  sources: string[];
}

export interface SupervisionSummaryResponse {
  student_id: number;
  student_name: string | null;
  reminders: SupervisionReminderItem[];
  support_items: SupervisionSupportItem[];
  weak_points: SupervisionWeakPointItem[];
  recent_assignments: SupervisionAssignmentItem[];
  weekly_report: WeeklyReportDraft;
}

// === Material ===

export interface NotificationItem {
  id: number;
  recipient_id: number;
  student_id: number | null;
  title: string;
  content: string;
  notification_type: string;
  source_type: string;
  source_id: number | null;
  read_at: string | null;
  created_at: string;
}

export interface NotificationListResponse {
  items: NotificationItem[];
  unread_count: number;
}

// === Notes ===
