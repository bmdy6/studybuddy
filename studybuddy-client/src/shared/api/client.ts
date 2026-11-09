import axios from 'axios';
import { API_TIMEOUTS, DEFAULT_API_BASE } from '@/shared/constants';
import { getStoredToken } from './token';
import { clearStoredAuth, redirectToLoginIfNeeded } from './authSession';
import { logger } from '@/shared/utils/logger';

// Vite 在构建时注入；本地和正式构建都尊重使用者提供的地址。
export const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;

const client = axios.create({
  baseURL: API_BASE,
  timeout: API_TIMEOUTS.DEFAULT,
});

interface AuthAwareConfig {
  __studybuddyAuthToken?: string | null;
}

// 请求拦截：从 zustand persist 存储读 JWT（与 authStore 同源，避免 sb_token 旧 key 不同步）
client.interceptors.request.use((config) => {
  const token = getStoredToken();
  (config as AuthAwareConfig).__studybuddyAuthToken = token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 响应拦截：401 清登录态并跳登录
client.interceptors.response.use(
  (response) => response,
  (error) => {
    const config = error.config;
    const requestToken = (config as AuthAwareConfig | undefined)?.__studybuddyAuthToken;
    logger.error(
      'api',
      `${config?.method?.toUpperCase() ?? '?'} ${config?.url ?? '?'} ${error.response?.status ?? 'network'}`,
      { status: error.response?.status, detail: error.response?.data?.detail },
    );
    if (clearStoredAuth(error.response?.status, requestToken)) {
      redirectToLoginIfNeeded();
    }
    return Promise.reject(error);
  },
);

export default client;

/** 从 axios 错误中提取后端返回的 detail 消息，回退到 Error.message */
export function getRequestErrorMessage(err: unknown): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
    (err as Error).message ??
    '未知错误'
  );
}
