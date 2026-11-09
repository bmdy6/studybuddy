export interface ChatSession {
  id: number;
  user_id: number;
  student_id: number;
  title: string;
  created_at: string;
  session_type: string;
  plan_id: number | null;
  plan_item_id: number | null;
  status: string;
}

export interface ChatMessage {
  id: number;
  role: 'user' | 'assistant' | 'tool';
  content: string | null;
  tool_calls?: unknown;
  tool_result?: unknown;
  created_at: string;
}

// SSE 事件流类型（后端推送）

export type ChatEvent =
  | { type: 'text'; content: string }
  | { type: 'reasoning'; content: string }
  | { type: 'tool_call'; name: string; input: unknown; id: string; started_at?: number }
  | {
      type: 'tool_progress';
      name: string;
      id: string;
      elapsed_ms: number;
      message?: string;
    }
  | { type: 'tool_result'; name: string; output: string; id: string; elapsed_ms?: number }
  | { type: 'error'; message: string }
  | { type: 'session'; session: ChatSession }
  | { type: 'done'; content: string };

// === P2.1 属性面板/兴趣/反馈/推荐 ===
/** 能力项证据来源：exam_score=大考录入，manual_adjust=agent 微调。未标记视为无证据。 */
