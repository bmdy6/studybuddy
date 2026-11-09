export interface MaterialUploadResponse {
  material_id: number;
  name: string;
  type: string;
  source: string;
  cos_key: string;
  uploaded_by: string;
  created_at: string;
  is_duplicate?: boolean;
  duplicate_of_material_id?: number | null;
  student_id?: number | null;
}

export interface MaterialItem {
  id: number;
  name: string;
  type: string;
  source: string;
  knowledge_tags: string[];
  recognition_status: string;
  uploaded_by: string;
  cos_url: string;
  created_at: string;
  student_id?: number | null;
  auto_ready?: boolean;
  is_duplicate?: boolean;
}

export interface MaterialExtraction {
  material_id: number;
  name: string;
  recognition_status: string;
  raw_text?: string | null;
  recognized_markdown?: string | null;
  confirmed_markdown?: string | null;
  summary?: string | null;
  content_type?: string | null;
  recognition_provider?: string | null;
  recognition_confidence?: string | null;
  uncertain_points: string[];
  recognized_at?: string | null;
  confirmed_at?: string | null;
  auto_ready?: boolean;
  content_fingerprint?: string | null;
  duplicate_of_material_id?: number | null;
}

// === Question Bank ===
// agg-1 materials
