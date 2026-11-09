/** 品牌配置 -- 改名只改这一处 */
export { BRAND } from './brand';

/** 角色 -- 后端 users.role 枚举对齐 */
export const ROLES = {
  PARENT: 'parent',
  STUDENT: 'student',
} as const;
export type Role = (typeof ROLES)[keyof typeof ROLES];

/** 题型中文标签 —— 与后端 QUESTION_TYPE_LABELS 对齐（阶段二） */
export const QUESTION_TYPE_LABELS: Record<string, string> = {
  single_choice: '单选题',
  multi_choice: '多选题',
  fill_blank: '填空题',
  transform: '句型转换',
  translation: '翻译题',
  essay: '作文',
  math_answer: '解答题',
};

/** 默认题型分组名（题组 group_id 为空时回退用） */
export const DEFAULT_TYPE_LABEL = '其他';

/** 素材类型 —— 与后端 material.type 对齐（自由字符串，非枚举） */
export const MATERIAL_TYPES = ['pdf', 'doc', 'image', 'audio', 'video', 'other'] as const;

/** 素材类型下拉选项 -- ChatPage 和 MaterialsPage 共用 */
export const MATERIAL_TYPE_OPTIONS = [
  { value: 'pdf', label: 'PDF' },
  { value: 'doc', label: '文档' },
  { value: 'image', label: '图片' },
  { value: 'audio', label: '音频' },
  { value: 'video', label: '视频' },
  { value: 'other', label: '其他' },
];

/** 学科 key → 中文展示名 —— 对齐后端 exams.subject (english/math/chinese) */
export const SUBJECT_LABELS: Record<string, string> = {
  english: '英语',
  math: '数学',
  chinese: '语文',
};

/** 默认学科顺序（错题本文件夹默认语数英） */
export const DEFAULT_SUBJECTS = ['chinese', 'math', 'english'] as const;

/** 自托管 API：显式配置优先，默认只连接本机。 */
export const DEFAULT_API_BASE = 'http://127.0.0.1:8001';
export const WECHAT_ENABLED = import.meta.env.VITE_WECHAT_ENABLED === 'true';

/** API 超时配置（毫秒） */
export const API_TIMEOUTS = {
  DEFAULT: 15000,
  PHOTO_UPLOAD: 60000,
  VISION_PARSE: 90000,
} as const;

/** 默认分页/列表限制 */
export const DEFAULT_PENDING_GRADE_LIMIT = 20;
