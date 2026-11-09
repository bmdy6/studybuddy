export interface ErrorQuestionItem {
  error_id: number;
  question_id: number;
  stem: string;
  student_answer: string;
  correct_answer: string;
  error_count: number;
  knowledge_tags: string[]; // 降级为题卡标签
}

export interface ErrorTypeGroup {
  question_type: string; // 原始类型 key
  type_label: string; // 中文展示名（阅读理解/完形填空/单选题…）
  error_count: number;
  last_wrong_at: string;
  questions: ErrorQuestionItem[];
}

export interface ErrorSubjectGroup {
  subject: string; // english / math / chinese（对齐后端 exams.subject）
  total_count: number;
  type_groups: ErrorTypeGroup[];
}

// === Diagnosis ===

export interface WeakPoint {
  tag: string;
  wrong_count: number;
  error_rate: number;
  total_attempts: number;
  mastered: boolean;
}

export interface DiagnosisResponse {
  student_id: number;
  student_name: string;
  weak_points: WeakPoint[];
  mastered_tags: string[];
  generated_at: string;
}

// === Learning Map ===
