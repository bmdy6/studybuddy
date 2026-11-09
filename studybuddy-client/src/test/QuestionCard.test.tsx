import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import QuestionCard from '@/shared/components/QuestionCard';

describe('QuestionCard', () => {
  it('保留题干中的换行和空白', () => {
    render(
      <QuestionCard
        question={{
          id: 1,
          type: 'essay',
          stem: '第一行\n第二行',
          options: null,
          score: 10,
          group_id: null,
        }}
        index={0}
        value=""
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText(/第一行/)).toHaveStyle({ whiteSpace: 'pre-wrap' });
  });

  it('多空填空题提示按顺序输入答案', () => {
    render(
      <QuestionCard
        question={{
          id: 2,
          type: 'fill_blank',
          stem: '______ you ______ (visit) your grandparents?',
          options: null,
          score: 10,
          group_id: null,
        }}
        index={0}
        value=""
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByPlaceholderText('多个空请按顺序用空格填写，如：Did visit')).toBeInTheDocument();
  });

  it('多空转换题的省略号也提示按顺序输入答案', () => {
    render(
      <QuestionCard
        question={{
          id: 3,
          type: 'transform',
          stem: 'Did ... visit ... yesterday?',
          options: null,
          score: 10,
          group_id: null,
        }}
        index={0}
        value=""
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByPlaceholderText('多个空请按顺序用空格填写，如：Did visit')).toBeInTheDocument();
  });
});
