import type { Root, RootContent } from 'mdast';
import remarkMath from 'remark-math';
import remarkParse from 'remark-parse';
import { unified } from 'unified';

const parser = unified().use(remarkParse).use(remarkMath);
const protectedTypes = new Set(['code', 'inlineCode', 'html', 'link', 'image', 'definition', 'math', 'inlineMath']);

/** Convert model-style LaTeX delimiters without rewriting Markdown code or destinations. */
export function normalizeMathDelimiters(content: string): string {
  if (!content.includes('\\(') && !content.includes('\\[')) return content;
  const protectedRanges: [number, number][] = [];
  function collect(node: Root | RootContent) {
    if (protectedTypes.has(node.type)) {
      const start = node.position?.start.offset;
      const end = node.position?.end.offset;
      if (start !== undefined && end !== undefined) protectedRanges.push([start, end]);
    } else if ('children' in node) {
      node.children.forEach(collect);
    }
  }
  collect(parser.parse(content));
  return content.replace(/(?<!\\)\\\(([\s\S]*?)(?<!\\)\\\)|(?<!\\)\\\[([\s\S]*?)(?<!\\)\\\]/g,
    (match, inline: string | undefined, display: string | undefined, offset: number) => {
      if (protectedRanges.some(([start, end]) => offset < end && offset + match.length > start)) return match;
      return inline !== undefined ? `$${inline.trim()}$` : `\n\n$$\n${display?.trim()}\n$$\n\n`;
    });
}
