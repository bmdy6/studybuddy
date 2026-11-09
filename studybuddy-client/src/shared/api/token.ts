/**
 * 从 zustand persist 存储里读 token（供 api/client.ts 用，避免循环依赖）。
 *
 * 纯 localStorage 读取，不依赖 zustand，避免 client -> authStore 反向依赖。
 * persist key 与 stores/authStore 的 { name: 'studybuddy-auth' } 一致。
 */
export function getStoredToken(): string | null {
  try {
    const raw = localStorage.getItem('studybuddy-auth');
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed?.state?.token ?? null;
  } catch {
    return null;
  }
}
