/**
 * 历史消息保守 Markdown 修复（前端第二道保险，批次 2）。
 *
 * 背景：批次 1 结构化终态协议保证新消息格式正确；但历史消息（数据库已存的
 * 单行文本，如 `--- ### 标题` 挤一行）需要显示层兜底。规则比后端更保守：
 * 只修高置信模式，数学表达式（a > 0、x - b、-b/2a）一律不动。
 *
 * 规则（与后端 legacy_markdown_repair.py 对齐，仅高置信子集）：
 * 0. 先保护 fenced code / inline code / $..$ 公式 / 链接 / URL（占位符），修复后原样放回
 * 1. 分隔线+标题：` --- ### ` → `\n\n---\n\n### `
 * 2. 句末后标题：`。 ### ` → `。\n\n### `
 * 3. 冒号后引用：`： > 文本` → `：\n> 文本`
 * 4. 连续有序列表：同行 ≥2 项、从 1 起、严格连续 → 编号前插换行
 * 5. 无序列表（保守）：同行 ≥2 个 `- ` 且每项含中文冒号/比较符 → 拆行
 */

/** 保护 code/公式/链接/URL：替换成占位符并保存原文，修复完成后原样放回。 */
const PROTECT_PATTERNS: RegExp[] = [
  /```[\s\S]*?```/g,
  /`[^`\n]+`/g,
  /\$\$[\s\S]*?\$\$/g,
  /\$[^$\n]+?\$/g,
  /\[[^\]]*\]\([^)]*\)/g,
  /https?:\/\/[^\s)\]]+/g,
];

function protectSensitive(text: string): { masked: string; originals: string[] } {
  const originals: string[] = [];
  let masked = text;
  for (const pattern of PROTECT_PATTERNS) {
    masked = masked.replace(pattern, (match) => {
      const token = `\u0000LEGACY_PROTECT_${originals.length}\u0000`;
      originals.push(match);
      return token;
    });
  }
  return { masked, originals };
}

function restoreSensitive(masked: string, originals: string[]): string {
  let restored = masked;
  originals.forEach((original, index) => {
    restored = restored.replace(`\u0000LEGACY_PROTECT_${index}\u0000`, () => original);
  });
  return restored;
}

/** 单行内紧凑编号列表拆分：≥2 项、从 1 起、严格连续才拆（与后端规则一致）。 */
function normalizeCompactNumberedLine(line: string): string {
  const items = [...line.matchAll(/(^|[\s:：])(\d+)\.\s/g)];
  if (items.length < 2) return line;

  const numbers = items.map((m) => parseInt(m[2], 10));
  if (numbers[0] !== 1) return line;
  for (let i = 1; i < numbers.length; i++) {
    if (numbers[i] !== numbers[i - 1] + 1) return line;
  }

  let result = line;
  for (let i = items.length - 1; i >= 0; i--) {
    const match = items[i];
    const numStart = (match.index ?? 0) + match[0].length - match[2].length - 2;
    const separator = i === 0 ? '\n\n' : '\n';
    result = result.slice(0, numStart) + separator + result.slice(numStart);
  }
  return `${result}\n`;
}

/** 保守无序列表拆分：同行 ≥2 个 `- ` 候选且每项含中文冒号/比较符才拆。 */
function splitCompactUlLine(line: string): string {
  const candidates = [...line.matchAll(/(?<=[\s：:])-\s(?=[^\d\s-])/g)];
  if (candidates.length < 2) return line;

  const itemStarts: number[] = [];
  for (const match of candidates) {
    const rest = line.slice(match.index! + match[0].length);
    // 列表项特征：含中文冒号「：」或比较符（> < >= <= = 后跟数字/字母）
    if (/[：:]|[<>]=?\s*\d|[<>]\s*[A-Za-zΔ]/.test(rest)) {
      itemStarts.push(match.index!);
    }
  }
  if (itemStarts.length < 2) return line;

  let result = line;
  for (let i = itemStarts.length - 1; i > 0; i--) {
    const start = itemStarts[i];
    result = result.slice(0, start).replace(/\s+$/, '') + '\n' + result.slice(start);
  }
  const first = itemStarts[0];
  result = result.slice(0, first).replace(/\s+$/, '') + '\n' + result.slice(first);
  return result;
}

/** 修复单行 markdown 的高置信规则（逐行处理）。 */
function repairLine(line: string): string {
  let out = line;
  // 1. 分隔线+标题：` --- ### ` → 空行 + 分隔线 + 空行 + 标题
  out = out.replace(/\s+---\s+(?=#{1,6}\s)/, '\n\n---\n\n');
  // 2. 句末后标题：`。 ### ` → `。\n\n### `
  out = out.replace(/(?<=[。！？!?；;])\s+(#{1,6})\s+/, '\n\n$1 ');
  // 3. 冒号后引用：`： > 文本` → `：\n> 文本`
  out = out.replace(/([：:])\s+>\s+(?=[^0-9+\-=<>])/, '$1\n> ');
  // 4. 连续有序列表
  out = normalizeCompactNumberedLine(out);
  // 5. 保守无序列表
  out = splitCompactUlLine(out);
  return out;
}

/**
 * 保守修复历史单行 markdown（幂等：已规范文本不变）。
 * 供 MarkdownContent 渲染前调用，覆盖历史消息/缓存数据。
 */
export function repairLegacyMarkdown(content: string): string {
  if (!content || !content.trim()) return content;
  const { masked, originals } = protectSensitive(content);
  const repaired = masked.split('\n').map(repairLine).join('\n');
  return restoreSensitive(repaired, originals);
}
