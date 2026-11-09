import type { ErrorReportInfo } from '@/features/chat/store';
import { BRAND } from '@/shared/constants';

function sanitizeErrorText(value: string) {
  return value
    .replace(/Bearer\s+[A-Za-z0-9._-]+/gi, 'Bearer [redacted]')
    .replace(/token\s*[:=]\s*[^\s,;]+/gi, 'token=[redacted]')
    .replace(/password\s*[:=]\s*[^\s,;]+/gi, 'password=[redacted]')
    .replace(/api[_-]?key\s*[:=]\s*[^\s,;]+/gi, 'api_key=[redacted]');
}

export function buildErrorReportText(
  report: ErrorReportInfo,
  meta: { role?: string | null; userId?: number | null; path: string },
) {
  const lines = [
    `${BRAND.name}错误信息`,
    `time: ${new Date().toISOString()}`,
    `context: ${sanitizeErrorText(report.context)}`,
    `message: ${sanitizeErrorText(report.message)}`,
    `path: ${sanitizeErrorText(meta.path)}`,
    `role: ${meta.role ?? 'unknown'}`,
    `user_id: ${meta.userId ?? 'unknown'}`,
    `student_id: ${report.studentId ?? 'unknown'}`,
    `session_id: ${report.sessionId ?? 'unknown'}`,
  ];
  if (report.details) {
    lines.push(`details: ${sanitizeErrorText(report.details)}`);
  }
  return lines.join('\n');
}
