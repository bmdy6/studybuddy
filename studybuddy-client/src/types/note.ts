export interface NoteItem {
  id: number;
  student_id: number;
  type: string;
  title: string;
  subject: string;
  category: string | null; // 学科下细分分类，agent 判断（词汇/语法/阅读…）
  content: string;
  knowledge_tags: string[];
  source: string;
  source_ref: unknown[];
  status: string;
  created_at: string;
  updated_at: string;
}

/** save_note 落草稿后对话里渲染的草案卡状态：弟弟确认/编辑后才转 confirmed 正式笔记。 */

export interface NoteDraftState {
  id: number;
  title: string;
  subject: string;
  category: string;
  content: string;
  knowledge_tags: string[];
  source: string;
  status: string; // draft（待确认）
}

export interface CreateNoteRequest {
  student_id: number;
  title: string;
  subject?: string;
  category?: string | null;
  content?: string;
  knowledge_tags?: string[];
  source?: string;
  source_ref?: unknown[];
  status?: 'draft' | 'confirmed';
}

export interface BlindSpotItem {
  tag: string;
  error_count: number;
  last_wrong_at: string;
  note_count: number;
}

// === Exam Batch（错题导入：拍照→合成PDF→视觉解析→判分入错题本） ===
