import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { MarkdownContent } from '@/shared/components/MarkdownContent';

describe('Markdown mathematical notation', () => {
  it('renders fractions from the real assistant delimiters and standard dollar notation', () => {
    const { container } = render(<MarkdownContent content={String.raw`例子：\(\frac{2}{7}+\frac{3}{7}=\frac{5}{7}\)。也可以写 $x^2$。`} />);
    expect(container.querySelectorAll('.katex')).toHaveLength(2);
    expect(container.querySelector('math mfrac')).not.toBeNull();
    expect(container.querySelector('math annotation')?.textContent).toContain('\\frac{2}{7}');
  });

  it('renders display delimiters across lines', () => {
    const { container } = render(<MarkdownContent content={String.raw`公式：
\[
\frac{1}{2}+\frac{1}{2}=1
\]`} />);
    expect(container.querySelector('.katex-display math mfrac')).not.toBeNull();
  });

  it('preserves dollar math blocks and literal replacement patterns inside code', () => {
    const { container } = render(<MarkdownContent content={'$$\nx^2\n$$\n\n`$$ $&`'} />);
    expect(container.querySelector('.katex-display')).not.toBeNull();
    expect(container.querySelector('code')?.textContent).toBe('$$ $&');
  });

  it('keeps inline, fenced and indented code literal', () => {
    const expression = String.raw`\(\frac{1}{2}\)`;
    const content = ['`' + expression + '`', '', '```txt', expression, '```', '', '~~~txt', expression, '~~~', '', '    ' + expression, '', 'Outside: ' + expression].join('\n');
    const { container } = render(<MarkdownContent content={content} />);
    expect(container.querySelectorAll('.katex')).toHaveLength(1);
    expect(container.querySelectorAll('code')).toHaveLength(4);
    for (const code of container.querySelectorAll('code')) {
      expect(code.textContent?.trim()).toBe(expression);
      expect(code.querySelector('.katex')).toBeNull();
    }
  });

  it('does not enable raw HTML, unsafe links or trusted LaTeX commands', () => {
    const { container } = render(<MarkdownContent content={String.raw`<img src="x" onerror="alert(1)">

$\href{javascript:alert(1)}{click}$

$\includegraphics{https://example.invalid/tracker.png}$`} />);
    expect(container.querySelector('img,script,iframe')).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(container.querySelector('.katex')).not.toBeNull();
  });

  it('keeps invalid math visible without removing the surrounding answer', () => {
    const { container } = render(<MarkdownContent content={String.raw`前文 $\frac{1}$ 后文`} />);
    expect(container.textContent).toContain('前文');
    expect(container.textContent).toContain('后文');
    expect(container.querySelector('.katex-error')).not.toBeNull();
  });
});
