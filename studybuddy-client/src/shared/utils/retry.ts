/**
 * 带退避重试的异步调用包装。
 *
 * 仅重试瞬时错误（网络错误、5xx、408、429）；4xx（401/403/404 等）直接抛出，
 * 避免对权限或资源不存在类错误做无意义重试。
 * 重试间隔指数退避：baseDelayMs * 2^attempt（默认 500ms -> 1000ms）。
 */

const RETRYABLE_STATUS = new Set([408, 429, 500, 502, 503, 504]);

interface RetryOptions {
  /** 额外重试次数（不含首次调用），默认 2 */
  retries?: number;
  /** 首次重试退避基准毫秒，默认 500 */
  baseDelayMs?: number;
}

function isRetryableError(err: unknown): boolean {
  const status = (err as { response?: { status?: number } })?.response?.status;
  // 无 response 视为网络错误（断网/超时），可重试；否则只重试可重试状态码
  return status === undefined || RETRYABLE_STATUS.has(status);
}

export async function withRetry<T>(fn: () => Promise<T>, options: RetryOptions = {}): Promise<T> {
  const { retries = 2, baseDelayMs = 500 } = options;
  let lastError: unknown;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      if (attempt === retries || !isRetryableError(err)) {
        throw err;
      }
      const delay = baseDelayMs * 2 ** attempt;
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }
  // 理论不可达：循环内要么 return 要么 throw；此处仅为 TS 类型守卫
  throw lastError;
}
