export type QuestionBankPaperStatus = 'candidate' | 'confirmed' | 'rejected' | 'internal_style';

export interface QuestionBankPaperItem {
  id: number;
  title: string;
  source_url: string;
  snippet: string | null;
  province: string | null;
  city: string | null;
  district: string | null;
  school: string | null;
  grade: string | null;
  semester: string | null;
  subject: string | null;
  textbook_version: string | null;
  year: number | null;
  exam_type: string | null;
  source_type: string;
  availability_level: string;
  risk_level: string;
  status: QuestionBankPaperStatus;
  confidence: number;
  source_adapter: string | null;
  review: {
    verdict: string;
    confidence: number;
    completeness: string;
    suggested_status: QuestionBankPaperStatus;
    evidence: {
      question_count_estimate?: number;
      last_question_no?: string | null;
      has_answer_signal?: boolean;
      preview_signals?: string[];
      access_block_signals?: string[];
      status_code?: number;
      content_type?: string;
      is_pdf?: boolean;
    };
    reasons: string[];
    checked_at: string;
  } | null;
}

export interface QuestionBankReviewBreakdown {
  verdict: string;
  total_count: number;
  sampled_count: number;
  agreement_count: number;
  confirmed_count: number;
  rejected_count: number;
  internal_style_count: number;
  candidate_count: number;
}

export interface QuestionBankReviewMetrics {
  total_reviewed: number;
  sampled_count: number;
  agreement_count: number;
  agreement_rate: number | null;
  formal_ready_sampled_count: number;
  formal_ready_false_positive_count: number;
  formal_ready_false_positive_rate: number | null;
  reject_sampled_count: number;
  reject_false_negative_count: number;
  reject_false_negative_rate: number | null;
  min_sample_size: number;
  max_formal_ready_false_positive_rate: number;
  auto_approve_allowed: boolean;
  verdict_breakdown: QuestionBankReviewBreakdown[];
}

export interface SearchPaperSourcesRequest {
  province?: string;
  city?: string;
  district?: string;
  school?: string;
  grade: string;
  semester?: string;
  subject: string;
  textbook_version?: string;
  exam_type?: string;
  year?: number;
  limit?: number;
}

export interface CreatePaperSourceRequest {
  title: string;
  source_url: string;
  snippet?: string;
  province?: string;
  city?: string;
  district?: string;
  school?: string;
  grade: string;
  semester?: string;
  subject: string;
  textbook_version?: string;
  exam_type?: string;
  year?: number;
  source_adapter?: string;
}

export interface ValidateUploadedPaperFileResponse {
  filename: string;
  content_type: string | null;
  source_type: string;
  content_length: number;
  text_length: number;
  question_count_estimate: number;
  last_question_no: string | null;
  has_answer_signal: boolean;
  can_parse_text: boolean;
  suggested_status: QuestionBankPaperStatus;
  warnings: string[];
  preview_text: string | null;
}

export interface UploadPaperSourceRequest {
  file: File;
  title?: string;
  province?: string;
  city?: string;
  district?: string;
  school?: string;
  grade: string;
  semester?: string;
  subject: string;
  textbook_version?: string;
  exam_type?: string;
  year?: number;
}

export interface UploadedPaperSourceResponse {
  paper: QuestionBankPaperItem;
  validation: ValidateUploadedPaperFileResponse;
}

export interface SearchPaperSourcesResponse {
  queries: string[];
  saved_count: number;
  candidates: QuestionBankPaperItem[];
}

export interface PaperSourceFullPreviewResponse {
  paper_id: number;
  status: string;
  content_kind: string;
  title: string;
  message: string;
  source_url: string;
  final_url: string | null;
  text: string | null;
  text_length: number;
  question_count_estimate: number;
  last_question_no: string | null;
  has_answer_signal: boolean;
  can_parse: boolean;
  warnings: string[];
}

export interface QuestionBankItem {
  id: number;
  subject: string | null;
  grade: string | null;
  semester: string | null;
  question_type: string;
  stem: string;
  options: unknown[] | null;
  answer: string | null;
  explanation: string | null;
  knowledge_tags: unknown[];
  difficulty: string | null;
  status: string;
  duplicate_key: string;
}

export interface ParsePaperSourceResponse {
  paper_id: number;
  parsed_count: number;
  saved_count: number;
  items: QuestionBankItem[];
  warnings: string[];
}

// === Chat（P2 agent 化） ===
