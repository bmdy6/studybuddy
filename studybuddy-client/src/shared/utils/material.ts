import { MATERIAL_TYPES } from '@/shared/constants';

/** 文件后缀 → 素材类型映射。覆盖常见学习资料格式。 */
const EXT_TYPE_MAP: Record<string, string> = {
  pdf: 'pdf',
  doc: 'doc',
  docx: 'doc',
  txt: 'doc',
  md: 'doc',
  png: 'image',
  jpg: 'image',
  jpeg: 'image',
  gif: 'image',
  webp: 'image',
  bmp: 'image',
  mp3: 'audio',
  wav: 'audio',
  m4a: 'audio',
  aac: 'audio',
  mp4: 'video',
  mov: 'video',
  mkv: 'video',
  avi: 'video',
};

/** 取文件名后缀（小写），无后缀返回空串。 */
function getExt(filename: string): string {
  const idx = filename.lastIndexOf('.');
  return idx > 0 ? filename.slice(idx + 1).toLowerCase() : '';
}

/** 根据文件名后缀判断素材类型，未知返回 'other'。 */
export function detectMaterialType(filename: string): string {
  const ext = getExt(filename);
  return EXT_TYPE_MAP[ext] ?? 'other';
}

/** 默认素材名：去掉后缀的文件名（批量导入时预填，用户可改）。 */
export function defaultMaterialName(filename: string): string {
  const idx = filename.lastIndexOf('.');
  return idx > 0 ? filename.slice(0, idx) : filename;
}

/** 类型守卫：归一化到 MATERIAL_TYPES，越界回退 'other'。 */
export function normalizeMaterialType(t: string): string {
  return (MATERIAL_TYPES as readonly string[]).includes(t) ? t : 'other';
}

/** 归一化素材标签：去空白、去空值、去重。 */
export function normalizeMaterialTags(tags: string[] | undefined): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  for (const raw of tags ?? []) {
    const tag = raw.trim();
    if (!tag || seen.has(tag)) continue;
    seen.add(tag);
    result.push(tag);
  }
  return result;
}
// agg-1 materials
