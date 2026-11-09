// 导航状态（当前会话/是否在计划/主会话id）按学生隔离持久化。
// 只存导航态，不存消息/流式运行态（刷新后流已断、靠 getMessages 重载历史）。
// 解决"刷新后 mainSessionId 丢失、找不到主会话"根因。

interface NavState {
  sessionId: number | null;
  activeTaskSessionId: number | null;
  mainSessionId: number | null;
}

function navKey(studentId: number): string {
  return `studybuddy-nav-${studentId}`;
}

export function saveNavState(studentId: number, state: NavState): void {
  try {
    localStorage.setItem(navKey(studentId), JSON.stringify(state));
  } catch {
    // localStorage 不可用时仅本会话静默
  }
}

export function loadNavState(studentId: number): NavState | null {
  try {
    const raw = localStorage.getItem(navKey(studentId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as NavState;
    if (parsed === null || typeof parsed !== 'object') return null;
    if (parsed.sessionId !== null && typeof parsed.sessionId !== 'number') return null;
    return parsed;
  } catch {
    return null;
  }
}

export function clearNavState(studentId: number): void {
  try {
    localStorage.removeItem(navKey(studentId));
  } catch {
    // 静默
  }
}

export type { NavState };
