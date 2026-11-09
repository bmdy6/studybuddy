/**
 * 前端统一日志：级别控制 + tag + 时间戳，便于排查生产问题。
 *
 * 用法：
 *   import { logger } from '@/shared/utils/logger';
 *   logger.info('chat', '发送消息', { prompt });
 *   logger.error('api', '请求失败', { url, status });
 *
 * 级别由 VITE_LOG_LEVEL 控制（debug/info/warn/error），默认 info。
 * 生产环境浏览器控制台可见；后续可接入 Sentry 等上报平台。
 */

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const LEVEL_PRIORITY: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

const currentLevel: LogLevel = (import.meta.env.VITE_LOG_LEVEL as LogLevel) || 'info';

function log(level: LogLevel, tag: string, message: string, extra?: unknown) {
  if (LEVEL_PRIORITY[level] < LEVEL_PRIORITY[currentLevel]) return;
  const fn = level === 'error' ? console.error : level === 'warn' ? console.warn : console.log;
  const ts = new Date().toISOString();
  fn(`[${ts}] [${level.toUpperCase()}] [${tag}] ${message}`, extra ?? '');
}

export const logger = {
  debug: (tag: string, message: string, extra?: unknown) => log('debug', tag, message, extra),
  info: (tag: string, message: string, extra?: unknown) => log('info', tag, message, extra),
  warn: (tag: string, message: string, extra?: unknown) => log('warn', tag, message, extra),
  error: (tag: string, message: string, extra?: unknown) => log('error', tag, message, extra),
};
