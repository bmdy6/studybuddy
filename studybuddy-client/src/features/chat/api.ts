import client, { API_BASE } from '@/shared/api/client';
import { getStoredToken } from '@/shared/api/token';
import { clearStoredAuth, redirectToLoginIfNeeded } from '@/shared/api/authSession';
import type { ChatSession, ChatMessage, ChatEvent } from '@/types';

// SSE 端点用 fetch（EventSource 不支持 Authorization header）
const SSE_BASE = API_BASE;

async function readErrorMessage(resp: Response): Promise<string> {
  try {
    const data = await resp.clone().json();
    if (typeof data?.detail === 'string') return data.detail;
  } catch {
    // 响应不是 JSON 时继续读文本。
  }
  try {
    const text = await resp.text();
    return text || `HTTP ${resp.status}`;
  } catch {
    return `HTTP ${resp.status}`;
  }
}

/** 打开 SSE 流，处理 401 过期 + 非 2xx 错误。 */
async function _openSSE(url: string, init: RequestInit, token: string | null): Promise<Response> {
  const resp = await fetch(url, {
    ...init,
    headers: {
      ...(init.headers || {}),
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });
  if (!resp.ok || !resp.body) {
    if (clearStoredAuth(resp.status, token)) {
      redirectToLoginIfNeeded();
      throw new Error('登录已过期，请重新登录');
    }
    const detail = await readErrorMessage(resp);
    throw new Error(`SSE 连接失败: ${detail}`);
  }
  return resp;
}

/** 解析 SSE 响应流，逐个 yield ChatEvent。收到 done/error 后主动终止。 */
async function* _parseSSE(resp: Response): AsyncGenerator<ChatEvent> {
  const reader = resp.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE 事件以 \n\n 分隔
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';
    for (const part of parts) {
      const line = part.trim();
      if (line.startsWith('data: ')) {
        try {
          const evt = JSON.parse(line.slice(6)) as ChatEvent;
          yield evt;
          // 收到 done/error 事件后主动终止 generator，
          // 不依赖 HTTP 流 EOF（生产经 nginx 代理 EOF 可能不及时到达）
          if (evt.type === 'done' || evt.type === 'error') {
            reader.cancel().catch(() => undefined);
            return;
          }
        } catch (err) {
          console.warn('SSE 事件解析失败', { line, err });
        }
      }
    }
  }
  // 处理残留 buffer
  if (buffer.startsWith('data: ')) {
    try {
      yield JSON.parse(buffer.slice(6)) as ChatEvent;
    } catch (err) {
      console.warn('SSE 残留事件解析失败', { buffer, err });
    }
  }
}

export const chatApi = {
  createSession: (studentId: number) =>
    client.post<ChatSession>('/api/chat/sessions', { student_id: studentId }).then((r) => r.data),

  listSessions: () => client.get<ChatSession[]>('/api/chat/sessions').then((r) => r.data),

  getMessages: (sessionId: number) =>
    client.get<ChatMessage[]>(`/api/chat/sessions/${sessionId}/messages`).then((r) => r.data),

  renameSession: (sessionId: number, title: string) =>
    client.patch<ChatSession>(`/api/chat/sessions/${sessionId}`, { title }).then((r) => r.data),

  deleteSession: (sessionId: number) =>
    client.delete(`/api/chat/sessions/${sessionId}`).then((r) => r.data),

  resetContext: (sessionId: number) =>
    client.post(`/api/chat/sessions/${sessionId}/context/reset`).then((r) => r.data),

  /**
   * 流式发消息：返回 async generator，逐个 yield ChatEvent。
   * 后端 SSE 格式: data: {"type":"text","content":"..."}\n\n
   */
  async *sendMessage(
    sessionId: number,
    content: string,
    displayContent?: string,
    signal?: AbortSignal,
  ): AsyncGenerator<ChatEvent> {
    const token = getStoredToken();
    const url = `${SSE_BASE}/api/chat/sessions/${sessionId}/messages`;
    const resp = await _openSSE(
      url,
      {
        method: 'POST',
        signal,
        body: JSON.stringify({ content, display_content: displayContent }),
      },
      token,
    );
    yield* _parseSSE(resp);
  },

  /**
   * 继续某个计划项的学习（U-042）：后端建/恢复 task session 并触发 agent。
   * 流式返回：先 session 事件（task session 信息），再 agent 事件，最后 done。
   */
  async *continueTaskItem(
    studentId: number,
    itemId: number,
    signal?: AbortSignal,
  ): AsyncGenerator<ChatEvent> {
    const token = getStoredToken();
    const url = `${SSE_BASE}/api/chat/students/${studentId}/plan-items/${itemId}/continue`;
    const resp = await _openSSE(url, { method: 'POST', signal }, token);
    yield* _parseSSE(resp);
  },
};
