import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { NoteDraftPanel } from '@/features/chat/components/NoteDraftPanel';
import type { NoteDraftState } from '../types';

vi.mock('@/features/chat/components/MessageBubble', () => ({
  MarkdownContent: ({ content }: { content: string }) => <div data-testid="md">{content}</div>,
}));

const state: NoteDraftState = {
  id: 1,
  title: '一般过去时',
  subject: 'english',
  category: '语法',
  content: '## 要点\n表示过去发生的动作，常加 -ed',
  knowledge_tags: ['过去时'],
  source: '素材整理',
  status: 'draft',
};

describe('NoteDraftPanel', () => {
  it('预览草案：显示标题/分类/学科 + 就这样存/改一下', () => {
    render(<NoteDraftPanel state={state} onConfirm={() => {}} />);
    expect(screen.getByText('一般过去时')).toBeInTheDocument();
    expect(screen.getByText('语法')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /就这样存/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /改一下/ })).toBeInTheDocument();
  });

  it('点就这样存 -> onConfirm({ status: "confirmed" })', () => {
    const onConfirm = vi.fn();
    render(<NoteDraftPanel state={state} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole('button', { name: /就这样存/ }));
    expect(onConfirm).toHaveBeenCalledWith({ status: 'confirmed' });
  });

  it('改一下 -> 编辑标题后保存入库 -> onConfirm 带编辑字段 + confirmed', () => {
    const onConfirm = vi.fn();
    render(<NoteDraftPanel state={state} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole('button', { name: /改一下/ }));
    fireEvent.change(screen.getByDisplayValue('一般过去时'), {
      target: { value: '一般过去时（改）' },
    });
    fireEvent.click(screen.getByRole('button', { name: /保存入库/ }));
    expect(onConfirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: '一般过去时（改）', status: 'confirmed' }),
    );
  });
});
