export type QuestionType =
  | 'single_choice'
  | 'multi_choice'
  | 'fill_blank'
  | 'transform'
  | 'translation'
  | 'essay'
  | 'math_answer';

export type FeedbackMode = 'immediate' | 'after_submit' | 'hidden';

export interface ExamListItem {
  id: number;
  title: string;
  subject: string;
  status: string;
  visibility?: string;
  assignment_status?: string;
  assignment_note?: string | null;
  assignment_due_at?: string | null;
  question_count: number;
  total_score: number;
  has_new: boolean;
  created_at: string;
  latest_record_status?: string | null;
  latest_record_id?: number | null;
}

export interface ExamAssignmentRequest {
  student_ids: number[];
  due_at?: string | null;
  note?: string | null;
}

export interface ExamAssignmentItem {
  id: number;
  exam_id: number;
  student_id: number;
  student_name: string;
  status: string;
  due_at: string | null;
  note: string | null;
}

export interface QuestionResponse {
  id: number;
  type: QuestionType;
  stem: string;
  options: string[] | null;
  score: number;
  group_id: string | null;
  // ★ 没有 answer_json —— 后端不下发
}

export interface ExamDetail {
  id: number;
  title: string;
  feedback_mode: FeedbackMode;
  questions: QuestionResponse[];
}

export interface StartExamResponse {
  exam_record_id: number;
  exam_id: number;
  status: string;
}

// === Exam Import ===

export interface GradingInput {
  rule_type: 'auto_exact' | 'auto_fuzzy' | 'manual';
  matcher: 'exact' | 'regex' | 'float_tol' | 'levenshtein';
  match_params: Record<string, unknown>;
}

export interface QuestionInput {
  type: QuestionType;
  stem: string;
  options: string[] | null;
  answer: unknown; // 标准答案
  score: number;
  knowledge_tags: string[];
  group_id: string | null;
  grading: GradingInput;
}

// === Answer ===

export interface AnswerSubmit {
  question_id: number;
  student_answer: string;
}

export interface SubmitRequest {
  exam_record_id: number;
  answers: AnswerSubmit[];
}

export interface SubmitResponse {
  exam_record_id: number;
  status: string;
  objective_score: number;
  pending_manual_count: number;
}

export interface ExamRecordAnswerResult {
  answer_id: number;
  question_id: number;
  question_stem: string;
  question_type: QuestionType;
  student_answer: string;
  correct_answer: string | null;
  is_correct: boolean | null;
  score: number | null;
  max_score: number;
  graded: boolean;
  knowledge_tags: string[];
}

export interface ExamRecordResult {
  exam_record_id: number;
  exam_id: number;
  exam_title: string;
  status: string;
  total_score: number | null;
  feedback_mode: FeedbackMode;
  answers: ExamRecordAnswerResult[];
}

export interface PendingGradeItem {
  answer_id: number;
  exam_record_id: number;
  student_name: string;
  exam_title: string;
  question_id: number;
  question_stem: string;
  question_type: string;
  max_score: number;
  student_answer: string;
  reference_answer: string;
  submitted_at: string;
}

export interface GradeManualResponse {
  answer_id: number;
  graded: boolean;
  score: number;
  is_correct: boolean;
  graded_at: string;
}

// === Error Book（两级：学科 → 题型） ===
// subject 为 english/math/chinese（对齐后端 exams.subject）；前端用 SUBJECT_LABELS 转中文。

export interface CreateBatchRequest {
  student_id: number;
  subject?: string;
  exam_name: string;
  exam_date: string; // YYYY-MM-DD
}

export interface BatchItem {
  id: number;
  student_id: number;
  subject: string;
  exam_name: string;
  exam_date: string;
  photo_material_ids: number[];
  parsed_pdf_ref: string | null;
  folder_name: string | null;
  status: string;
  created_at: string;
}

export interface ParsedQuestion {
  no: string; // 题号
  answer: string; // 学生作答
  score: string | null; // 老师批改分数（无则 null）
}

export interface ParseResult {
  batch_id: number;
  questions: ParsedQuestion[];
  raw_text: string;
}

export interface PhotoAnswerReviewItem {
  question_no: string;
  detected_answer: string | null;
  confirmed_answer: string | null;
  confidence: 'high' | 'medium' | 'low';
  needs_review: boolean;
  review_reason: string | null;
  answer_type: 'choice' | 'text' | 'unknown';
  source_excerpt: string | null;
  skipped: boolean;
}

export interface PhotoAnswerReviewState {
  batch_id: number;
  recognized_markdown: string;
  items: PhotoAnswerReviewItem[];
  status: 'pending_review' | 'confirmed' | 'graded';
  confirmed_at?: string | null;
}

export interface ConfirmAnswerReviewRequest {
  items: PhotoAnswerReviewItem[];
}

/** 判分模式（对齐后端 grade_and_save_errors） */

export type GradeMode = 'has_score' | 'no_score_has_answer' | 'no_score_no_answer';
