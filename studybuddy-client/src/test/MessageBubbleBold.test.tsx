import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { MessageBubble } from '@/features/chat/components/MessageBubble';

describe('MessageBubble 轻练正文 markdown 渲染', () => {
  it('含 ** 加粗的轻练正文渲染为 strong，不出现字面星号', () => {
    const content =
      '不对哦，24 × 5 = **120**，不是 180。\n\n\n下一题：\n\n\n**第 2 题：36 ÷ 9 = ?**\n';
    render(
      <MemoryRouter>
        <MessageBubble msg={{ id: 'm1', role: 'assistant', content }} />
      </MemoryRouter>,
    );
    // 正文渲染为加粗（strong），无字面星号
    const bold = screen.getByText('120');
    expect(bold.tagName).toBe('STRONG');
    expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument();
    // 题目行也渲染为加粗
    expect(screen.getByText('第 2 题：36 ÷ 9 = ?').tagName).toBe('STRONG');
  });
});
